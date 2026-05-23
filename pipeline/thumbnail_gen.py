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
    str(ROOT / "assets/fonts/Anton-Regular.ttf"),
    str(ROOT / "assets/fonts/BebasNeue-Regular.ttf"),
    str(ROOT / "assets/fonts/Oswald-Bold.ttf"),
    "/System/Library/Fonts/Supplemental/Devanagari Sangam MN.ttc",
    "/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf",
]


def _font_path() -> str:
    """Pick the niche-configured font (cfg.video.font) if available, else
    fall back to first existing candidate. Called per-thumbnail so each
    niche gets its own font (Khand for Hindi, Anton for English ancient)."""
    try:
        cfg = load_config()
        configured = cfg.get("video", {}).get("font", "")
        if configured:
            path = configured if Path(configured).is_absolute() else str(ROOT / configured)
            if Path(path).exists():
                return path
    except Exception:
        pass
    for f in _FONT_CANDIDATES:
        if Path(f).exists():
            return f
    raise RuntimeError("No display font available (place one under assets/fonts/)")
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
Match the viral Kaliyug-style 3M-view formula: short question hook + curiosity sub.

Topic title: {title}
Video hook: {hook}
Niche: {niche}

Output ONLY this JSON (no markdown fences):
{{
  "top": "main punch in Devanagari Hindi, 2-3 words MAX, ends with ? if possible",
  "bottom": "curiosity teaser in Devanagari Hindi, 2-4 words MAX"
}}

VIRAL THUMBNAIL TEXT FORMULA (proven):
- Top text = QUESTION HOOK in 2-3 words like:
  * "राम सेतु गायब?" (3 words)
  * "ये सच है?" (3 words)
  * "क्या हुआ था?" (3 words)
  * "अमर है?" (2 words)
  * "कैसे मरा?" (2 words)
- Bottom text = curiosity confirmation in 2-4 words like:
  * "देखिए ये रहस्य"
  * "सच जान के चौंक जाओगे"
  * "वो हैरान कर देने वाला सच"

CRITICAL:
- TOTAL words across both lines: max 6-7
- NO emojis, NO English, pure Devanagari
- Top SHOULD be a question (?) for curiosity gap
- Each line MUST fit in 1 line at very big font (no wrapping)
- Each line max 18 characters including spaces"""

    m = genai.GenerativeModel("gemini-flash-latest")
    r = m.generate_content(prompt, generation_config={"temperature": 0.9})
    text = r.text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    s, e = text.find("{"), text.rfind("}")
    return json.loads(text[s : e + 1])


def _gen_thumb_image_prompt(script: dict, niche: str) -> str:
    """Use LLM to craft a DEDICATED thumbnail composition prompt that matches
    viral Indian mythology Shorts formula (e.g., Kaliyug Ke Divya Mantra's
    3M-view Ram Setu thumbnail):

    - TWO characters: hero (calm/discovering) + reactor (shocked, hands on
      cheeks, open mouth) = relational drama in one frame
    - Storytelling background (the mystery being revealed visually)
    - Dramatic stormy/glowing atmosphere with lightning or divine light
    - Bright lighting on faces, no crops
    """
    import google.generativeai as genai
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    genai.configure(api_key=api_key)
    title = script.get("title", "")
    hook = script.get("hook", "")
    visuals = script.get("visuals") or []
    first_visual = visuals[0] if visuals else ""

    instruction = f"""Create a single ENGLISH image prompt for a YouTube Shorts THUMBNAIL.

Topic: {title}
Hook: {hook}
Video opening scene: {first_visual}
Niche: {niche}

VIRAL THUMBNAIL COMPOSITION (proven 3M-view formula):
- TWO Indian mythological/historical characters in the frame:
  * LEFT or BACK: the calm "hero" character (e.g., Ram, Bhishma, sage) in
    discovering pose — back view OR side profile, looking at the mystery
  * RIGHT FOREGROUND: the "reaction" character (Hanuman, devotee, soldier)
    with SHOCKED EXPRESSION — hands on cheeks, open mouth, wide eyes,
    classic "OMG" face that grabs scroll attention
- BACKGROUND tells the story visually: the mystery being revealed
  (Ram Setu bridge with glowing stones, ancient submerged Dwarka, cosmic
  Vishvarupa form, lost temple at sea, etc.)
- DRAMATIC atmospheric lighting: stormy clouds + lightning bolts, OR
  divine golden rays bursting through, OR mysterious dark-blue/orange
  chiaroscuro
- Bright illumination on BOTH faces — fully visible, no crops, both eyes
  showing on the reaction character
- Color palette: deep stormy blue + lightning yellow + saffron orange
  characters (high contrast)
- Vertical 9:16 portrait composition (1080x1920)
- Both characters anatomically correct (two arms each, hands have 5 fingers)
- Top 20% of frame relatively empty (will be covered by overlay text)
- NO text in image, NO watermarks, NO modern objects

Output ONLY the prompt string (no markdown, no explanation, ~100-150 words)."""
    try:
        m = genai.GenerativeModel("gemini-flash-latest")
        r = m.generate_content(instruction, generation_config={"temperature": 0.7})
        return r.text.strip().strip("`'\"")
    except Exception:
        return None


def _gen_base_image(script: dict, niche: str = "bhakti") -> Image.Image:
    """Generate a dedicated thumbnail portrait — LLM crafts a prompt focused
    on close-up face composition. Gemini Nano Banana 2 primary, Pollinations
    fallback.
    """
    import base64

    # Get a thumbnail-specific portrait prompt from the LLM
    thumb_prompt = _gen_thumb_image_prompt(script, niche)
    if not thumb_prompt:
        # Fallback: construct minimal portrait prompt from visuals[0]
        visuals = script.get("visuals") or []
        base = visuals[0] if visuals else script.get("title", "")
        thumb_prompt = (
            f"Close-up portrait of the main character from this scene: {base}. "
            f"Face fills 60% of frame, eye-level framing, both eyes visible, "
            f"direct emotional eye contact, single subject."
        )

    prompt = (
        f"{thumb_prompt}\n\nIMPORTANT: Close-up portrait composition with face "
        f"clearly visible. Anatomically correct (two eyes, one head, five fingers "
        f"per hand). Bright cinematic lighting on the face. Single dominant subject "
        f"centered. Atmospheric background, NOT crowded. Vertical 9:16 portrait "
        f"(1080x1920). Traditional Indian devotional art masterpiece. "
        f"NO text, NO watermark, NO modern objects, NO extra limbs, NO distorted anatomy."
    )

    # Try Gemini Nano Banana 2 first
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        try:
            r = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-3.1-flash-image-preview:generateContent?key={api_key}",
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
                },
                timeout=180,
            )
            if r.status_code == 200:
                for part in r.json()["candidates"][0]["content"]["parts"]:
                    if "inlineData" in part:
                        img_bytes = base64.b64decode(part["inlineData"]["data"])
                        if len(img_bytes) > 5000:
                            print("[thumbnail] base via Gemini Nano Banana 2")
                            return Image.open(BytesIO(img_bytes)).convert("RGB")
            else:
                print(f"[thumbnail] Gemini failed ({r.status_code}), falling back to Pollinations")
        except Exception as e:
            print(f"[thumbnail] Gemini error ({e}), falling back to Pollinations")

    # Fallback: Pollinations flux-realism
    url = (
        f"https://image.pollinations.ai/prompt/{requests.utils.quote(prompt)}"
        f"?width=1080&height=1920&nologo=true&model=flux-realism"
    )
    print("[thumbnail] base via Pollinations (fallback)")
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
        f = ImageFont.truetype(_font_path(), size=size)
        bbox = draw.textbbox((0, 0), text, font=f, stroke_width=stroke_w)
        if (bbox[2] - bbox[0]) <= max_width:
            return f
        size -= 10
    return ImageFont.truetype(_font_path(), size=min_size)


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
    img = _gen_base_image(script, niche)
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

    # Top text — HUGE bold gold (viral Kaliyug-style 200+ px font)
    # Positioned in TOP-SAFE-ZONE (y=120 from top)
    if top_text:
        font_big = _fit_font(draw, top_text, max_w, start_size=220, min_size=130, stroke_w=16)
        th = _draw_text_block(draw, top_text, W, y=120, fill=(255, 215, 0), font=font_big, stroke_w=16)
        sub_y = 120 + th + 40
    else:
        sub_y = 320

    # Sub text — slightly smaller white (high contrast vs gold top)
    if sub_text:
        font_sub = _fit_font(draw, sub_text, max_w, start_size=110, min_size=70, stroke_w=8)
        _draw_text_block(draw, sub_text, W, y=sub_y, fill=(255, 255, 255), font=font_sub, stroke_w=10)

    # Bottom brand
    brand = (
        cfg.get("branding", {})
        .get("channel_handle", f"@{niche}")
        .lstrip("@")
        .upper()
    )
    font_brand = ImageFont.truetype(_font_path(), size=60)
    _draw_text_block(draw, brand, W, y=H - 150, fill=(255, 215, 0), font=font_brand, stroke_w=4)

    img.save(str(out_path), "JPEG", quality=95)
    print(f"[thumbnail] saved → {out_path}")
    return out_path
