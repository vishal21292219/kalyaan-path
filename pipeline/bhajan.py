"""Bhajan video pipeline — turns a Flow Music / Suno MP3 into a YT Shorts
vertical 9:16 video with deity-specific scene storyboard.

Flow:
  1. Pick newest unprocessed MP3 from data/music_bhajan/[deity]/
  2. Generate 5-6 scene image prompts via Gemini LLM (deity-specific storyboard)
  3. Generate scene images via Gemini Nano Banana 2 (with Pollinations fallback)
  4. Get MP3 duration, build vertical video with Ken Burns motion on each scene
  5. Add MP3 as audio (no TTS, no captions)
  6. Auto-thumbnail + endcard (reuses existing modules)
  7. Mark MP3 as processed in state file
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from .utils import ROOT, load_config

load_dotenv()

VALID_DEITIES = {"hanuman", "krishna", "shiva", "ram", "devi", "ganesh", "sai", "khatu_shyam", "general"}


def _audio_duration(audio_path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _load_processed_state(state_path: Path) -> set:
    if state_path.exists():
        try:
            return set(json.loads(state_path.read_text()))
        except Exception:
            return set()
    return set()


def _save_processed_state(state_path: Path, processed: set) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(sorted(processed), indent=2, ensure_ascii=False))


def pick_bhajan_audio(deity: str | None = None) -> tuple[Path, str] | None:
    """Pick newest unprocessed MP3 from data/music_bhajan/[deity]/ folders.
    If deity is None, picks across all deities (round-robin).
    Returns (mp3_path, deity_name) or None if nothing to process.
    """
    cfg = load_config()
    root = ROOT / cfg["paths"]["bhajan_audio_root"]
    state_path = ROOT / cfg["paths"]["processed_state"]
    processed = _load_processed_state(state_path)

    if not root.exists():
        print(f"[bhajan] no folder: {root}")
        return None

    deities_to_check = [deity] if deity else sorted(VALID_DEITIES)
    candidates: list[tuple[Path, str, float]] = []
    for d in deities_to_check:
        folder = root / d
        if not folder.is_dir():
            continue
        for mp3 in folder.glob("*.mp3"):
            if str(mp3.resolve()) in processed:
                continue
            candidates.append((mp3, d, mp3.stat().st_mtime))

    if not candidates:
        print("[bhajan] no unprocessed MP3s available")
        return None

    # Pick newest unprocessed
    candidates.sort(key=lambda x: x[2], reverse=True)
    mp3, picked_deity, _ = candidates[0]
    print(f"[bhajan] picked {mp3.name} ({picked_deity})")
    return mp3, picked_deity


def mark_audio_processed(mp3_path: Path) -> None:
    cfg = load_config()
    state_path = ROOT / cfg["paths"]["processed_state"]
    processed = _load_processed_state(state_path)
    processed.add(str(mp3_path.resolve()))
    _save_processed_state(state_path, processed)


DEITY_STYLE_GUIDE = {
    "krishna": (
        "STRICT: Focus on VRINDAVAN-era Krishna (childhood + youth) — NOT Mahabharata. "
        "Use settings: Vrindavan forests, Yamuna river, Govardhan hill, Vraj villages. "
        "Use motifs: bansuri flute, peacock feather crown, blue skin, yellow dhoti, cows, "
        "gopis, Radha, lotus ponds, Kadamba trees, butter pots, golden sunrise. "
        "INCLUDE Radha-Krishna scenes. EXCLUDE Kurukshetra, war, Vishvarupa, Arjuna."
    ),
    "hanuman": (
        "Focus on iconic Hanuman moments: baby with Anjani, flying to sun, "
        "Sanjeevani mountain rescue, at Ram's feet, Sundara Kand scenes, "
        "tearing chest to show Ram-Sita inside, gada in hand. "
        "Use saffron/orange dhoti, golden mace, divine aura."
    ),
    "shiva": (
        "Focus on Shiva forms: meditation on Kailash, Tandav cosmic dance, "
        "drinking Halahala poison (blue throat), with Ganga from hair, "
        "blessing devotees, third eye, trishul, damru, ash-smeared body, "
        "snake around neck, tiger skin, snow Himalayas backdrop."
    ),
    "ram": (
        "Focus on Ram's iconic moments: Ayodhya court, bow and arrow, "
        "forest exile with Sita and Lakshman, meeting Hanuman, Ram Setu, "
        "Lanka victory, blessing devotees, blue-skinned with yellow dhoti, "
        "peaceful divine expression. Include Sita and Hanuman in some scenes."
    ),
    "devi": (
        "Focus on Devi/Durga forms: riding lion/tiger, eight arms with weapons, "
        "trishul, sword, conch, chakra, defeating Mahishasura, blessing devotees, "
        "red saree, gold jewelry, third eye, fierce yet motherly expression."
    ),
    "ganesh": (
        "Focus on Ganesh: elephant head with one tusk, holding modak/laddu, "
        "mouse vehicle, four arms with axe-rope-lotus, blessing pose, "
        "yellow dhoti, garland of marigolds, joyful expression, family with "
        "Shiva-Parvati and Kartikeya in some scenes."
    ),
    "sai": (
        "Focus on Sai Baba of Shirdi: orange/saffron kafni robe, head cloth, "
        "sitting on stone, with dog/cat/devotees, dhuni fire, Shirdi mosque, "
        "wooden plank bed, simple peaceful expression, blessing pose, walking stick."
    ),
    "khatu_shyam": (
        "Focus on Khatu Shyam Ji (Barbarik, grandson of Bhima blessed by Krishna). "
        "Iconic imagery: young warrior with three glowing arrows (teen baan), "
        "head-only form (sheesh) atop a high hill overlooking Kurukshetra, severed "
        "head on a golden plate offered to Krishna, blue divine glow, peacock-feather "
        "crown (Shyam = Krishna's name), Khatu temple in Rajasthan, golden Shyam baba "
        "idol with red/saffron robes, 'Hare ka Sahara' tagline mood. Mix Mahabharata "
        "Kurukshetra battle scenes with peaceful temple devotion scenes."
    ),
}


def generate_scene_prompts(deity: str, n_scenes: int = 25) -> list[str]:
    """Use Gemini LLM to generate cinematic scene storyboard for a deity bhajan.
    Now with deity-specific style guidance to ensure scene relevance.
    """
    import google.generativeai as genai
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    genai.configure(api_key=api_key)

    cfg = load_config()
    persona = cfg["llm"]["persona"]
    deity_guide = DEITY_STYLE_GUIDE.get(deity, "")

    user = f"""Generate {n_scenes} cinematic visual scene prompts for a devotional bhajan video about Lord {deity.upper()}.

DEITY-SPECIFIC GUIDANCE (CRITICAL — follow strictly):
{deity_guide}

Each scene must:
- Be a vivid English image prompt (2-3 sentences)
- Be HIGHLY RELEVANT to the deity-specific guidance above
- Show MAXIMUM VARIETY in compositions:
  * Mix of close-up portraits + medium shots + wide cinematic shots
  * Different times of day (sunrise, golden hour, twilight, moonlit night)
  * Different settings (forest, river, palace, temple, garden, mountain)
  * Different emotional moods (peaceful, joyful, dramatic, blessing, devotional)
  * Different camera angles (eye-level, low angle epic, top-down devotional)
- Single dominant subject per scene (no crowded scenes)
- Anatomically correct (single head, two natural arms unless canonical multi-arm)
- Bright divine warm lighting, traditional Indian art style
- NO text, NO watermarks, NO modern objects
- NO repetition — each scene must be visually distinct from the others

Output ONLY a JSON array of {n_scenes} prompt strings (no markdown fences):
["prompt 1", "prompt 2", "prompt 3", ...]"""

    model = genai.GenerativeModel("gemini-flash-latest", system_instruction=persona)
    resp = model.generate_content(user, generation_config={"temperature": 0.92})
    text = resp.text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    s, e = text.find("["), text.rfind("]")
    if s == -1 or e == -1:
        raise ValueError(f"No JSON array in LLM output: {text[:200]}")
    prompts = json.loads(text[s : e + 1])
    print(f"[bhajan] generated {len(prompts)} scene prompts for {deity}")
    return prompts


def _generate_images(prompts: list[str], out_dir: Path) -> list[Path]:
    """Reuse existing image_gen module with bhajan config's image settings.
    Uses new Gemini-only generator (Pollinations removed); on failure
    raises GeminiUnavailable so caller can save to retry queue."""
    from .image_gen import _generate_gemini, GeminiUnavailable

    cfg = load_config()
    img_cfg = cfg["images"]
    model = img_cfg.get("model", "gemini-3.1-flash-image-preview")
    negative = img_cfg.get("negative", "")
    style = cfg["llm"].get("image_style_guidance", "")

    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for i, raw in enumerate(prompts):
        full_prompt = f"{raw}\n\nStyle guidance:\n{style}\n\nAvoid: {negative}"
        path = out_dir / f"scene_{i:02d}.jpg"
        try:
            if _generate_gemini(full_prompt, path, model):
                results.append(path)
        except GeminiUnavailable as e:
            print(f"[bhajan] scene {i} failed permanently: {e}")
            raise  # let run.py save to retry queue
    return results


def assemble_bhajan_video(
    mp3_path: Path,
    scene_images: list[Path],
    out_video: Path,
    title_text: str = "",
) -> Path:
    """Build vertical 9:16 bhajan video with:
    - Per-scene aggressive Ken Burns (8 motion variations, deeper zooms)
    - Crossfade transitions between EVERY scene (xfade filter chain)
    - MP3 as audio (no TTS, no captions)
    - Designed for NON-BORING flow at 25+ scenes per 3-min track.
    """
    cfg = load_config()
    W = cfg["video"]["width"]
    H = cfg["video"]["height"]
    FPS = cfg["video"]["fps"]

    duration = _audio_duration(mp3_path)
    if duration <= 0:
        raise RuntimeError(f"Could not read audio duration from {mp3_path}")

    N = len(scene_images)
    xfade_dur = float(cfg["images"].get("xfade_duration", 0.6))
    # Each clip plays per_scene then crossfades into next for xfade_dur.
    # Effective unique time per clip = per_scene - xfade_dur.
    # Total visible time = N*per_scene - (N-1)*xfade_dur = audio_duration
    # => per_scene = (audio_dur + (N-1)*xfade_dur) / N
    per_scene = (duration + (N - 1) * xfade_dur) / N
    per_frames = max(int(per_scene * FPS), 30)
    denom = max(per_frames - 1, 1)
    print(f"[bhajan] {N} scenes × {per_scene:.2f}s with {xfade_dur}s xfade "
          f"(audio={duration:.1f}s)")

    work = out_video.parent / f"_bhajan_work_{out_video.stem}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)

    # 8 dynamic motion variations — deeper zooms (1.0-1.35) for engagement
    pan = "(iw-iw/zoom)"
    motions = [
        ("1.00", "1.30", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),         # deep zoom in
        ("1.30", "1.00", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),         # deep zoom out
        ("1.10", "1.25", f"on*{pan}/{denom}", "ih/2-(ih/zoom/2)"),         # pan L→R + zoom
        ("1.25", "1.10", f"{pan}-on*{pan}/{denom}", "ih/2-(ih/zoom/2)"),   # pan R→L + zoom out
        ("1.10", "1.30", "iw/2-(iw/zoom/2)", f"ih/2-(ih/zoom/2)-on*ih*0.08/{denom}"),  # zoom + pan up
        ("1.30", "1.10", "iw/2-(iw/zoom/2)", f"ih/2-(ih/zoom/2)+on*ih*0.08/{denom}"),  # zoom + pan down
        ("1.05", "1.35", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),         # very deep zoom in
        ("1.35", "1.05", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),         # very deep zoom out
    ]

    # 1. Build per-scene clips
    clips = []
    for i, img in enumerate(scene_images):
        clip = work / f"clip_{i:02d}.mp4"
        z_s, z_e, x_expr, y_expr = motions[i % len(motions)]
        z_expr = f"({z_s})+(({z_e})-({z_s}))*on/{denom}"
        vf = (
            f"scale={W}:{H}:flags=lanczos:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1,"
            f"unsharp=lx=5:ly=5:la=1.2:cx=5:cy=5:ca=0.4,"
            f"eq=contrast=1.12:saturation=1.35:brightness=0.08:gamma=0.85,"
            f"zoompan=z='{z_expr}':x='{x_expr}':y='{y_expr}':"
            f"d={per_frames}:s={W}x{H}:fps={FPS},"
            f"format=yuv420p"
        )
        subprocess.run([
            "ffmpeg", "-y", "-loop", "1", "-i", str(img),
            "-t", f"{per_scene:.3f}",
            "-vf", vf, "-r", str(FPS),
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p", str(clip),
        ], capture_output=True)
        clips.append(clip)

    # 2. Chain xfade transitions between all clips
    print(f"[bhajan] chaining {N-1} crossfade transitions...")
    inputs_args = []
    for c in clips:
        inputs_args += ["-i", str(c)]

    filters = []
    last_label = "0:v"
    offset = per_scene - xfade_dur
    for i in range(1, N):
        new_label = f"v{i}"
        filters.append(
            f"[{last_label}][{i}:v]xfade=transition=fade:"
            f"duration={xfade_dur}:offset={offset:.3f}[{new_label}]"
        )
        last_label = new_label
        offset += per_scene - xfade_dur

    filter_complex = ";".join(filters)
    slides = work / "slides_xfade.mp4"
    r = subprocess.run([
        "ffmpeg", "-y", *inputs_args,
        "-filter_complex", filter_complex,
        "-map", f"[{last_label}]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(slides),
    ], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[bhajan] xfade failed, falling back to hard cuts:\n{r.stderr[-500:]}")
        # Fallback to concat
        concat_list = work / "concat.txt"
        concat_list.write_text("\n".join(f"file '{c.name}'" for c in clips))
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list), "-c", "copy", str(slides),
        ], capture_output=True)

    # 3. Mix audio
    out_video.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(slides),
        "-i", str(mp3_path),
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-movflags", "+faststart",
        str(out_video),
    ], capture_output=True)

    shutil.rmtree(work, ignore_errors=True)
    print(f"[bhajan] FINAL → {out_video} ({out_video.stat().st_size/1024/1024:.1f} MB)")
    return out_video


def build_bhajan_metadata(deity: str, mp3_name: str) -> dict:
    """Build a script-like dict so notifier_telegram + uploader can use it."""
    cfg = load_config()
    deity_cfg = cfg.get("deities", {}).get(deity, {})
    title_hint = deity_cfg.get("title_hint", f"{deity.title()} Bhajan")
    hook = deity_cfg.get("description_hook", "")

    track_name = re.sub(r"[_\-]", " ", mp3_name.replace(".mp3", "")).strip().title()
    title = f"{track_name} {title_hint} #Shorts"
    description = (
        f"{hook}\n\n"
        f"🎵 {track_name}\n"
        f"AI-generated devotional bhajan — pure, original, royalty-free.\n\n"
        f"🔔 Subscribe KalyaanPath for daily devotional content.\n\n"
        f"#Bhajan #{deity.title()}Bhajan #KalyaanPath #Bhakti #HinduBhajan "
        f"#SanatanDharma #DevotionalSong #Shorts #YouTubeShorts"
    )
    return {
        "title": title[:100],
        "description": description,
        "hashtags": [f"#{deity}bhajan", "#bhajan", "#bhakti", "#kalyaanpath",
                     "#hindubhajan", "#sanatandharma", "#shorts", "#youtubeshorts"],
        "kind": "bhajan",
        "deity": deity,
        "cta": hook,
        "hook": f"{track_name} — {title_hint}",
    }
