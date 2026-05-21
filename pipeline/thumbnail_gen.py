"""Auto-generate a YouTube Shorts thumbnail per video.

Steps:
1. Generate a dramatic close-up image via Pollinations (based on video's first
   visual prompt, tweaked for thumbnail framing).
2. Apply dark gradient overlays for text readability.
3. Add a punchy Hindi text overlay (LLM-generated hook + sub-hook).
4. Stamp channel brand at bottom.
5. Output 1080×1920 JPEG ready for upload.

Usage: called automatically by run.py when --auto-thumb or --notify-telegram
is passed.
"""
from __future__ import annotations

import json
import os
import re
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .utils import ROOT, load_config

# Try project-local font first (cross-platform), then macOS system fallback,
# then Linux Devanagari font for GitHub Actions/Ubuntu runners.
_FONT_CANDIDATES = [
    str(ROOT / "assets/fonts/Khand-Bold.ttf"),
    str(ROOT / "assets/fonts/MuktaVaani-Bold.ttf"),
    "/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc",
    "/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
]


def _font_path() -> str:
    for f in _FONT_CANDIDATES:
        if Path(f).exists():
            return f
    raise RuntimeError("No Devanagari font available (place one under assets/fonts/)")


FONT_PATH = _font_path()
MAX_WIDTH_RATIO = 0.92  # text wrap target


def _gen_thumb_text(script: dict, niche: str) -> dict:
    """Use Gemini to generate punchy thumbnail hook + sub-hook."""
    import google.generativeai as genai
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")
    genai.configure(api_key=api_key)

    title = script.get("title", "")
    hook = script.get("hook", "")

    prompt = f"""Generate a YouTube Shorts thumbnail text in Devanagari Hindi.

Topic title: {title}
Video hook: {hook}
Niche: {niche}

Output ONLY this JSON (no markdown fences):
{{
  "top": "main punch in Devanagari Hindi, 2-4 words MAX, dramatic+clickbait",
  "bottom": "curiosity teaser in Devanagari Hindi, 3-5 words MAX"
}}

Rules:
- Top text MUST be 2-4 words, max ~20 chars total (it must fit one line in big bold font).
- Bottom text MUST be 3-5 words, max ~30 chars.
- NO emojis, NO English words, pure Devanagari.
- DRAMATIC. Think: "रहस्य", "सच", "खुलासा", "देखो क्या हुआ".
- Avoid full sentences — punchy fragments only."""

    m = genai.GenerativeModel("gemini-flash-latest")
    r = m.generate_content(prompt, generation_config={"temperature": 0.9})
    text = r.text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    s, e = text.find("{"), text.rfind("}")
    return json.loads(text[s : e + 1])


def _gen_base_image(script: dict) -> Image.Image:
    """Generate a dramatic close-up thumbnail image via Pollinations."""
    visuals = script.get("visuals") or []
    base_prompt = visuals[0] if visuals else script.get("title", "")
    prompt = (
        f"{base_prompt}, dramatic close-up portrait framing, intense emotional expression, "
        f"deep chiaroscuro lighting, vertical 9:16 portrait composition, "
        f"ultra detailed, cinematic concept art, no text, no watermark, "
        f"single character centered"
    )
    url = (
        f"https://image.pollinations.ai/prompt/{requests.utils.quote(prompt)}"
        f"?width=1080&height=1920&nologo=true&model=flux"
    )
    r = requests.get(url, timeout=240)
    r.raise_for_status()
    return Image.open(BytesIO(r.content)).convert("RGB")


def _apply_gradients(img: Image.Image) -> Image.Image:
    W, H = img.size
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for y in range(0, int(H * 0.32)):
        alpha = int(190 * (1 - y / (H * 0.32)))
        d.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
    for y in range(int(H * 0.82), H):
        alpha = int(170 * ((y - H * 0.82) / (H * 0.18)))
        d.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def _fit_font(draw, text: str, max_width: int, start_size: int, min_size: int, stroke_w: int) -> ImageFont.FreeTypeFont:
    """Shrink font until text fits in max_width."""
    size = start_size
    while size >= min_size:
        f = ImageFont.truetype(FONT_PATH, size=size)
        bbox = draw.textbbox((0, 0), text, font=f, stroke_width=stroke_w)
        if (bbox[2] - bbox[0]) <= max_width:
            return f
        size -= 10
    return ImageFont.truetype(FONT_PATH, size=min_size)


def _draw_text_block(draw, text: str, W: int, y: int, fill, font, stroke_w: int) -> int:
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_w)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = (W - tw) // 2
    draw.text(
        (x, y), text,
        fill=fill,
        stroke_width=stroke_w,
        stroke_fill=(0, 0, 0),
        font=font,
    )
    return th


def make_thumbnail(script: dict, niche: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = load_config()

    print(f"[thumbnail] generating base image...")
    img = _gen_base_image(script)
    if img.size != (1080, 1920):
        img = img.resize((1080, 1920), Image.LANCZOS).filter(
            ImageFilter.UnsharpMask(radius=2, percent=130, threshold=3)
        )
    img = _apply_gradients(img)

    # Get hook texts
    try:
        texts = _gen_thumb_text(script, niche)
        top_text = texts.get("top", "").strip()
        sub_text = texts.get("bottom", "").strip()
    except Exception as e:
        print(f"[thumbnail] LLM hook failed ({e}), using fallback")
        hook = script.get("hook", "")
        words = hook.split()
        top_text = " ".join(words[:3])[:25]
        sub_text = " ".join(words[3:7])[:30]

    draw = ImageDraw.Draw(img)
    W, H = img.size
    max_w = int(W * MAX_WIDTH_RATIO)

    # Top text — big bold gold
    if top_text:
        font_big = _fit_font(draw, top_text, max_w, start_size=180, min_size=110, stroke_w=14)
        th = _draw_text_block(draw, top_text, W, y=160, fill=(255, 215, 0), font=font_big, stroke_w=14)
        sub_y = 160 + th + 60
    else:
        sub_y = 320

    # Sub text — smaller red accent
    if sub_text:
        font_sub = _fit_font(draw, sub_text, max_w, start_size=92, min_size=58, stroke_w=6)
        _draw_text_block(draw, sub_text, W, y=sub_y, fill=(255, 80, 80), font=font_sub, stroke_w=8)

    # Bottom brand
    brand = (
        cfg.get("branding", {})
        .get("channel_handle", f"@{niche}")
        .lstrip("@")
        .upper()
    )
    font_brand = ImageFont.truetype(FONT_PATH, size=60)
    _draw_text_block(draw, brand, W, y=H - 150, fill=(255, 215, 0), font=font_brand, stroke_w=4)

    img.save(str(out_path), "JPEG", quality=95)
    print(f"[thumbnail] saved → {out_path}")
    return out_path
