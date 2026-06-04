"""EXPERIMENT: A little child talking to Bhagwan Shiv in a park (Yelefinn-style).

Matches the reference reel the user liked: a small kid sitting in a park having
a sweet emotional conversation with Mahadev. Flat cute cartoon, two voices —
the child speaks in a cute high voice, Shiva answers in a calm deep voice.

  - flat 2D cartoon ART STYLE, child + Shiva consistent via one master scene
  - a short comforting Hindi dialogue (kid asks, Mahadev reassures)
  - TWO edge-tts voices stitched per line, with synced captions + image timing
  - soft, no epic war drums

Run: .venv/bin/python -m scripts.experiment_shiva_child_pov
     .venv/bin/python -m scripts.experiment_shiva_child_pov --reuse-master
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from pipeline.assembler import assemble
from pipeline.char_consistent import _fal_upload, generate_scene_with_reference
from pipeline.image_gen import _generate_fal_flux
from pipeline.kling_video import generate_hero_clip
from pipeline.tts import _audio_duration_seconds, _edge_synth_with_boundaries
from pipeline.utils import out_path, set_active_niche, today_stamp

# ── Locked look + style (cute flat cartoon, two characters) ───────────────
ART_STYLE = (
    "flat 2D cartoon animation style — simple clean thick black outlines, flat "
    "bright cel-shaded colors, cute wholesome children's-storybook look, minimal "
    "shading, soft warm pastel background, adorable Instagram devotional cartoon"
)
LOOK = (
    "a scene with TWO characters: (1) a cute little human child, about 5 years "
    "old, big round eyes, chubby cheeks, simple modern clothes, adorable and "
    "innocent; and (2) Lord Shiva (Mahadev) as a kind gentle deity — matted "
    "jata top-knot hair, a crescent moon, a blue throat, rudraksha bead malas, "
    "a trishul (trident), serene loving smile, soft divine glow — both sitting "
    "together on green grass in a sunny green park"
)
CHAR_NAME = "the little child and Lord Shiva"

# Master is a TWO-character wide shot (single-character "portrait" framing drops
# the child), so build it directly with an explicit two-shot prompt.
MASTER_PROMPT = (
    f"{ART_STYLE}. Wide two-character scene, both fully visible: on the LEFT a "
    "cute little human child about 5 years old with big round eyes and chubby "
    "cheeks, sitting on the green grass; on the RIGHT Lord Shiva (Mahadev) — "
    "matted jata top-knot hair, a crescent moon, a blue throat, rudraksha bead "
    "malas, holding a trishul, serene loving smile — sitting cross-legged. They "
    "are together in a sunny green park, the child looking up at Shiva. Full "
    "body, wholesome devotional cartoon, vertical 9:16."
)

# ── Emotional dialogue. One line = one scene = one image (1:1). ───────────
# speaker: "child" (cute innocent voice) or "shiva" (calm deep voice)
DIALOGUE = [
    ("child", "भोले बाबा... सब कहते हैं मैं किसी काम का नहीं।"),
    ("shiva", "जिसे मैंने खुद बनाया, वो भला बेकार कैसे हो सकता है?"),
    ("child", "पर जब मैं रात में अकेले रोता हूँ, तब आप कहाँ होते हो?"),
    ("shiva", "जो आँसू तू अकेले में बहाता है, सबसे पहले मैं उन्हें पोंछता हूँ।"),
    ("child", "सच में? आप मुझे कभी नहीं छोड़ोगे ना?"),
    ("shiva", "कभी नहीं मेरे बच्चे। तू बस मुझे याद रखना। हर हर महादेव।"),
]

VISUALS = [
    "the little child sitting on the grass, looking down sad and dejected with "
    "teary eyes, feeling worthless, soft overcast light",
    "Lord Shiva gently lifting the child's chin with one finger, looking at him "
    "with deep loving compassion, warm reassuring smile",
    "the little child curled up hugging their knees, a single tear on their "
    "cheek, looking up with a trembling lip, soft sad evening light",
    "Lord Shiva gently wiping the tear from the child's cheek with his thumb, "
    "tender caring expression, a soft warm glow surrounding them",
    "the little child looking up at Lord Shiva with hopeful shining wet eyes and "
    "a small trusting smile, gentle golden light",
    "Lord Shiva placing a protective hand on the child's head, both smiling "
    "warmly, radiant divine light, peaceful loving blessing in the park",
]

# Keep Shiva's identity human and divine (avoid the furry/monkey drift)
SHIVA_FACE_ANCHOR = (
    " Lord Shiva has a calm handsome human-featured face with a neat trimmed "
    "beard — NOT a monkey, NOT a furry face."
)

VOICES = {
    # voice, rate, pitch  — child = slow + high = innocent/masoom
    "child": ("hi-IN-SwaraNeural", "-12%", "+45Hz"),
    "shiva": ("hi-IN-MadhurNeural", "-10%", "-12Hz"),
}
GAP = 0.4  # seconds of silence between dialogue lines

# Add gentle real motion (Kling I2V) to these scene indices. Empty = stills only.
ANIMATE_INDICES = {0, 1, 2, 3, 4, 5}
KLING_MOTION = (
    "very gentle subtle animation: the characters breathe softly and blink, hair "
    "and grass sway slightly in a soft breeze, warm light gently shimmers, calm "
    "slow emotional motion, no large movement, no camera shake"
)


def _clean_words(line: str) -> list[str]:
    return [w.strip(",.।॥!?;:\"'()") for w in line.split() if w.strip(",.।॥!?;:\"'()")]


def synth_dialogue(out_file: Path) -> None:
    """Synthesize each dialogue line with its speaker's voice, stitch them with
    small gaps, and write matching words.json + sentences.json sidecars."""
    work = out_file.parent / f"_pov_{out_file.stem}"
    work.mkdir(parents=True, exist_ok=True)

    # uniform silence spacer (24kHz mono mp3 to match edge-tts output)
    sil = work / "sil.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-t", str(GAP),
         "-i", "anullsrc=r=24000:cl=mono", "-c:a", "libmp3lame", "-ar", "24000",
         "-ac", "1", str(sil)],
        capture_output=True,
    )

    seg_files: list[Path] = []
    sentences: list[dict] = []
    words: list[dict] = []
    cursor = 0.0
    for i, (spk, line) in enumerate(DIALOGUE):
        voice, rate, pitch = VOICES[spk]
        seg = work / f"line_{i:02d}.mp3"
        asyncio.run(_edge_synth_with_boundaries(line, seg, voice, rate, pitch))
        dur = _audio_duration_seconds(seg)
        start, end = cursor, cursor + dur
        sentences.append({"text": line, "start": round(start, 3), "end": round(end, 3)})
        ws = _clean_words(line)
        weights = [max(1, len(w)) for w in ws]
        tot = sum(weights) or 1
        c = 0
        for w, wt in zip(ws, weights):
            s = start + (c / tot) * dur
            c += wt
            e = start + (c / tot) * dur
            words.append({"text": w, "start": round(s, 3), "end": round(e, 3)})
        seg_files.append(seg)
        cursor = end + GAP

    # concat (re-encode to uniform mp3 so timing is exact)
    listf = work / "list.txt"
    parts = []
    for i, seg in enumerate(seg_files):
        parts.append(f"file '{seg.resolve()}'")
        if i < len(seg_files) - 1:
            parts.append(f"file '{sil.resolve()}'")
    listf.write_text("\n".join(parts), encoding="utf-8")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listf),
         "-c:a", "libmp3lame", "-ar", "24000", "-ac", "1", str(out_file)],
        capture_output=True,
    )

    out_file.with_suffix(".words.json").write_text(
        json.dumps(words, indent=2, ensure_ascii=False), encoding="utf-8")
    out_file.with_suffix(".sentences.json").write_text(
        json.dumps(sentences, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[tts] 2-voice dialogue stitched → {len(DIALOGUE)} lines, "
          f"{len(words)} words, {cursor - GAP:.1f}s")


SCRIPT = {
    "title": "POV: एक बच्चे ने भोलेनाथ से बात की 🥹🔱",
    "hook": DIALOGUE[0][1],
    "body": [l for _, l in DIALOGUE[1:-1]],
    "cta": DIALOGUE[-1][1],
    "description": "Ek masoom bachche aur Bhole Baba ki pyaari baat. "
                   "#Mahadev #Shiv #Bhakti #Shorts",
    "hashtags": ["#Mahadev", "#Shiv", "#HarHarMahadev", "#Bhakti", "#Shorts"],
}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse-master", action="store_true")
    ap.add_argument("--no-animate", action="store_true", help="skip Kling, stills only")
    args = ap.parse_args(argv)

    set_active_niche("bhakti")
    base = f"{today_stamp()}_experiment_shiva_child_pov"
    img_dir = out_path("images", base)
    img_dir.mkdir(parents=True, exist_ok=True)
    print("== EXPERIMENT: child talks to Bhagwan Shiv in a park (flat cartoon, 2 voices) ==")

    out_path("scripts", f"{base}.json").write_text(
        json.dumps(SCRIPT, indent=2, ensure_ascii=False), encoding="utf-8")

    # 1. Master scene (child + Shiva together, flat cartoon)
    master = img_dir / "master_shiva_child.jpg"
    if args.reuse_master and master.exists():
        print("[char] reusing existing master")
    elif not _generate_fal_flux(MASTER_PROMPT, master):
        print("[fatal] master failed")
        return 1
    else:
        print(f"[char] master (child + Shiva) → {master.name}")
    master_url = _fal_upload(master)
    if not master_url:
        print("[fatal] master upload failed")
        return 1

    # 2. Scenes referencing the master (same two characters, same style)
    images: list[Path] = []
    for i, action in enumerate(VISUALS):
        path = img_dir / f"img_{i:02d}.jpg"
        # Shiva-led beats (odd indices) get the human-face anchor to stop drift
        prompt_action = action + (SHIVA_FACE_ANCHOR if i % 2 == 1 else "")
        if generate_scene_with_reference(master_url, prompt_action, path,
                                         char_name=CHAR_NAME, art_style=ART_STYLE):
            images.append(path)
            print(f"[scene {i+1}/{len(VISUALS)}] ok")
        else:
            print(f"[scene {i+1}/{len(VISUALS)}] FAILED")

    if len(images) < len(VISUALS):
        print(f"[fatal] only {len(images)}/{len(VISUALS)} scenes — aborting")
        return 1

    # 3. Two-voice dialogue FIRST, so we know each scene's on-screen duration
    voice_path = out_path("audio", f"{base}.mp3")
    synth_dialogue(voice_path)
    sentences = json.loads(voice_path.with_suffix(".sentences.json").read_text())
    durations = [s["end"] - s["start"] for s in sentences]

    # 4. Add gentle real motion to chosen scenes via Kling (duration ≈ scene len)
    hero_clips: dict[int, Path] = {}
    if ANIMATE_INDICES and not args.no_animate:
        clip_dir = out_path("videos", f"_kling_{base}")
        clip_dir.mkdir(parents=True, exist_ok=True)
        for i in sorted(ANIMATE_INDICES):
            if i >= len(images):
                continue
            secs = max(3, min(10, round(durations[i]) if i < len(durations) else 5))
            clip = clip_dir / f"hero_{i:02d}.mp4"
            print(f"[kling] animating scene {i+1} (~{secs}s)...")
            if generate_hero_clip(KLING_MOTION, images[i], clip, duration=secs):
                hero_clips[i] = clip
            else:
                print(f"[kling] scene {i+1} failed — staying a still")

    # 5. Assemble — soft (no epic music), NO captions
    video_path = out_path("videos", f"{base}.mp4")
    assemble(SCRIPT, voice_path, images, video_path,
             skip_music=True, skip_captions=True, hero_clips=hero_clips or None)

    print(f"\n[done] FINAL → {video_path}")
    print(f"[done] animated scenes: {sorted(i+1 for i in hero_clips)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
