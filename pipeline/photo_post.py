"""PHOTO LANE — one image, one sentence. The cheap half of the Facebook page.

WHY THIS EXISTS (2026-10-21 competitor audit, measured, not assumed)
--------------------------------------------------------------------
Awakeners (151K followers, the closest real competitor — Sanatan + psychology,
also openly AI) was scraped: 140 reels, median 3,200 views. Their REELS are
losing to their PHOTOS by an order of magnitude on the same page in the same
week:

    reel  (Dussehra, 8h old) ....  17 likes   1 comment   10 shares
    photo (Kali) ...............  668 likes  65 comments  76 shares
    photo ("worship God") ......  223 likes   7 comments  59 shares
    photo ("People are portals")  208 likes   3 comments  81 shares

Their best photo is the whole format in one line:

    AI Kali art + "Kali destroys the illusion that you must remain the
    person your pain made you."  — deity name in gold, rest in white,
    small watermark. No slides. No details. ONE sentence.

That is a ~10x cheaper unit than a GoM reel (no script, no TTS, no motion, no
assembly) and Meta's Content Monetization pays on photos as well as reels, so
this lane earns as well as grows. GoM was 100% reels at 4/week; this lane is
what takes the page to competitor cadence without touching the reel schedule.

DESIGN CONSTRAINTS — each one is from the audit, do not "improve" them blind:
  · 4:5 (1080x1350). Measured off Awakeners' best-performing posts; it is the
    tallest aspect FB allows in-feed, i.e. maximum screen real estate.
  · ONE sentence, <= 3 rendered lines. An earlier attempt at multi-slide decks
    with "details on slide 1" was rejected four times by the user and is
    contradicted by every top post on the competitor page.
  · The deity's own name is the gold accent. It is the brand tell and the only
    colour break in the type.
  · A gradient scrim under the text, ALWAYS. Legibility cannot depend on which
    image the model happened to return.
  · The image must DRAMATISE the line (same rule as the reel pipeline learned
    at 8c83e0f) — not be a generic portrait of the deity.

Entry point: scripts/make_photo_post.py
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from .image_gen import _deity_block
from .utils import load_config

load_dotenv(override=True)

ROOT = Path(__file__).resolve().parent.parent
FONT_SERIF = ROOT / "assets/fonts/PlayfairDisplay.ttf"
FONT_MARK = ROOT / "assets/fonts/CormorantGaramond.ttf"

W, H = 1080, 1350          # 4:5 — see module docstring
GOLD = (232, 182, 90)      # deity name + watermark
WHITE = (247, 243, 236)    # warm white, not pure #fff (reads softer on art)


# ── 1. THE LINE ──────────────────────────────────────────────────────────────

_LINE_SYSTEM = """You write single-sentence posts for "Gods of the Mind", a page \
that decodes Hindu dharma as psychology. You never use the words "myth" or \
"mythology" — these are sacred traditions. Use Sanatan Dharma, Hindu wisdom, \
scriptures, Pauranik.

THE FORM. Exactly ONE sentence. It names a deity and reframes a private, \
painful, second-person experience through them. The reader should feel caught \
out, then relieved. Calm and revelatory, never hyped, never preachy, no emojis, \
no hashtags, no quotation marks.

The measured benchmark in this lane (668 likes / 65 comments / 76 shares on a \
151K page):
  "Kali destroys the illusion that you must remain the person your pain made you."

Study what makes it work and match that register:
  · the deity is the SUBJECT doing something, not a label
  · the pain is specific and unflattering and the reader recognises it as theirs
  · the turn is a reframe, not advice — nothing is asked of the reader
  · 12-22 words. It must fit in three lines of large type.

BANNED: "Did you know", "Remember that", "In Hinduism", imperatives ("let go", \
"embrace", "trust"), generic affirmation, astrology, birth charts, anything that \
could be any deity.

For each line also give:
  deity   — the single deity named, lowercase, one word
  visual  — one sentence of art direction that DRAMATISES THE LINE, not a \
portrait. State what the deity is DOING and what is happening around them so \
the picture and the sentence say the same thing. Do not describe the deity's \
fixed attributes — those are added automatically.
    Two hard rules, both learned from a failed render:
      · The lower third of the frame must go DARK — deep shadow, black smoke, \
night water, unlit ground. The post's text sits there. "Pale", "flat" or \
"simple" is not enough.
      · Never ask for a washed-out, white, grey, misty-pale or desaturated \
scene. The palette is always deep and saturated — indigo, teal, blood red, \
gold, violet, ember. A grey scene reads as generic self-help stock and this \
lane has already measured that it kills reach.

Return ONLY a JSON array: [{"line": "...", "deity": "...", "visual": "..."}]"""


def write_lines(n: int = 8, avoid: list[str] | None = None, model: str = "") -> list[dict]:
    """Ask Claude for n new lines. Raises on failure — a bad pool is worse than
    no pool, and this is a batch job, not something in a render's critical path."""
    from .script_writer import _claude

    cfg = load_config()
    deities = sorted((cfg.get("images", {}) or {}).get("deity_blocks") or {})
    avoid = [a for a in (avoid or []) if a]
    user = (
        f"Write {n} lines. Available deities (use only these, and spread them out "
        f"— no deity twice in this batch): {', '.join(deities)}.\n"
    )
    if avoid:
        recent = "\n".join(f"- {a}" for a in avoid[-60:])
        user += (
            "\nThese already exist. Do not repeat their deity+theme pairing, and "
            f"do not echo their phrasing:\n{recent}\n"
        )
    raw = _claude(_LINE_SYSTEM, user, model or (cfg.get("llm", {}) or {}).get("model") or "claude-sonnet-4-6")
    m = re.search(r"\[.*\]", raw, re.S)
    if not m:
        raise RuntimeError(f"line writer returned no JSON array: {raw[:300]}")
    out = []
    for item in json.loads(m.group(0)):
        line = (item.get("line") or "").strip().strip('"')
        deity = (item.get("deity") or "").strip().lower()
        visual = (item.get("visual") or "").strip()
        if not (line and deity and visual):
            continue
        bad = _reject(line, deity)
        if bad:
            print(f"[photo] rejected ({bad}): {line}")
            continue
        out.append({"line": line, "deity": deity, "visual": visual})
    return out


_BANNED_WORDS = ("myth", "mythology")

# Deities whose text-to-image prior is wrong in a way no prompt wording fixes,
# pinned instead to a known-good reference frame in assets/refs/<deity>.jpg and
# rendered through nano-banana-2/edit so the reference's clothing and identity
# carry into every new scene.
#
# Kali, 2026-10-21: FLUX renders her bare-chested and FIVE wordings failed to
# override it — "chest fully covered" (ignored twice), a sari over one shoulder
# (breast exposed, twice), and an "armoured choli" that covered her but came out
# as Western fantasy armour rather than devotional iconography. Prompt wording
# was the wrong tool. What worked: generate her once for canon (black skin,
# three eyes, protruding tongue, supine Shiva underfoot), EDIT that frame to add
# a red silk blouse and the mundamala draped shoulder-to-hip, and pin the result.
# Verified on two unrelated scenes: clothing and style both held.
REF_DEITIES = {"kali"}

REFS_DIR = ROOT / "assets/refs"


def _reject(line: str, deity: str) -> str:
    """Return a reason string if the line must not ship, else ""."""
    low = line.lower()
    for w in _BANNED_WORDS:
        if w in low:
            return f"banned word '{w}'"          # settled rule, see CLAUDE.md
    if deity not in low:
        return "deity not named in the line"      # the gold accent needs it
    if line.count(".") > 1 or "?" in line or "!" in line:
        return "not a single calm sentence"
    words = len(line.split())
    if not 10 <= words <= 26:
        return f"{words} words (want 10-26)"
    return ""


# ── 2. THE IMAGE ─────────────────────────────────────────────────────────────

_STYLE_TAIL = (
    ", Raja Ravi Varma devotional oil painting fused with cosmic symbolism, "
    "deep teal and indigo depths, golden divine rim light, volumetric mist, "
    "one dominant figure, rich saturated jewel colour, ornate detail, "
    "the lower third of the frame falling into deep uncluttered shadow, "
    "no text, no watermark, masterpiece"
)


def _fal_image(prompt: str, out_path: Path, model: str = "fal-ai/flux/dev") -> bool:
    """One 3:4 image from fal, cropped to 4:5. Mirrors image_gen's endpoint
    branching: flux-pro/v1.1 rejects num_inference_steps/guidance_scale/
    enable_safety_checker, dev and schnell accept them."""
    if not os.getenv("FAL_KEY"):
        print("[photo] FAL_KEY missing")
        return False
    import fal_client

    args = {"prompt": prompt, "image_size": "portrait_4_3",
            "num_images": 1, "output_format": "jpeg"}
    m = model.lower()
    if "flux-pro" in m:
        args["safety_tolerance"] = "2"
    else:
        args["num_inference_steps"] = 12 if "schnell" in m else 30
        args["enable_safety_checker"] = True
        if "schnell" not in m:
            args["guidance_scale"] = 4.0
    try:
        res = fal_client.subscribe(model, arguments=args, with_logs=False)
        url = (res.get("images") or [{}])[0].get("url")
        if not url:
            print(f"[photo] fal returned no image: {str(res)[:200]}")
            return False
        out_path.write_bytes(requests.get(url, timeout=120).content)
        return True
    except Exception as e:
        print(f"[photo] fal error: {type(e).__name__}: {e}")
        return False


def _is_blank(path: Path) -> bool:
    """True if the file is effectively an empty frame.

    flux-pro/v1.1 does not always RAISE when its safety checker fires — on the
    Kali prompt it returned HTTP 200 with a solid black JPEG, which composited
    into a perfectly typeset post with no picture in it and would have published.
    Silent success on a failed step is this project's most expensive bug class
    (a YouTube failure reported SUCCESS for 24 days), so every generated frame is
    checked before it is allowed anywhere near a caption."""
    from PIL import Image, ImageStat
    try:
        st = ImageStat.Stat(Image.open(path).convert("L"))
        return st.stddev[0] < 10 or st.mean[0] < 12
    except Exception:
        return True


def _build_prompt(deity: str, visual: str, cfg: dict) -> str:
    block = _deity_block(deity, cfg) or _deity_block(visual, cfg)
    if not block:
        raise RuntimeError(f"no iconography block for deity '{deity}' — "
                           f"images.deity_blocks must cover every deity the "
                           f"line writer is allowed to use")
    # Iconography FIRST, action second. FLUX weights the head of the prompt most,
    # and the first render of this lane proved it: with the scene sentence leading,
    # Shiva came back blue-skinned with no trishul, no crescent and no tiger skin
    # while the scene's own "ash-grey emptiness" dominated the whole frame. Being
    # the right deity matters more than the staging, so the block leads.
    return f"{block} {visual.rstrip('. ')}{_STYLE_TAIL}"


# ── 3. THE COMPOSITE ─────────────────────────────────────────────────────────

def _fit_45(img):
    from PIL import Image
    sw, sh = img.size
    want = W / H
    if sw / sh > want:
        nw = int(sh * want)
        img = img.crop(((sw - nw) // 2, 0, (sw - nw) // 2 + nw, sh))
    elif sw / sh < want:
        nh = int(sw / want)
        # Crop from the TOP, not the centre: these are portraits, the face is
        # high in the frame and the bottom is the shadow we asked for.
        img = img.crop((0, 0, sw, nh))
    return img.resize((W, H), Image.LANCZOS)


def _wrap(text: str, font, max_w: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if font.getlength(trial) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _layout(text: str, max_w: int, max_lines: int = 3):
    """Largest serif size at which `text` wraps into <= max_lines. Returns
    (font, lines). Falls back to 4 lines before it will shrink below 46px —
    unreadable type is a worse failure than an extra line."""
    from PIL import ImageFont
    for limit in (max_lines, max_lines + 1):
        for size in range(86, 45, -2):
            f = ImageFont.truetype(str(FONT_SERIF), size)
            f.set_variation_by_axes([600])
            lines = _wrap(text, f, max_w)
            if len(lines) <= limit:
                return f, lines
    f = ImageFont.truetype(str(FONT_SERIF), 46)
    f.set_variation_by_axes([600])
    return f, _wrap(text, f, max_w)


FADE = 340          # px of gradient above the text block
ALPHA_AT_TEXT = 170  # guaranteed darkness where the first line starts
ALPHA_AT_FOOT = 210  # at the very bottom


def _scrim(img, text_top: int):
    """Black gradient keyed to WHERE THE TEXT ACTUALLY STARTS, not to a fixed
    fraction of the frame. Transparent until FADE px above the text, ALPHA_AT_TEXT
    by the time the first line begins, ALPHA_AT_FOOT at the bottom edge.

    Keyed to the text rather than the image because the first version faded from
    a fixed 55% and left only alpha 58 under the opening line — on a bright frame
    (pale smoke behind Shiva) the white serif sat on near-white and the post was
    unusable. Legibility must never depend on what the image model returned."""
    from PIL import Image
    grad = Image.new("L", (1, H), 0)
    px = grad.load()
    start = max(0, text_top - FADE)
    for y in range(H):
        if y <= start:
            px[0, y] = 0
        elif y < text_top:
            px[0, y] = int(ALPHA_AT_TEXT * (y - start) / max(1, text_top - start))
        else:
            t = (y - text_top) / max(1, H - text_top)
            px[0, y] = int(ALPHA_AT_TEXT + (ALPHA_AT_FOOT - ALPHA_AT_TEXT) * t)
    grad = grad.resize((W, H))
    black = Image.new("RGB", (W, H), (6, 8, 12))
    return Image.composite(black, img, grad)


def _draw_accented(draw, lines, font, deity: str, y0: int, line_h: int):
    """Centre each line, drawing the deity's own name in gold and the rest in
    warm white. Word-by-word so the accent survives wrapping."""
    needle = deity.lower()
    for i, line in enumerate(lines):
        words = line.split()
        widths = [font.getlength(w) for w in words]
        space = font.getlength(" ")
        total = sum(widths) + space * (len(words) - 1)
        x = (W - total) / 2
        y = y0 + i * line_h
        for w, wd in zip(words, widths):
            colour = GOLD if needle in re.sub(r"[^a-z]", "", w.lower()) else WHITE
            draw.text((x, y), w, font=font, fill=colour)
            x += wd + space


def compose(image_path: Path, line: str, deity: str, out_path: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    img = _fit_45(Image.open(image_path).convert("RGB"))
    margin = 86
    font, lines = _layout(line, W - 2 * margin)
    line_h = int(font.size * 1.26)
    block_h = line_h * len(lines)

    mark_size = 30
    baseline = H - 108                       # bottom of the text block
    y0 = baseline - block_h
    img = _scrim(img, text_top=y0)

    draw = ImageDraw.Draw(img)
    _draw_accented(draw, lines, font, deity, y0, line_h)

    mark = ImageFont.truetype(str(FONT_MARK), mark_size)
    mark.set_variation_by_axes([600])
    text = "G O D S   O F   T H E   M I N D"
    draw.text(((W - mark.getlength(text)) / 2, H - 76), text, font=mark, fill=GOLD)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=92)
    return out_path


# ── 4. THE CAPTION ───────────────────────────────────────────────────────────

# Awakeners' best-performing reels carry 12+ hashtags; GoM reels are capped at 5
# on Facebook (uploader_make_reel.FB_MAX_HASHTAGS) after an earlier throttling
# scare. That cap was set for VIDEO. Photos are a different surface and the
# competitor evidence is 12+, so this lane runs wider on purpose and the two
# lanes stay independently measurable.
PHOTO_TAGS = [
    "#godsofthemind", "#sanatandharma", "#hinduwisdom", "#psychology",
    "#spiritualawakening", "#consciousness", "#shadowwork", "#selfawareness",
    "#innerwork", "#philosophy", "#mindfulness", "#spirituality",
]


def caption(line: str, deity: str) -> str:
    follow = ("👉 Follow Gods of the Mind — a new god decoded every day. "
              "Don't miss the next one.")
    ask = "💬 Tag someone who needs to read this today."
    return "\n\n".join([line, ask, follow, " ".join(PHOTO_TAGS)])


# ── 5. ONE POST ──────────────────────────────────────────────────────────────

PRIMARY_MODEL = "fal-ai/flux-pro/v1.1"   # best anatomy — matters most for the
FALLBACK_MODEL = "fal-ai/flux/dev"       # many-armed deities. See build().


def build(item: dict, out_dir: Path, model: str = "") -> dict:
    """item = {line, deity, visual} -> {image, caption, ...}. Raises on failure.

    Model policy: flux-pro/v1.1 first — measured side by side on the same Durga
    prompt it gave clean hands and six distinct weapons where flux/dev gave
    duplicated bows and mangled fingers, and at one post a day the difference is
    a few rupees a month. But pro's safety checker silently blanks some prompts
    (Kali), so a blank frame falls back to dev rather than shipping empty."""
    cfg = load_config()
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "_", item["line"].lower())[:48].strip("_")
    raw = out_dir / f"{slug}__raw.jpg"
    final = out_dir / f"{slug}.jpg"

    # Pinned-reference path first, for deities text-to-image gets wrong (see
    # REF_DEITIES). The reference carries identity AND clothing into the scene,
    # which is the whole reason it exists.
    ref = REFS_DIR / f"{item['deity']}.jpg"
    if item["deity"] in REF_DEITIES and ref.exists():
        from .char_consistent import _fal_upload, generate_scene_with_reference
        url = _fal_upload(str(ref))
        style = ((cfg.get("images", {}) or {}).get("style_tail") or "").lstrip(", ").strip()
        if url and generate_scene_with_reference(
                url, item["visual"], raw, char_name=item["deity"].title(),
                art_style=style, aspect_ratio="3:4", target_w=W, target_h=H) \
                and not _is_blank(raw):
            compose(raw, item["line"], item["deity"], final)
            return {"line": item["line"], "deity": item["deity"], "visual": item["visual"],
                    "image": str(final), "raw": str(raw),
                    "caption": caption(item["line"], item["deity"]), "prompt": f"[ref:{ref.name}] {item['visual']}"}
        print(f"[photo] reference path failed for {item['deity']} — falling back to text-to-image")

    prompt = _build_prompt(item["deity"], item["visual"], cfg)
    chain = [model] if model else [PRIMARY_MODEL, FALLBACK_MODEL]
    for m in chain:
        for attempt in range(2):
            if _fal_image(prompt, raw, m):
                if not _is_blank(raw):
                    break
                print(f"[photo] {m} returned a blank frame (safety checker) — discarding")
            time.sleep(6)
        else:
            continue
        break
    else:
        raise RuntimeError(f"image generation failed for: {item['line']}")

    compose(raw, item["line"], item["deity"], final)
    return {"line": item["line"], "deity": item["deity"], "visual": item["visual"],
            "image": str(final), "raw": str(raw),
            "caption": caption(item["line"], item["deity"]), "prompt": prompt}
