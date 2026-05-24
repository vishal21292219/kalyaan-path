"""Auto-clip a long-form video (15-25 min) into 3-4 viral Shorts (50-60 sec).

Used for the weekly long-form runs (Sunday Itihaasvani, Saturday TimeDecoders)
to multiply content surface area: 1 long-form → 1 long-form + 3 Shorts that
all promote each other.

Algorithm:
  1. Read words.json (per-word timing from TTS step) to identify natural
     sentence boundaries within the long-form narration.
  2. Use Gemini to pick N MOST VIRAL 50-60 sec clips from the full transcript:
       - opens with a strong hook line
       - has a self-contained mini-narrative arc
       - ends on a cliffhanger or punchy reveal
       - includes specific facts (numbers, names) — not generic setup
  3. For each clip, ffmpeg-cut the matching window of (video, audio,
     captions) and append a custom outro card:
       "Full video on @Channel — link in description"
  4. Generate metadata (title/description/tags) for each Short with a CTA
     back to the long-form.

Outputs:
  output/videos/{base}_short_01.mp4
  output/videos/{base}_short_02.mp4
  ...
  output/scripts/{base}_short_NN.json  (metadata per Short)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path
from typing import List, Dict, Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


# ─────────────────────────── Gemini clip picker ───────────────────────────

def _gemini_pick_clips(transcript_lines: List[Dict[str, Any]],
                       long_form_title: str,
                       n_clips: int,
                       target_sec: tuple = (45, 60)) -> List[Dict[str, Any]]:
    """Ask Gemini to identify N most viral non-overlapping clips from the
    transcript. Each line is dict {start, end, text}. Returns list of dicts
    {start_sec, end_sec, title_hook, why_viral}.
    """
    import google.generativeai as genai
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY missing")
    genai.configure(api_key=api_key)

    # Build a compact transcript view
    compact = "\n".join(
        f"[{i:03d}] {ln['start']:.1f}-{ln['end']:.1f}s: {ln['text'].strip()}"
        for i, ln in enumerate(transcript_lines)
    )

    sys_prompt = (
        "You are a top YouTube Shorts strategist. Pick the N most viral "
        f"{target_sec[0]}-{target_sec[1]} second segments from the transcript "
        "of a long-form video. Each pick MUST:\n"
        "  - Open with a strong hook (curiosity, shocking claim, question)\n"
        "  - Be a self-contained mini-narrative\n"
        "  - End on a cliffhanger / punchy reveal\n"
        "  - Contain at least one specific fact (number, name, date, place)\n"
        "  - NOT overlap with other picks (different parts of the video)\n"
        "  - NOT be the intro or outro of the long-form\n"
        "Output ONLY valid JSON: a list of N objects, each with keys:\n"
        "  start_line: int (line number in transcript)\n"
        "  end_line: int (line number in transcript)\n"
        "  estimated_duration_sec: int\n"
        "  hook_title: str (≤70 chars, ready-to-use YT Shorts title with 1 emoji)\n"
        "  why_viral: str (1 sentence — why this 50-sec clip will pop)\n"
        "NO markdown fences. Return the raw JSON array."
    )

    user = (
        f"LONG-FORM TITLE: {long_form_title}\n\n"
        f"TARGET CLIPS: {n_clips}\n"
        f"TARGET DURATION PER CLIP: {target_sec[0]}-{target_sec[1]} seconds\n\n"
        f"TRANSCRIPT (line# start-end seconds: text):\n{compact}\n\n"
        "Return the JSON array of viral clip selections."
    )

    m = genai.GenerativeModel("gemini-flash-latest", system_instruction=sys_prompt)
    resp = m.generate_content(user, generation_config={"temperature": 0.7})
    raw = resp.text.strip()
    # Strip code fences if model added them
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    picks = json.loads(raw)

    # Convert line numbers to actual time windows
    result = []
    for p in picks:
        try:
            start_ln = transcript_lines[p["start_line"]]
            end_ln = transcript_lines[p["end_line"]]
            result.append({
                "start_sec": float(start_ln["start"]),
                "end_sec": float(end_ln["end"]),
                "hook_title": p.get("hook_title", "")[:90],
                "why_viral": p.get("why_viral", ""),
            })
        except (IndexError, KeyError) as e:
            print(f"  [clip-pick] skipping bad pick: {e}")
    return result


# ─────────────────────────── Video cutter ───────────────────────────

def _cut_clip(source_video: Path, start_sec: float, end_sec: float,
              out_path: Path) -> bool:
    """ffmpeg-cut a sub-clip from the source. Re-encodes for clean cut."""
    dur = end_sec - start_sec
    cmd = [
        "ffmpeg", "-y",
        "-ss", f"{start_sec:.3f}", "-i", str(source_video),
        "-t", f"{dur:.3f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(out_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  [ffmpeg-cut] FAIL: {r.stderr[-400:]}")
        return False
    return True


# ─────────────────────────── Outro card ───────────────────────────

def _append_outro(clip_path: Path, channel_handle: str,
                  outro_sec: float = 3.0) -> Path:
    """Append a 3-sec outro card pointing viewer to the long-form.
    Card: dark background + "Watch FULL video on @Channel" text.
    """
    from PIL import Image, ImageDraw, ImageFont
    import tempfile

    W, H = 1080, 1920
    # Build outro frame
    img = Image.new("RGB", (W, H), (15, 15, 25))
    draw = ImageDraw.Draw(img)
    anton = str(ROOT / "assets/fonts/Anton-Regular.ttf")
    khand = str(ROOT / "assets/fonts/Khand-Bold.ttf")

    f_top = ImageFont.truetype(anton, 110)
    f_handle = ImageFont.truetype(anton, 130)
    f_sub = ImageFont.truetype(khand, 70)

    line1 = "WATCH THE"
    line2 = "FULL VIDEO"
    line3 = channel_handle
    line4 = "Link in description ⬇"

    def center_y(text, font, y, fill, stroke=8):
        bb = draw.textbbox((0, 0), text, font=font, stroke_width=stroke)
        w = bb[2] - bb[0]
        draw.text(((W - w) // 2, y), text, fill=fill, font=font,
                  stroke_width=stroke, stroke_fill=(0, 0, 0))

    center_y(line1, f_top, 600, (255, 230, 100))
    center_y(line2, f_top, 740, (255, 230, 100))
    center_y(line3, f_handle, 950, (0, 220, 255))
    center_y(line4, f_sub, 1150, (255, 255, 255), stroke=4)

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tf:
        outro_jpg = Path(tf.name)
    img.save(str(outro_jpg), quality=95)

    # Build a silent outro video clip from the image
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tf:
        outro_mp4 = Path(tf.name)
    subprocess.run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(outro_jpg),
        "-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t", f"{outro_sec:.3f}",
        "-vf", f"scale={W}:{H}:flags=lanczos,setsar=1,format=yuv420p",
        "-r", "30",
        "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-shortest",
        str(outro_mp4),
    ], capture_output=True)

    # Concat clip + outro
    final = clip_path.with_name(clip_path.stem + "_with_outro.mp4")
    concat_txt = final.with_suffix(".txt")
    concat_txt.write_text(f"file '{clip_path}'\nfile '{outro_mp4}'\n")
    r = subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_txt),
        "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
        str(final),
    ], capture_output=True, text=True)
    concat_txt.unlink(missing_ok=True)
    outro_jpg.unlink(missing_ok=True)
    outro_mp4.unlink(missing_ok=True)

    if r.returncode != 0:
        print(f"  [outro] FAIL: {r.stderr[-400:]}")
        return clip_path  # fallback to clip without outro
    clip_path.unlink(missing_ok=True)  # remove pre-outro version
    return final


# ─────────────────────────── Public API ───────────────────────────

def clip_long_form(video_path: Path, words_json_path: Path, long_form_script: dict,
                   niche: str, n_clips: int = 3, out_dir: Path | None = None) -> List[Dict]:
    """Clip a long-form video into N viral Shorts.

    Args:
      video_path: Path to the long-form .mp4
      words_json_path: Path to .words.json (per-word timing from TTS)
      long_form_script: The long-form's script dict (for title context)
      niche: bhakti / itihaas / ancient
      n_clips: How many Shorts to produce (default 3)
      out_dir: Where to write Shorts (defaults to video_path's parent)

    Returns:
      List of dicts: {clip_path, metadata_path, hook_title, why_viral, start_sec, end_sec}
    """
    from .utils import load_config, set_active_niche
    set_active_niche(niche)
    cfg = load_config()

    out_dir = out_dir or video_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    base = video_path.stem

    # 1. Load word-timing → reconstruct sentence-level transcript
    words = json.loads(words_json_path.read_text())
    sentences = _words_to_sentences(words)
    print(f"[clip] {len(words)} words → {len(sentences)} sentences over "
          f"{sentences[-1]['end']:.0f}s long-form")

    # 2. Pick N viral clips via Gemini
    long_title = long_form_script.get("title", "Long-form video")
    picks = _gemini_pick_clips(sentences, long_title, n_clips)
    print(f"[clip] Gemini picked {len(picks)} clips:")
    for i, p in enumerate(picks, 1):
        print(f"  {i}. [{p['start_sec']:.0f}-{p['end_sec']:.0f}s] {p['hook_title']}")
        print(f"     why: {p['why_viral']}")

    # 3. Cut each clip + append outro
    channel_handle = cfg.get("branding", {}).get("channel_handle", f"@{niche.title()}")
    results = []
    for i, pick in enumerate(picks, 1):
        clip_out = out_dir / f"{base}_short_{i:02d}.mp4"
        print(f"[clip] cutting #{i} → {clip_out.name}")
        if not _cut_clip(video_path, pick["start_sec"], pick["end_sec"], clip_out):
            print(f"  [clip] skipping #{i} (cut failed)")
            continue
        final_clip = _append_outro(clip_out, channel_handle)
        print(f"  ✓ {final_clip.name} ({final_clip.stat().st_size/1024/1024:.1f} MB)")

        # 4. Generate metadata for this Short
        meta = _build_short_metadata(pick, long_form_script, channel_handle, niche)
        meta_path = out_dir / f"{base}_short_{i:02d}.json"
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))

        results.append({
            "clip_path": str(final_clip),
            "metadata_path": str(meta_path),
            "hook_title": pick["hook_title"],
            "why_viral": pick["why_viral"],
            "start_sec": pick["start_sec"],
            "end_sec": pick["end_sec"],
        })

    return results


def _words_to_sentences(words: List[Dict]) -> List[Dict]:
    """Group word-timings into sentence-like chunks (~4-8 sec each)."""
    if not words:
        return []
    out = []
    cur_start = None
    cur_text = []
    cur_words = []
    for w in words:
        wt = w.get("text", "").strip()
        ws = float(w.get("start", 0))
        we = float(w.get("end", ws + 0.1))
        if cur_start is None:
            cur_start = ws
        cur_text.append(wt)
        cur_words.append(w)
        # Close sentence on punctuation or after ~6 sec
        if (wt.endswith((".", "?", "!", "।")) or (we - cur_start) > 6.0):
            out.append({"start": cur_start, "end": we, "text": " ".join(cur_text)})
            cur_start = None
            cur_text = []
            cur_words = []
    if cur_text:
        out.append({"start": cur_start or 0, "end": words[-1].get("end", 0), "text": " ".join(cur_text)})
    return out


def _build_short_metadata(pick: Dict, long_form_script: Dict, channel_handle: str,
                          niche: str) -> Dict:
    """Build a script-dict-shaped metadata file for the Short (compatible with
    uploader_youtube.py format if user wants to auto-publish later)."""
    long_title = long_form_script.get("title", "")
    short_title = pick["hook_title"]
    if not short_title:
        short_title = (long_title[:50] + " 🔥") if long_title else "Viral Short 🔥"

    desc_lines = [
        f"🎬 Part of: {long_title}",
        "",
        pick.get("why_viral", ""),
        "",
        f"▶️ WATCH THE FULL VIDEO on {channel_handle} (link in description)",
        "",
        f"🔔 Subscribe {channel_handle} for daily content",
        "",
        "📩 Business: gopulabs@gmail.com",
        "",
        f"#Shorts #YouTubeShorts {channel_handle.replace('@','#')}",
    ]
    base_hashtags = {
        "bhakti": ["#KalyaanPath", "#Bhakti", "#Hinduism", "#SanatanDharma"],
        "itihaas": ["#Itihaasvani", "#Itihaas", "#Mahabharata", "#Ramayana"],
        "ancient": ["#TimeDecoders", "#AncientMysteries", "#LostHistory"],
    }.get(niche, [])
    return {
        "title": short_title[:95],
        "description": "\n".join(desc_lines),
        "hashtags": base_hashtags + ["#Shorts", "#YouTubeShorts"],
        "cta": f"Watch the full video on {channel_handle}",
        "source_long_form": long_title,
        "source_window_sec": [pick["start_sec"], pick["end_sec"]],
        "kind": "long_form_clip",
    }
