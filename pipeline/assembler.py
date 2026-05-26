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

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .music import (
    compose_audio_track,
    pick_drone,
    pick_music,
    pick_sting,
    pick_sting_timestamps,
)
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


def _compute_image_durations(voice_path: Path, n_images: int, total_duration: float) -> list[float] | None:
    """Map N images proportionally across the M silence-aligned sentences so
    each image appears WHILE its corresponding script sentence is being
    narrated, instead of the equal-split default.

    Reads {voice_path}.sentences.json (written by tts._silence_align). If the
    sidecar isn't present or has zero/one segments, returns None and caller
    falls back to equal split.

    Mapping rule: image i covers sentences [floor(i*M/N), floor((i+1)*M/N)).
    Image duration = sum of those sentences' durations.
    """
    import json as _json
    sents_path = voice_path.with_suffix(".sentences.json")
    if not sents_path.exists():
        return None
    try:
        sentences = _json.loads(sents_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not sentences or n_images <= 0:
        return None
    M = len(sentences)
    if M < 2:
        return None

    durations: list[float] = []
    for i in range(n_images):
        s_idx = int(i * M / n_images)
        e_idx = int((i + 1) * M / n_images)
        e_idx = max(s_idx + 1, e_idx)
        e_idx = min(e_idx, M)
        # Cover from start of first sentence in window to end of last
        start_t = sentences[s_idx]["start"]
        end_t = sentences[e_idx - 1]["end"]
        durations.append(max(0.5, end_t - start_t))

    # Rescale to total_duration (handles head/tail silence not in sentence span)
    sum_d = sum(durations)
    if sum_d > 0:
        scale = total_duration / sum_d
        durations = [d * scale for d in durations]
    return durations


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
    # Try the niche's configured font first (cfg.video.font) so each niche
    # can pick its own display font — English niches use Anton/Bebas,
    # Hindi niches use Khand-Bold.
    try:
        cfg = load_config()
        configured = cfg.get("video", {}).get("font", "")
        if configured:
            path = configured if Path(configured).is_absolute() else str(ROOT / configured)
            if Path(path).exists():
                return ImageFont.truetype(path, size=size)
    except Exception:
        pass
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


# Animated word-effect dictionaries — viral mythology channel style
# (inspired by @priyanshshukla_007). Words matching GLOW_WORDS get a
# golden halo, words matching SHOCK_WORDS render in red with thicker
# stroke. Everything else uses the default yellow/white styling and
# the universal Y-axis bounce-in animation added at overlay time.
GLOW_WORDS = {
    "रहस्य", "चमत्कार", "सच", "जब", "क्यों", "कैसे", "अद्भुत",
    "खौफनाक", "सबसे", "असली", "गुप्त", "मायावी", "दिव्य",
    "पहली बार", "अकेला",
}
SHOCK_WORDS = {
    "मारा", "मरा", "खून", "चीख", "डर", "श्राप", "क्रोध",
    "क्रूर", "मौत", "विनाश", "गिर", "टूट", "चीर", "वध", "हत्या",
}


def _render_word_png(
    text: str,
    font_size: int,
    color: tuple,
    out: Path,
    stroke_w: int = 9,
    glow: bool = False,
) -> Path:
    """Render a single word with HUGE bold typography for word-by-word captions.

    color: (R, G, B) tuple for text fill — white/yellow/red for emphasis tiers.
    glow: when True, paint a saffron/gold halo behind the text (KEY HINDI WORDS).
    """
    font = _find_font(font_size)
    pad_x, pad_y = 28, 18
    # Glow needs extra room around the glyphs so the blurred halo isn't clipped.
    glow_pad = 36 if glow else 0
    dummy = Image.new("RGBA", (10, 10))
    d = ImageDraw.Draw(dummy)
    bbox = d.textbbox((0, 0), text, font=font, stroke_width=stroke_w)
    tw, th = int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])
    box_w = tw + pad_x * 2 + glow_pad * 2
    box_h = th + pad_y * 2 + glow_pad * 2

    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    text_xy = ((box_w - tw) // 2 - bbox[0], (box_h - th) // 2 - bbox[1])

    if glow:
        # Two-pass golden halo: a wide soft blur for the outer aura, then a
        # tighter, denser pass for body warmth. Stack them under the main glyphs.
        for blur_radius, alpha in ((22, 200), (10, 230)):
            halo = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
            halo_draw = ImageDraw.Draw(halo)
            halo_draw.text(
                text_xy, text,
                fill=(255, 190, 60, alpha),
                stroke_width=stroke_w + 2,
                stroke_fill=(255, 170, 40, alpha),
                font=font,
            )
            halo = halo.filter(ImageFilter.GaussianBlur(radius=blur_radius))
            img.alpha_composite(halo)

    draw = ImageDraw.Draw(img)
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


def _clean_word(word: str) -> str:
    """Strip punctuation for set-membership lookups."""
    return word.strip(",.!?।॥;:\"'()[]")


def _word_style(word: str) -> tuple[tuple, int, bool]:
    """Return (color, stroke_width, glow) tuple for a word.

    Priority order:
      1. SHOCK_WORDS → bright red + thicker stroke for visceral hits
      2. GLOW_WORDS  → yellow text + golden halo for key story beats
      3. _HIGH_EMPHASIS → legacy red emphasis
      4. _MED_EMPHASIS  → legacy yellow
      5. default      → white
    """
    w = _clean_word(word)
    if w in SHOCK_WORDS:
        return ((255, 60, 60), 12, False)
    if w in GLOW_WORDS:
        return ((255, 230, 120), 9, True)
    if w in _HIGH_EMPHASIS:
        return ((255, 60, 60), 9, False)
    if w in _MED_EMPHASIS:
        return ((255, 220, 0), 9, False)
    return ((255, 255, 255), 9, False)


def _word_color(word: str) -> tuple:
    """Backwards-compat: return only the RGB color tuple for a word."""
    color, _stroke, _glow = _word_style(word)
    return color


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


def _cinematic_motion_filter(scene_idx: int, total_scenes: int, duration_frames: int, W: int, H: int) -> str:
    """Return a ffmpeg zoompan expression set for one of 6 cinematic motion presets.

    Mimics viral mythology channel motion variety (@priyanshshukla_007) — each
    scene gets a distinct camera move instead of repeating the same zoom.

    Selection logic:
      - Scene 0 (opening hook):  PUSH_IN     (dramatic entrance)
      - Scene 1:                 PAN_RIGHT
      - Scene 2:                 PULL_OUT
      - Scene 3:                 PAN_LEFT
      - Scene 4:                 TILT_UP
      - Scene 5+:                cycle PUSH_IN, PAN_RIGHT, PULL_OUT, PAN_LEFT, TILT_UP, DRIFT_DIAGONAL
      - Last scene (climax):     PUSH_IN

    Easing: power-curve (pow(on/D, 0.85)) instead of linear for natural feel.
    """
    D = max(duration_frames - 1, 1)
    # Power-curve easing — softer start, smoother arrival (vs linear on/D).
    # Comma inside pow() must be escaped because zoompan splits sub-options on ':'
    # and ffmpeg parses commas at the filter level when not quoted; we double-escape
    # so the expression survives both Python string and ffmpeg arg parsing.
    t = f"pow(on/{D}\\,0.85)"

    PUSH_IN = 0
    PAN_RIGHT = 1
    PULL_OUT = 2
    PAN_LEFT = 3
    TILT_UP = 4
    DRIFT_DIAGONAL = 5

    # Per-scene motion selection
    if scene_idx == 0:
        preset = PUSH_IN
    elif total_scenes > 1 and scene_idx == total_scenes - 1:
        preset = PUSH_IN
    elif scene_idx == 1:
        preset = PAN_RIGHT
    elif scene_idx == 2:
        preset = PULL_OUT
    elif scene_idx == 3:
        preset = PAN_LEFT
    elif scene_idx == 4:
        preset = TILT_UP
    else:
        preset = scene_idx % 6

    if preset == PUSH_IN:
        z = f"1.0+0.18*{t}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif preset == PULL_OUT:
        z = f"1.18-0.18*{t}"
        x = "iw/2-(iw/zoom/2)"
        y = "ih/2-(ih/zoom/2)"
    elif preset == PAN_LEFT:
        z = "1.10"
        x = f"(iw-iw/zoom)*{t}"
        y = "ih/2-(ih/zoom/2)"
    elif preset == PAN_RIGHT:
        z = "1.10"
        x = f"(iw-iw/zoom)*(1-{t})"
        y = "ih/2-(ih/zoom/2)"
    elif preset == TILT_UP:
        z = f"1.08+0.06*{t}"
        x = "iw/2-(iw/zoom/2)"
        y = f"(ih-ih/zoom)*(1-{t})"
    else:  # DRIFT_DIAGONAL
        z = "1.06"
        x = f"(iw-iw/zoom)*{t}*0.5"
        y = f"(ih-ih/zoom)*{t}*0.5"

    preset_name = ["PUSH_IN", "PAN_RIGHT", "PULL_OUT", "PAN_LEFT", "TILT_UP", "DRIFT_DIAGONAL"][preset]
    print(f"[motion] scene {scene_idx + 1}/{total_scenes} → {preset_name}")

    return (
        f"zoompan=z='{z}':x='{x}':y='{y}':"
        f"d={duration_frames}:s={W}x{H}:fps=__FPS__"
    )


def assemble(
    script: dict,
    voice_path: Path,
    image_paths: list[Path],
    out_video: Path,
    skip_music: bool = False,
    long_form: bool = False,
) -> Path:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg not found in PATH. Install with: brew install ffmpeg")

    cfg = load_config()
    if long_form:
        # Long-form documentary = 1920x1080 horizontal (YouTube standard)
        # Larger font for desktop/TV viewing
        W, H = 1920, 1080
        FPS = cfg["video"]["fps"]
        print(f"[assembler] LONG-FORM mode → 1920x1080 horizontal documentary")
    else:
        W = cfg["video"]["width"]
        H = cfg["video"]["height"]
        FPS = cfg["video"]["fps"]
    BR = cfg["video"]["bitrate"]
    font_size = cfg["video"]["font_size"]
    box_opacity = cfg["video"]["subtitle_box_opacity"]

    duration = _audio_duration(voice_path)
    n = len(image_paths)

    # Sync images to script sentences (silence-aligned). Each image's display
    # window covers a proportional range of sentences, so the visual on screen
    # actually matches the line being narrated. Falls back to equal split if
    # the sentences.json sidecar isn't available (e.g., for ElevenLabs).
    image_durations = _compute_image_durations(voice_path, n, duration)
    if image_durations is None:
        per_uniform = duration / n
        image_durations = [per_uniform] * n
        print(f"[assembler] image timing: equal split ({per_uniform:.2f}s each)")
    else:
        print(f"[assembler] image timing: sentence-synced "
              f"(durations {[round(d, 2) for d in image_durations]})")

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
    n_scenes = len(image_paths)
    for i, img in enumerate(image_paths):
        clip = work / f"clip_{i:02d}.mp4"
        per = max(0.5, image_durations[i])  # min 0.5s per image
        per_frames = max(int(per * FPS), 15)
        # Cinematic motion variety — 6 distinct presets per video instead of static zoom.
        motion = _cinematic_motion_filter(i, n_scenes, per_frames, W, H).replace("__FPS__", str(FPS))
        zoompan = (
            # high-quality upscale from Pollinations' 576x1024 → 1080x1920
            f"scale={W}:{H}:flags=lanczos:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},setsar=1,"
            # sharpen so AI image doesn't look soft after upscale
            f"unsharp=lx=5:ly=5:la=1.2:cx=5:cy=5:ca=0.4,"
            # BRIGHTER + more vibrant cinematic grading (lifts dark areas, pops colors)
            f"eq=contrast=1.10:saturation=1.32:brightness=0.07:gamma=0.86,"
            f"{motion},"
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

            # Long-form safety: ffmpeg filter_complex chokes above ~600 simultaneous
            # PNG inputs (OS fd limit + filtergraph cap). For long-form (1000+ words)
            # we group consecutive words into PHRASES of ~4 words (or until punctuation),
            # render each as a yellow-bold caption PNG, and time it precisely using the
            # first/last word boundaries. This keeps overlays under ~400 (ffmpeg-safe)
            # AND keeps captions synced to actual speech (unlike even-split fallback).
            MAX_WORDS_FOR_PER_WORD = 600
            PHRASE_WORDS_TARGET = 4   # words per caption chunk
            PHRASE_WORDS_MAX = 6      # hard cap before forced break
            PUNCT_BREAK = set(".!?,;:।")

            if boundaries and len(boundaries) > MAX_WORDS_FOR_PER_WORD:
                print(f"[captions] {len(boundaries)} words > {MAX_WORDS_FOR_PER_WORD} — grouping into phrases (long-form mode)")
                phrases = []
                buf, buf_start = [], None
                for b in boundaries:
                    if buf_start is None:
                        buf_start = b["start"]
                    buf.append(b)
                    last_char = b["text"].strip()[-1:] if b["text"].strip() else ""
                    if len(buf) >= PHRASE_WORDS_MAX or (len(buf) >= PHRASE_WORDS_TARGET and last_char in PUNCT_BREAK):
                        phrases.append({
                            "text": " ".join(w["text"].strip() for w in buf),
                            "start": buf_start,
                            "end": buf[-1]["end"],
                        })
                        buf, buf_start = [], None
                if buf:
                    phrases.append({
                        "text": " ".join(w["text"].strip() for w in buf),
                        "start": buf_start,
                        "end": buf[-1]["end"],
                    })
                print(f"[captions] grouped {len(boundaries)} words → {len(phrases)} phrases (~{PHRASE_WORDS_TARGET}-word chunks, audio-synced)")
                for i, p in enumerate(phrases):
                    png = work / f"phrase_{i:04d}.png"
                    _render_caption_png(p["text"], W, int(font_size * 1.25), box_opacity, png)
                    p_start = max(0.0, p["start"] - 0.05)
                    p_end = p["end"] + 0.05
                    if i + 1 < len(phrases):
                        p_end = min(p_end, phrases[i + 1]["start"] - 0.005)
                    if p_end - p_start < 0.4:
                        p_end = p_start + 0.4
                    inputs += ["-i", str(png)]
                    overlay_idx += 1
                    out_lbl = f"v{overlay_idx}"
                    chain_parts.append(
                        f"[{prev}][{overlay_idx}:v]overlay="
                        f"x=(W-w)/2:y=H*0.65:"
                        f"enable='between(t\\,{p_start:.3f}\\,{p_end:.3f})'[{out_lbl}]"
                    )
                    prev = out_lbl
                used_words = True
                boundaries = []  # skip the word-by-word branch below

            if boundaries:
                print(f"[captions] rendering {len(boundaries)} word PNGs (animated word-by-word)")
                word_font_size = int(font_size * 1.7)  # bigger than line-by-line
                # Bounce-in animation parameters (drop-in from above over ~150ms).
                # Y-offset peaks at BOUNCE_PX above resting position at t=word_start,
                # eases to 0 at t=word_start+BOUNCE_DUR. Resting position = H*0.62.
                BOUNCE_DUR = 0.15
                BOUNCE_PX = 40
                for i, b in enumerate(boundaries):
                    word = b["text"].strip()
                    if not word:
                        continue
                    color, stroke_w, glow = _word_style(word)
                    png = work / f"word_{i:04d}.png"
                    _render_word_png(word, word_font_size, color, png,
                                     stroke_w=stroke_w, glow=glow)

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
                    # FIXED Y position — bounce-in animation reverted because user
                    # reported caption desync. Static position is proven reliable.
                    # Re-enable bounce only after we have a way to verify it works.
                    ws = f"{word_start:.3f}"
                    we = f"{word_end:.3f}"
                    chain_parts.append(
                        f"[{prev}][{overlay_idx}:v]overlay="
                        f"x=(W-w)/2:y=H*0.62-h/2:"
                        f"enable='between(t\\,{ws}\\,{we})'[{out_lbl}]"
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
    # 4. THREE-LAYER CINEMATIC MIX (voice + drone + sting hits).
    # Pre-bake the audio in pipeline/music.compose_audio_track() so the final
    # mux is a simple stream-copy from slides_subbed + the mixed track.
    # Falls back to the legacy single-track duck mix (and finally to pure
    # voice) when drone/sting libraries are unavailable.
    drone = None if skip_music else pick_drone(script.get("kind"))
    sting_ts = [] if skip_music else pick_sting_timestamps(duration)
    have_stings = bool(sting_ts) and pick_sting(0) is not None

    composed_audio: Path | None = None
    if not skip_music and (drone or have_stings):
        try:
            composed_audio = compose_audio_track(
                voice_path=voice_path,
                video_duration=duration,
                drone_path=drone,
                sting_timestamps=sting_ts if have_stings else [],
                out_path=work / "mix.m4a",
            )
            print(
                f"[audio] 3-layer mix → drone={'yes' if drone else 'no'} "
                f"stings={len(sting_ts) if have_stings else 0}"
            )
        except Exception as e:
            print(f"[audio] compose_audio_track failed ({e}); falling back to legacy mix")
            composed_audio = None

    if composed_audio is not None:
        _run([
            "ffmpeg", "-y",
            "-i", str(slides_subbed),
            "-i", str(composed_audio),
            "-map", "0:v", "-map", "1:a",
            *common_v,
            "-c:a", "aac", "-b:a", "192k",
            "-shortest", str(out_video),
        ])
    else:
        # Legacy fallback path — single ducked bg, or pure voice if none.
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
