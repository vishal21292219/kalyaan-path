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

    # Niche-aware language: English channels need English thumbnail text,
    # else font (e.g. Anton in TimeDecoders) renders Devanagari as ####.
    cfg = load_config()
    lang = cfg.get("llm", {}).get("language", "hindi").lower()
    is_english = lang == "english" or niche == "ancient"

    if is_english:
        prompt = f"""Generate a YouTube Shorts thumbnail text in ENGLISH (NOT Hindi/Devanagari).
Match viral documentary-style thumbnail formula: short shock hook + curiosity sub.

Topic title: {title}
Video hook: {hook}
Niche: {niche}

Output ONLY this JSON (no markdown fences):
{{
  "top": "main punch in ENGLISH, 2-3 words MAX, all caps, ends with ? or ! if possible",
  "bottom": "curiosity teaser in ENGLISH, 2-4 words MAX"
}}

VIRAL ENGLISH THUMBNAIL FORMULA (proven on Praveen Mohan / Bright Insight):
- Top text = SHOCK HOOK in 2-3 words like:
  * "ATLANTIS FOUND?"
  * "OLDER THAN HISTORY"
  * "BURIED FOR 5000 YEARS"
  * "SCIENTISTS BAFFLED"
  * "THE LOST CITY"
- Bottom text = curiosity teaser in 2-4 words like:
  * "What they found inside"
  * "Decoded after centuries"
  * "The hidden truth"

CRITICAL:
- ENGLISH ONLY — absolutely NO Devanagari/Hindi characters
- TOTAL words across both lines: max 6-7
- NO emojis
- ALL CAPS for top, Title Case for bottom
- Each line MUST fit at very large font (max 18 chars per line)"""
    else:
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


def _gen_thumb_image_prompt(script: dict, niche: str, long_form: bool = False) -> str:
    """Use LLM to craft a DEDICATED thumbnail composition prompt.

    Two modes:
    - Shorts (vertical 9:16): hero + shocked-reactor face composition (viral
      Kaliyug Ke Divya Mantra 3M-view formula)
    - Long-form (horizontal 16:9): split-screen drama composition with
      character on one side + storytelling background on other side, leaves
      RIGHT-THIRD empty for the BIG bold text overlay (Praveen Mohan /
      Project Nightfall documentary thumbnail formula)
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
    # English/global niches (TimeDecoders ancient) must NOT use Indian-deity art.
    _lang = (load_config().get("llm", {}).get("language", "hindi") or "hindi").lower()
    is_english = _lang == "english" or niche == "ancient"

    if long_form:
        # 16:9 horizontal documentary thumbnail (1280x720 target)
        instruction = f"""Create a single ENGLISH image prompt for a YouTube LONG-FORM (16:9 horizontal) documentary THUMBNAIL.

Topic: {title}
Hook: {hook}
Video opening scene: {first_visual}
Niche: {niche}

VIRAL LONG-FORM DOCUMENTARY THUMBNAIL COMPOSITION (Praveen Mohan / Project Nightfall / Kaliyug Ke Divya Mantra formula):

- HORIZONTAL 16:9 wide cinematic composition (1280x720 aspect)
- LEFT-THIRD: ONE iconic character in dramatic pose
  * Mythology: hero deity (Ram drawing bow, Krishna with chakra, Hanuman
    leaping, Devi with weapons) OR shocked-reaction face (devotee, sage)
  * Ancient mysteries: archaeologist with torch in ruins, explorer pointing
    at discovery, scholar in shocked discovery pose
  * Character takes up roughly LEFT 35% of frame, eyes visible, dramatic
    lighting on face
- RIGHT TWO-THIRDS: STORYTELLING BACKGROUND
  * The mystery/topic visualized: ancient ruins, glowing artifacts, cosmic
    scenes, submerged cities, lit caves, divine landscapes
  * RIGHT-THIRD specifically should have darker/simpler area where bold
    overlay text will be placed (no busy detail in right-third)
- DRAMATIC LIGHTING: cinematic chiaroscuro, lightning bolts, divine golden
  rays, mysterious dark-blue/saffron-orange contrast
- Color palette: deep stormy blue/black + lightning yellow accents + warm
  golden character lighting (max contrast for 16:9 mobile + TV display)
- Character anatomically correct (proper limbs, eyes, fingers)
- NO text in image, NO watermarks, NO modern objects, NO logos
- Camera lens: cinematic 50mm-style, shallow depth-of-field background

Output ONLY the prompt string (no markdown, no explanation, ~120-180 words)."""
    elif is_english or niche == "ancient":
        # Vertical 9:16 Shorts thumbnail for TimeDecoders (English, GLOBAL
        # ancient-mysteries). MUST NOT use Indian deities — the reactor + scene
        # should match the topic's real geography/culture (Egyptian, Mesoamerican,
        # European, underwater, etc.), Praveen-Mohan / Bright-Insight style.
        instruction = f"""Create a single ENGLISH image prompt for a YouTube Shorts THUMBNAIL
for a GLOBAL ancient-mysteries / lost-history channel (NOT Indian devotional).

Topic: {title}
Hook: {hook}
Video opening scene: {first_visual}
Niche: {niche}

VIRAL ANCIENT-MYSTERY THUMBNAIL COMPOSITION (Praveen Mohan / Bright Insight formula):
- RIGHT FOREGROUND: ONE human "reaction" face with a SHOCKED/awed expression —
  wide eyes, open mouth, hand near face. Pick the face to MATCH the topic's
  region: a Western explorer/archaeologist, an Egyptian, a Mesoamerican, a
  Greek/Roman, a European scholar — whatever fits {title}. NEVER an Indian
  deity, tilak, turban, or Hindu iconography unless the topic is explicitly Indian.
- LEFT / BACKGROUND: the MONUMENT or mystery itself, hyper-real and dramatic
  (pyramids, megaliths, ruined citadel, submerged city, stone heads, glowing
  artifact, ancient map) — matched to the actual topic, photoreal not painterly.
- DRAMATIC cinematic lighting: god-rays through storm clouds, teal-and-orange
  color grade, volumetric fog, lightning — high contrast for mobile.
- Face brightly lit, both eyes visible, photorealistic skin.
- Vertical 9:16 portrait composition (1080x1920).
- Anatomically correct (two eyes, five fingers).
- Top 20% of frame relatively empty (covered by overlay text later).
- NO text in image, NO watermark, NO modern objects, NO cartoon look.

Output ONLY the prompt string (no markdown, no explanation, ~100-150 words)."""
    else:
        # Vertical 9:16 Shorts thumbnail (1080x1920) — Indian mythology/bhakti formula
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


def _pick_character_master(script: dict, img_dir: Path | None) -> Path | None:
    """If the consistency pass produced character master portraits in img_dir,
    pick the one matching this video's main character (named in the title, else
    the first available) so the thumbnail face matches the video exactly."""
    if not img_dir:
        return None
    masters = sorted(Path(img_dir).glob("master_*.jpg"))
    if not masters:
        return None
    bible = script.get("character_bible") or []
    title_low = (script.get("title", "") + " " + " ".join(script.get("visuals") or [])[:1]).lower()
    from .utils import slugify
    for ch in bible:
        name = (ch.get("name") or "")
        if name and name.lower() in title_low:
            cand = Path(img_dir) / f"master_{slugify(name)}.jpg"
            if cand.exists():
                return cand
    return masters[0]


def _gen_base_image(script: dict, niche: str = "bhakti", long_form: bool = False,
                    img_dir: Path | None = None) -> Image.Image:
    """Generate a dedicated thumbnail base image. For Shorts: vertical 9:16
    close-up. For long-form: horizontal 16:9 cinematic split-screen drama.

    If a character master portrait exists in img_dir (from the consistency
    pass), the base is reference-conditioned off it so the thumbnail's face
    matches the video. Provider chain: fal FLUX → HF schnell → Gemini.
    """
    import base64

    # Get a thumbnail-specific composition prompt from the LLM (mode-aware)
    thumb_prompt = _gen_thumb_image_prompt(script, niche, long_form=long_form)
    if not thumb_prompt:
        # Fallback: construct minimal portrait prompt from visuals[0]
        visuals = script.get("visuals") or []
        base = visuals[0] if visuals else script.get("title", "")
        thumb_prompt = (
            f"Close-up portrait of the main character from this scene: {base}. "
            f"Face fills 60% of frame, eye-level framing, both eyes visible, "
            f"direct emotional eye contact, single subject."
        )

    if long_form:
        prompt = (
            f"{thumb_prompt}\n\nIMPORTANT: HORIZONTAL 16:9 cinematic widescreen composition "
            f"(1280x720 aspect ratio). Left-third dominant character, right two-thirds storytelling "
            f"background with right-third area kept simple/dark for text overlay. "
            f"Anatomically correct figures. Dramatic cinematic chiaroscuro lighting. "
            f"NO text, NO watermark, NO modern objects, NO extra limbs, NO distorted anatomy."
        )
    else:
        prompt = (
            f"{thumb_prompt}\n\nIMPORTANT: Close-up portrait composition with face "
            f"clearly visible. Anatomically correct (two eyes, one head, five fingers "
            f"per hand). Bright cinematic lighting on the face. Single dominant subject "
            f"centered. Atmospheric background, NOT crowded. Vertical 9:16 portrait "
            f"(1080x1920). Traditional Indian devotional art masterpiece. "
            f"NO text, NO watermark, NO modern objects, NO extra limbs, NO distorted anatomy."
        )

    # Provider chain (matches image_gen.py): fal.ai FLUX 1.1-pro → HF FLUX schnell → Gemini.
    # Each thumbnail = 1 image so we just write to a temp path and read back.
    from .image_gen import _generate_fal_flux, _generate_hf_flux, _generate_gemini, GeminiUnavailable
    import tempfile

    _icfg = load_config().get("images", {})
    use_fal = str(_icfg.get("provider", "fal")).lower() == "fal"
    from .image_gen import FAL_FLUX_PRO
    _fal_model = _icfg.get("model", "") if str(_icfg.get("model", "")).startswith("fal-ai/") else FAL_FLUX_PRO
    target_w, target_h = (1280, 720) if long_form else (1080, 1920)
    tmp_path = Path(tempfile.mkstemp(suffix=".jpg")[1])

    # 0. Reference-conditioned off the character master (consistency pass) so the
    #    thumbnail face matches the video. Vertical Shorts only (nano edit 9:16).
    if use_fal and not long_form:
        master = _pick_character_master(script, img_dir)
        if master:
            try:
                from .char_consistent import _fal_upload, generate_scene_with_reference
                murl = _fal_upload(master)
                if murl and generate_scene_with_reference(
                    murl, thumb_prompt, tmp_path,
                    char_name="the main character",
                    art_style="match the reference's art style exactly",
                    target_w=target_w, target_h=target_h,
                ):
                    print(f"[thumbnail] base reference-conditioned off {master.name}")
                    return Image.open(tmp_path).convert("RGB")
            except Exception as e:
                print(f"[thumbnail] master-conditioning skipped: {type(e).__name__}: {e}")

    # 1. fal (paid) — only when provider == "fal", using the configured fal model
    if use_fal and _generate_fal_flux(prompt, tmp_path, model=_fal_model, target_w=target_w, target_h=target_h):
        print(f"[thumbnail] base via fal ({_fal_model})")
        return Image.open(tmp_path).convert("RGB")

    # 2. HF FLUX schnell (free fallback)
    if _generate_hf_flux(prompt, tmp_path):
        print("[thumbnail] base via HF FLUX schnell (fal failed)")
        return Image.open(tmp_path).convert("RGB")

    # 3. Gemini (last resort — usually banned/quota'd)
    try:
        if _generate_gemini(prompt, tmp_path, "gemini-3.1-flash-image-preview"):
            print("[thumbnail] base via Gemini (last resort)")
            return Image.open(tmp_path).convert("RGB")
    except GeminiUnavailable as e:
        pass

    raise GeminiUnavailable("Thumbnail base image: fal + HF + Gemini all failed")


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


# Words that POP yellow on thumbnails (rest white) — like top viral channels.
_THUMB_KEY = {
    "real", "hidden", "secret", "truth", "mind", "god", "gods", "death", "power",
    "why", "shocking", "forbidden", "cursed", "proof", "never", "psychology",
    "dark", "soul", "meaning", "lost", "ancient", "mystery", "sealed",
    "रहस्य", "सच", "असली", "मौत", "श्राप", "अमर", "चमत्कार", "खौफनाक", "गुप्त",
    "कैसे", "क्यों", "सबसे", "रहस्यमयी", "खतरनाक",
}


def _is_key_word(w: str) -> bool:
    wl = w.strip(",.!?।॥-:;'\"").lower()
    return wl in _THUMB_KEY or any(c.isdigit() for c in w)


def _draw_words_colored(draw, text: str, W: int, y: int, font, stroke_w: int,
                        key_color=(255, 215, 0), base_color=(255, 255, 255)) -> int:
    """Draw text word-by-word: KEY words in yellow, rest white, thick black
    stroke, wrapped + centered per line (matches the viral thumbnail look)."""
    max_w = int(W * MAX_WIDTH_RATIO)

    def wlen(s):
        b = draw.textbbox((0, 0), s, font=font, stroke_width=stroke_w)
        return b[2] - b[0]

    space = wlen(" ")
    # greedy wrap into lines
    lines, cur, cur_w = [], [], 0
    for w in text.split():
        ww = wlen(w)
        if cur and cur_w + space + ww > max_w:
            lines.append(cur)
            cur, cur_w = [w], ww
        else:
            cur_w += (space + ww) if cur else ww
            cur.append(w)
    if cur:
        lines.append(cur)

    asc, desc = font.getmetrics()
    line_h = asc + desc + stroke_w * 2 + 12
    total_h = 0
    for li, words in enumerate(lines):
        # if no key word on this line, force the longest word yellow (always a pop)
        has_key = any(_is_key_word(w) for w in words)
        longest = max(words, key=len) if words and not has_key else None
        line_w = sum(wlen(w) for w in words) + space * (len(words) - 1)
        x = (W - line_w) // 2
        ly = y + li * line_h
        for w in words:
            col = key_color if (_is_key_word(w) or w is longest) else base_color
            draw.text((x, ly), w, fill=col, stroke_width=stroke_w,
                      stroke_fill=(0, 0, 0), font=font)
            x += wlen(w) + space
        total_h = (li + 1) * line_h
    return total_h


def make_thumbnail(script: dict, niche: str, out_path: Path, long_form: bool = False,
                   img_dir: Path | None = None) -> Path:
    """Generate thumbnail. Shorts mode = 1080x1920 vertical. Long-form mode =
    1280x720 horizontal with drama composition (text overlay right-side).

    img_dir: scene-image dir; if it holds character master portraits from the
    consistency pass, the base is reference-conditioned so the thumbnail face
    matches the video."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cfg = load_config()

    print(f"[thumbnail] generating base image (long_form={long_form})...")
    img = _gen_base_image(script, niche, long_form=long_form, img_dir=img_dir)

    target_size = (1280, 720) if long_form else (1080, 1920)
    if img.size != target_size:
        img = img.resize(target_size, Image.LANCZOS).filter(
            ImageFilter.UnsharpMask(radius=2, percent=130, threshold=3)
        )

    if long_form:
        return _render_longform_thumbnail(img, script, niche, cfg, out_path)

    # ── Shorts (existing layout, unchanged) ──
    img = _apply_gradients(img)
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
    if top_text:
        font_big = _fit_font(draw, top_text, max_w, start_size=220, min_size=130, stroke_w=16)
        try:
            th = _draw_words_colored(draw, top_text, W, y=120, font=font_big, stroke_w=16)
        except Exception as e:
            print(f"[thumbnail] per-word color failed ({e}) — solid yellow fallback")
            th = _draw_text_block(draw, top_text, W, y=120, fill=(255, 215, 0), font=font_big, stroke_w=16)
        sub_y = 120 + th + 40
    else:
        sub_y = 320
    if sub_text:
        font_sub = _fit_font(draw, sub_text, max_w, start_size=110, min_size=70, stroke_w=8)
        _draw_text_block(draw, sub_text, W, y=sub_y, fill=(255, 255, 255), font=font_sub, stroke_w=10)
    brand = (cfg.get("branding", {}).get("channel_handle", f"@{niche}").lstrip("@").upper())
    font_brand = ImageFont.truetype(_font_path(), size=60)
    _draw_text_block(draw, brand, W, y=H - 150, fill=(255, 215, 0), font=font_brand, stroke_w=4)

    img.save(str(out_path), "JPEG", quality=95)
    print(f"[thumbnail] saved → {out_path}")
    return out_path


def _render_longform_thumbnail(img: Image.Image, script: dict, niche: str,
                                cfg: dict, out_path: Path) -> Path:
    """Long-form 16:9 thumbnail (1280x720): BIG bold 3-5 word text on right-third,
    character on left, brand chip bottom-left.
    Inspired by Praveen Mohan / Project Nightfall thumbnails."""
    W, H = img.size  # 1280x720

    # Darken right-third for text legibility
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ovr_draw = ImageDraw.Draw(overlay)
    # Vertical gradient on right 40% (left 60% kept clean for character)
    text_zone_x = int(W * 0.55)
    for x in range(text_zone_x, W):
        alpha = int(180 * ((x - text_zone_x) / (W - text_zone_x)))
        ovr_draw.line([(x, 0), (x, H)], fill=(0, 0, 0, alpha))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    # Pick punchy text via existing LLM hook generator + take shortest possible
    try:
        texts = _gen_thumb_text(script, niche)
        line1 = texts.get("top", "").strip().upper()
        line2 = texts.get("bottom", "").strip().upper()
    except Exception:
        title = script.get("title", "")
        words = title.split()
        line1 = " ".join(words[:2]).upper()
        line2 = " ".join(words[2:5]).upper()

    # Cap to viral 3-5 word punch
    line1 = " ".join(line1.split()[:3])
    line2 = " ".join(line2.split()[:4])

    draw = ImageDraw.Draw(img)
    text_zone_w = W - text_zone_x - 40  # 40px right padding

    # Line 1: HUGE red/yellow (high contrast)
    if line1:
        f1 = _fit_font(draw, line1, text_zone_w, start_size=130, min_size=72, stroke_w=8)
        bbox = draw.textbbox((0, 0), line1, font=f1, stroke_width=8)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        x = text_zone_x + (text_zone_w - tw) // 2
        y = int(H * 0.20)
        draw.text((x, y), line1, fill=(255, 215, 0), font=f1, stroke_width=8, stroke_fill=(0, 0, 0))
        line2_y = y + th + 30

    # Line 2: medium white
    if line2:
        f2 = _fit_font(draw, line2, text_zone_w, start_size=90, min_size=56, stroke_w=6)
        bbox = draw.textbbox((0, 0), line2, font=f2, stroke_width=6)
        tw = bbox[2] - bbox[0]
        x = text_zone_x + (text_zone_w - tw) // 2
        draw.text((x, line2_y), line2, fill=(255, 255, 255), font=f2, stroke_width=6, stroke_fill=(0, 0, 0))

    # Brand chip bottom-left
    brand = (cfg.get("branding", {}).get("channel_handle", f"@{niche}").lstrip("@").upper())
    fb = ImageFont.truetype(_font_path(), size=40)
    bbox = draw.textbbox((0, 0), brand, font=fb, stroke_width=3)
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    # Brand box
    bx, by = 30, H - bh - 50
    draw.rounded_rectangle([bx - 15, by - 10, bx + bw + 15, by + bh + 15], radius=12, fill=(200, 20, 20))
    draw.text((bx, by), brand, fill=(255, 255, 255), font=fb, stroke_width=2, stroke_fill=(0, 0, 0))

    img.save(str(out_path), "JPEG", quality=95)
    print(f"[thumbnail] LONG-FORM 16:9 saved → {out_path}  (1280x720 drama composition)")
    return out_path
