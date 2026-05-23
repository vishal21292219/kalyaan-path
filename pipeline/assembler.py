"""Compose final reel via ffmpeg.

Steps:
1. Read audio duration of the voiceover.
2. Split duration evenly across image slides.
3. Apply Ken Burns (zoompan) to each image → vertical 1080x1920.
4. Concatenate slides.
5. Render subtitle lines as PNGs via Pillow and overlay them at the right
   time windows (works on stock Homebrew ffmpeg, no libass needed).
6. Mix voiceover with optional background music (ducked under voice).
"""
from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .music import pick_music
from .utils import load_config

ROOT = Path(__file__).resolve().parent.parent

FONT_CANDIDATES = [
    # Project-local Google Fonts — viral display weights, top priority
    str(ROOT / "assets/fonts/Khand-Bold.ttf"),
    str(ROOT / "assets/fonts/MuktaVaani-Bold.ttf"),
    str(ROOT / "assets/fonts/AnekDevanagari.ttf"),
    str(ROOT / "assets/fonts/YatraOne-Regular.ttf"),
    str(ROOT / "assets/fonts/Khand-SemiBold.ttf"),
    # System Devanagari fallbacks
    "/System/Library/Fonts/Supplemental/Kohinoor.ttc",
    "/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc",
    "/System/Library/Fonts/Supplemental/ITF Devanagari.ttc",
    # Latin-only fallbacks
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
]


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    print("[ffmpeg]", " ".join(cmd[:6]), "...")
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd) if cwd else None)
    if res.returncode != 0:
        print(res.stderr[-2500:])
        raise RuntimeError(f"ffmpeg failed: {cmd[0]}")


def _audio_duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        text=True,
    )
    return float(out.strip())


def _find_font(size: int) -> ImageFont.FreeTypeFont:
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            try:
                return ImageFont.truetype(f, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


DEVANAGARI_FONTS = [
    "/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc",
    "/System/Library/Fonts/Supplemental/Kohinoor.ttc",
    "/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
]


def _find_dev_font(size: int) -> ImageFont.FreeTypeFont:
    for f in DEVANAGARI_FONTS:
        if Path(f).exists():
            try:
                return ImageFont.truetype(f, size=size)
            except Exception:
                continue
    return _find_font(size)


def _render_devanagari_png(text: str, max_width: int, font_size: int, out: Path) -> Path:
    """Render Sanskrit/Devanagari text via Pillow+raqm (proper conjunct shaping)."""
    font = _find_dev_font(font_size)
    # split shloka into two lines at danda (।) if present
    if "।" in text:
        raw_parts = text.split("।")
        parts = []
        for p in raw_parts:
            p = p.strip()
            if not p:
                continue
            # don't tack a danda onto a line that already ends in ॥
            if p.endswith("॥"):
                parts.append(p)
            else:
                parts.append(p + "।")
        wrapped = "\n".join(parts)
    else:
        wrapped = text

    pad_x, pad_y = 56, 36
    dummy = Image.new("RGBA", (10, 10))
    d = ImageDraw.Draw(dummy)
    bbox = d.multiline_textbbox((0, 0), wrapped, font=font, spacing=18,
                                 align="center", stroke_width=5)
    tw, th = int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])
    box_w = int(min(max_width, tw + pad_x * 2))
    box_h = int(th + pad_y * 2)

    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # warm semi-opaque background panel
    draw.rounded_rectangle([(0, 0), (box_w, box_h)], radius=32,
                            fill=(0, 0, 0, 165))
    draw.rounded_rectangle([(6, 6), (box_w - 6, box_h - 6)], radius=26,
                            outline=(255, 200, 80, 220), width=3)

    text_xy = ((box_w - tw) // 2 - bbox[0], (box_h - th) // 2 - bbox[1])
    draw.multiline_text(
        text_xy, wrapped,
        fill=(255, 224, 102, 255),
        stroke_width=5, stroke_fill=(0, 0, 0, 255),
        font=font, spacing=18, align="center",
    )
    img.save(out)
    return out


def _render_badge_png(text: str, font_size: int, out: Path) -> Path:
    """Small pill badge for episode label (e.g. 'Shloka 2 | Gita 2.48')."""
    font = _find_font(font_size)
    pad_x, pad_y = 32, 18
    dummy = Image.new("RGBA", (10, 10))
    d = ImageDraw.Draw(dummy)
    bbox = d.textbbox((0, 0), text, font=font, stroke_width=3)
    tw, th = int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])
    box_w, box_h = tw + pad_x * 2, th + pad_y * 2
    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # rounded pill background — orange→gold gradient feel
    draw.rounded_rectangle([(0, 0), (box_w, box_h)], radius=box_h // 2,
                            fill=(180, 30, 30, 230))
    draw.rounded_rectangle([(4, 4), (box_w - 4, box_h - 4)], radius=(box_h - 8) // 2,
                            outline=(255, 220, 120, 255), width=3)
    draw.text(((box_w - tw) // 2 - bbox[0], (box_h - th) // 2 - bbox[1]),
              text, fill=(255, 255, 255, 255),
              stroke_width=2, stroke_fill=(0, 0, 0, 255), font=font)
    img.save(out)
    return out


def _render_word_png(text: str, font_size: int, color: tuple, out: Path, stroke_w: int = 9) -> Path:
    """Render a single word with HUGE bold typography for word-by-word captions.
    color: (R, G, B) tuple for text fill — white/yellow/red for emphasis tiers.
    """
    font = _find_font(font_size)
    pad_x, pad_y = 28, 18
    dummy = Image.new("RGBA", (10, 10))
    d = ImageDraw.Draw(dummy)
    bbox = d.textbbox((0, 0), text, font=font, stroke_width=stroke_w)
    tw, th = int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])
    box_w = tw + pad_x * 2
    box_h = th + pad_y * 2

    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    text_xy = ((box_w - tw) // 2 - bbox[0], (box_h - th) // 2 - bbox[1])
    draw.text(
        text_xy, text,
        fill=color + (255,),
        stroke_width=stroke_w,
        stroke_fill=(0, 0, 0, 255),
        font=font,
    )
    img.save(out)
    return out


# Word emphasis tiers for word-by-word captions
_HIGH_EMPHASIS = {
    "रहस्य", "सच", "अमर", "श्राप", "वरदान", "जादू", "चमत्कार", "खुलासा",
    "मौत", "जीवित", "ज़िंदा", "मारा", "खुद", "असली", "वास्तविक", "देखो",
    "rahasya", "sach", "amar", "shrap", "vardaan", "khulasa", "asli",
}
_MED_EMPHASIS = {
    "कौन", "क्या", "कब", "कैसे", "क्यों", "कहाँ", "कोई",
    "kaun", "kya", "kab", "kaise", "kyun", "kahan",
}


def _word_color(word: str) -> tuple:
    """Return (R,G,B) color for word based on emphasis tier."""
    w = word.strip(",.!?।॥;:\"'()[]")
    if w in _HIGH_EMPHASIS:
        return (255, 60, 60)       # red
    if w in _MED_EMPHASIS:
        return (255, 220, 0)       # yellow
    return (255, 255, 255)         # white


def _render_caption_png(text: str, width: int, font_size: int, box_opacity: float, out: Path) -> Path:
    """YT-Shorts style caption: bold yellow text + thick black stroke. No box by default."""
    font = _find_font(font_size)
    pad_x, pad_y = 40, 30
    # wrap text — shorter lines (max ~18 chars) for big bold caption look
    chars_per_line = 18 if len(text) > 24 else max(len(text), 10)
    wrapped = textwrap.fill(text, width=chars_per_line, break_long_words=False)

    img_w = width - 100
    dummy = Image.new("RGBA", (10, 10))
    d = ImageDraw.Draw(dummy)
    stroke_w = 6
    bbox = d.multiline_textbbox((0, 0), wrapped, font=font, spacing=12,
                                 align="center", stroke_width=stroke_w)
    tw, th = int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])
    box_w = int(min(img_w, tw + pad_x * 2))
    box_h = int(th + pad_y * 2)

    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    if box_opacity > 0:
        bg_alpha = int(box_opacity * 255)
        draw.rounded_rectangle([(0, 0), (box_w, box_h)], radius=28,
                                fill=(0, 0, 0, bg_alpha))

    text_xy = ((box_w - tw) // 2 - bbox[0], (box_h - th) // 2 - bbox[1])
    # bold yellow with thick black stroke (Shorts/Reels style)
    draw.multiline_text(
        text_xy, wrapped,
        fill=(255, 220, 0, 255),
        stroke_width=stroke_w,
        stroke_fill=(0, 0, 0, 255),
        font=font, spacing=12, align="center",
    )
    img.save(out)
    return out


def assemble(
    script: dict,
    voice_path: Path,
    image_paths: list[Path],
    out_video: Path,
    skip_music: bool = False,
) -> Path:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found in PATH. Install with: brew install ffmpeg")

    cfg = load_config()
    W = cfg["video"]["width"]
    H = cfg["video"]["height"]
    FPS = cfg["video"]["fps"]
    BR = cfg["video"]["bitrate"]
    font_size = cfg["video"]["font_size"]
    box_opacity = cfg["video"]["subtitle_box_opacity"]

    duration = _audio_duration(voice_path)
    n = len(image_paths)
    per = duration / n
    per_frames = max(int(per * FPS), 30)

    work = out_video.parent / f"_work_{out_video.stem}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)

    # 1. Build per-image clips with smooth Ken Burns motion.
    # IMPORTANT: don't pre-scale the input. zoompan z=1.0 means the visible
    # window equals the OUTPUT size — if input == output size, z=1.0 shows
    # the full image. Pre-scaling by 2x and using z=2.0 was the old bug
    # (visible window covered only 25% of the image content).
    clips: list[Path] = []
    denom = max(per_frames - 1, 1)
    # iw/ih here = input width/height after scale below = W and H
    pan_range = "(iw-iw/zoom)"   # max x offset while keeping window inside frame
    motions = [
        # (start_z, end_z, x_expr_template, y_expr_template)
        ("1.00", "1.15", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),               # zoom in, center
        ("1.15", "1.00", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),               # zoom out, center
        ("1.10", "1.10", f"on*{pan_range}/{denom}", "ih/2-(ih/zoom/2)"),         # pan L→R
        ("1.10", "1.10", f"{pan_range}-on*{pan_range}/{denom}", "ih/2-(ih/zoom/2)"),  # pan R→L
    ]
    for i, img in enumerate(image_paths):
        clip = work / f"clip_{i:02d}.mp4"
        start_z, end_z, x_expr, y_expr = motions[i % len(motions)]
        z_expr = f"({start_z})+(({end_z})-({start_z}))*on/{denom}"
        zoompan = (
            # high-quality upscale from Pollinations' 576x1024 → 1080x1920
            f"scale={W}:{H}:flags=lanczos:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1,"
            # sharpen so AI image doesn't look soft after upscale
            f"unsharp=lx=5:ly=5:la=1.2:cx=5:cy=5:ca=0.4,"
            # BRIGHTER + more vibrant cinematic grading (lifts dark areas, pops colors)
            f"eq=contrast=1.10:saturation=1.32:brightness=0.07:gamma=0.86,"
            f"zoompan=z='{z_expr}':"
            f"x='{x_expr}':y='{y_expr}':"
            f"d={per_frames}:s={W}x{H}:fps={FPS},"
            f"format=yuv420p"
        )
        _run([
            "ffmpeg", "-y", "-loop", "1", "-i", str(img),
            "-t", f"{per:.3f}",
            "-vf", zoompan,
            "-r", str(FPS),
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            str(clip),
        ])
        clips.append(clip)

    # 2. Concat slides
    concat_list = work / "concat.txt"
    concat_list.write_text("\n".join(f"file '{c.name}'" for c in clips))
    slides = work / "slides.mp4"
    _run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy", str(slides),
    ])

    # 3. Compose overlays. For shloka_episode mode: top "Shloka N" badge
    # (persistent) + centered Sanskrit verse (also persistent), no scrolling
    # body captions. For other modes: per-line yellow captions as before.
    inputs = ["-i", str(slides)]
    chain_parts = []
    prev = "0:v"
    overlay_idx = 0

    if script.get("kind") == "shloka_episode" or script.get("episode_number"):
        ep_num = script.get("episode_number")
        ref = script.get("ref", "")
        badge_text = f"  Shloka  {ep_num}  |  Gita  {ref}  " if ep_num else "  Bhagavad Gita  "
        badge_png = work / f"badge.png"
        _render_badge_png(badge_text, 56, badge_png)
        inputs += ["-i", str(badge_png)]
        overlay_idx += 1
        chain_parts.append(
            f"[{prev}][{overlay_idx}:v]overlay=x=(W-w)/2:y=80[v_b]"
        )
        prev = "v_b"

        verse = script.get("verse") or ""
        if verse:
            verse_png = work / f"verse.png"
            _render_devanagari_png(verse, W - 120, 64, verse_png)
            inputs += ["-i", str(verse_png)]
            overlay_idx += 1
            # show verse only during opening — when narrator reads it.
            # appears at 3s, fades around 13s. After that image is clean.
            verse_start = 3.0
            verse_end = min(14.0, duration - 2.0)
            chain_parts.append(
                f"[{prev}][{overlay_idx}:v]overlay="
                f"x=(W-w)/2:y=H*0.40:"
                f"enable='between(t\\,{verse_start:.2f}\\,{verse_end:.2f})'[v_v]"
            )
            prev = "v_v"
    else:
        # NEW: animated word-by-word captions (CapCut/Reels viral style).
        # Driven by word boundaries captured during TTS → one PNG per word,
        # overlaid with timed enable filter. Pure overlay chain — works on
        # minimal ffmpeg builds (no libass/drawtext needed).
        words_json = voice_path.with_suffix(".words.json")
        used_words = False
        if words_json.exists():
            try:
                import json as _json
                boundaries = _json.loads(words_json.read_text(encoding="utf-8"))
                # Filter out empty / pure-punctuation
                boundaries = [
                    b for b in boundaries
                    if b.get("text", "").strip() and any(ch.isalnum() or ord(ch) > 127 for ch in b["text"])
                ]
            except Exception as e:
                print(f"[captions] failed to read word boundaries ({e})")
                boundaries = []

            if boundaries:
                print(f"[captions] rendering {len(boundaries)} word PNGs (animated word-by-word)")
                word_font_size = int(font_size * 1.7)  # bigger than line-by-line
                for i, b in enumerate(boundaries):
                    word = b["text"].strip()
                    if not word:
                        continue
                    color = _word_color(word)
                    png = work / f"word_{i:04d}.png"
                    _render_word_png(word, word_font_size, color, png)

                    # Time window: pad slightly on both sides for readability
                    word_start = max(0.0, b["start"] - 0.05)
                    word_end = b["end"] + 0.05
                    if i + 1 < len(boundaries):
                        word_end = min(word_end, boundaries[i + 1]["start"] - 0.005)
                    if word_end - word_start < 0.18:
                        word_end = word_start + 0.18

                    inputs += ["-i", str(png)]
                    overlay_idx += 1
                    out_lbl = f"v{overlay_idx}"
                    chain_parts.append(
                        f"[{prev}][{overlay_idx}:v]overlay="
                        f"x=(W-w)/2:y=H*0.62:"
                        f"enable='between(t\\,{word_start:.3f}\\,{word_end:.3f})'[{out_lbl}]"
                    )
                    prev = out_lbl
                used_words = True

        if not used_words:
            # Fallback: legacy line-by-line PNG overlay subtitles
            sub_lines = [
                script.get("hook_roman") or script["hook"],
                *(script.get("body_roman") or script["body"]),
                script.get("cta_roman") or script["cta"],
            ]
            n_sub = len(sub_lines)
            per_sub = duration / n_sub
            for i, line in enumerate(sub_lines):
                png = work / f"sub_{i:02d}.png"
                _render_caption_png(line.strip(), W, font_size, box_opacity, png)
                inputs += ["-i", str(png)]
                overlay_idx += 1
                start = i * per_sub
                end = (i + 1) * per_sub - 0.05
                out_lbl = f"v{overlay_idx}"
                chain_parts.append(
                    f"[{prev}][{overlay_idx}:v]overlay="
                    f"x=(W-w)/2:y=H*0.62:"
                    f"enable='between(t\\,{start:.3f}\\,{end:.3f})'[{out_lbl}]"
                )
                prev = out_lbl

    final_label = prev
    filter_complex = ";".join(chain_parts) if chain_parts else None

    slides_subbed = work / "slides_sub.mp4"
    if filter_complex:
        _run([
            "ffmpeg", "-y", *inputs,
            "-filter_complex", filter_complex,
            "-map", f"[{final_label}]",
            "-c:v", "libx264", "-preset", "veryfast",
            "-b:v", BR, "-pix_fmt", "yuv420p",
            str(slides_subbed),
        ])
    else:
        # no overlays — just copy slides
        shutil.copy(slides, slides_subbed)

    # 4. Mix audio with optional bg music (ducked). Re-encode video to
    # yuv420p tv-range + faststart so QuickTime / iOS / web players all
    # accept it (Pollinations JPEGs come in as yuvj420p full-range).
    common_v = [
        "-vf", "scale=in_range=full:out_range=tv,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-b:v", BR,
        "-pix_fmt", "yuv420p", "-color_range", "tv",
        "-movflags", "+faststart",
    ]
    bg = None if skip_music else pick_music(script.get("kind"))
    if bg:
        _run([
            "ffmpeg", "-y",
            "-i", str(slides_subbed),
            "-i", str(voice_path),
            "-stream_loop", "-1", "-i", str(bg),
            "-filter_complex",
            "[1:a]volume=1.2,highpass=f=120[voice];"
            "[2:a]volume=0.32,lowpass=f=8000[bg];"
            "[voice][bg]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[a]",
            "-map", "0:v", "-map", "[a]",
            *common_v,
            "-c:a", "aac", "-b:a", "192k",
            "-shortest", str(out_video),
        ])
    else:
        _run([
            "ffmpeg", "-y",
            "-i", str(slides_subbed),
            "-i", str(voice_path),
            "-map", "0:v", "-map", "1:a",
            *common_v,
            "-c:a", "aac", "-b:a", "192k",
            "-shortest", str(out_video),
        ])

    shutil.rmtree(work, ignore_errors=True)
    return out_video


if __name__ == "__main__":
    print("Use run.py to assemble end-to-end.")
