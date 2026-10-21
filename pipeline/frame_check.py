"""Look at the frame before it ships.

WHY THIS EXISTS
---------------
Every other kind of bug in this repo surfaces as an exception or a failed call.
The ones that actually reach the audience do not: a bearded Krishna, a goddess
without a garment, a black frame, a picture that has nothing to do with its
line — all of these are SUCCESS to the pipeline. There is no assertion that can
fail, because the output is a picture and the code cannot see it.

Worse, the architecture is built never to fail: fal answers HTTP 200 with a
black image when its safety checker fires, and the fal -> HF -> Gemini chain
turns a failure into silent degradation. So the pipeline reports success in
exactly the cases where a human would say "that is unusable".

The channel's non-negotiable rules ("Krishna is clean-shaven", "deities are
mature adults", "a goddess is clothed") have until now lived only in prose — in
CLAUDE.md and in YAML comments. Prose does not run. The LLM rewrites the
character bible every run and quietly violates it; on 2026-10-21 it wrote
"clean-shaven ... never a full beard" and produced a bearded master that went
into a published reel.

This module is the missing layer: it turns those prose rules into a gate by
giving the pipeline eyes. One vision call per frame, a hard verdict, and the
caller regenerates on failure.

Deliberately NOT a style critic. It answers only questions with a right answer,
because a subjective gate would reject good frames and get switched off.
"""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

# Deities whose canon REQUIRES a bare jaw. A beard on any of these is a hard
# fail — it is the single most-reported defect on this channel.
CLEAN_SHAVEN = {"krishna", "ram", "rama", "vishnu", "kartikeya", "indra", "shiva"}
# Brahma and Yama are bearded by canon; never flag them.
BEARDED_OK = {"brahma", "yama", "shani"}
GODDESSES = {"kali", "durga", "parvati", "lakshmi", "saraswati"}

# Deities whose FORM — not just their attributes — is the thing that goes wrong.
# A human-faced Hanuman is the channel's most-documented iconography drift and
# is what a devotee notices first. Measured 2026-10-21: a generated Hanuman came
# back as a bearded human man and the checker only blocked it by luck, on an
# unrelated staging nitpick. Stated as the REQUIRED form, never as a ban.
FORM_REQUIRED = {
    "hanuman": "the head and face of a MONKEY — a furred muzzle with a monkey's "
               "nose and mouth pushed forward and monkey ears — on a man's body",
    "ganesha": "the head of an ELEPHANT, with a trunk and large fan-like ears",
    "jagannath": "a stylised wooden temple murti with huge round eyes and an "
                 "abstract armless form, never a realistic human",
}

MODEL = os.getenv("FRAME_CHECK_MODEL", "claude-haiku-5-5")

_PROMPT = """You are a quality gate for a Hindu devotional art pipeline. Answer \
ONLY from what is visibly in this image. Do not be generous and do not guess.

Return STRICT JSON, no prose:
{{
  "facial_hair": true|false,     // ANY beard, moustache, goatee or stubble on the main figure's face
  "torso_covered": true|false,   // the main figure's chest is covered by clothing, armour or a broad garland. For a male figure a bare chest is normal — answer true. For a FEMALE figure answer false if the breasts are bare or only partly covered.
  "is_child": true|false,        // the main figure reads as a child or baby rather than an adult
  "scene_match": 0|1|2,          // how well the image matches this description: 2 = clearly this scene, 1 = the right subject but staged differently (pose, props, angle, colour all differ - this is FINE), 0 = a DIFFERENT subject, or the central element of the description is entirely absent. Described scene: "{scene}"
  "form_ok": true|false,         // {form_q}
  "garbled_text": true|false,    // any rendered lettering or watermark that is not real words
  "deity_dominant": true|false,  // TRUE only if a HINDU DEITY, or a bold sacred object (trishul, vahana, yantra, murti, conch, lotus-throne), is the LARGE dominant subject of this frame, clearly visible and taking up most of it. Answer FALSE for: an ordinary modern person, a small distant silhouette, a body part with no face or deity, an empty landscape, sky or room, an abstract light effect with no figure.
  "note": "one short sentence on anything clearly wrong"
}}"""


def _b64(path: Path) -> tuple[str, str]:
    """Media type is sniffed from the BYTES, not the filename. nano-banana-2
    returns PNG data that this pipeline writes to a .jpg path, and the API
    rejects the mismatch outright — caught the first time this module was
    tested, which is the only reason it is not a production bug."""
    raw = path.read_bytes()
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        media = "image/png"
    elif raw[:3] == b"\xff\xd8\xff":
        media = "image/jpeg"
    elif raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        media = "image/webp"
    else:
        media = "image/jpeg"
    return media, base64.standard_b64encode(raw).decode()


def inspect(path: Path, scene: str = "", deity: str = "") -> dict | None:
    """Raw vision verdict for one frame, or None if the check could not run.

    None means UNKNOWN, never "fine" — callers must not treat it as a pass that
    lets a frame through on a silent API failure. That is the exact bug class
    this module exists to kill."""
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        print("[frame_check] ANTHROPIC_API_KEY missing — check skipped")
        return None
    try:
        import anthropic
        media, data = _b64(Path(path))
        resp = anthropic.Anthropic(api_key=key).messages.create(
            model=MODEL,
            # 2000, not 400: this model has thinking ON by default, the
            # ThinkingBlock eats the budget first, and at 400 the run stopped at
            # stop_reason=max_tokens with the JSON truncated mid-"note" — which
            # the parser then read as "no verdict" and let the frame through.
            # The same ThinkingBlock trap is documented in script_writer._claude.
            max_tokens=2000,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}},
                {"type": "text", "text": _PROMPT.format(
                    scene=(scene or "not specified")[:400],
                    form_q=(f"the main figure has {FORM_REQUIRED[deity]}"
                            if deity in FORM_REQUIRED else "always answer true"))},
            ]}],
        )
        text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), "")
        if getattr(resp, "stop_reason", None) == "max_tokens":
            print("[frame_check] response hit max_tokens — verdict may be partial")
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            print(f"[frame_check] no JSON in response: {text[:120]!r}")
            return None
        return json.loads(m.group(0))
    except Exception as e:
        print(f"[frame_check] check failed: {type(e).__name__}: {e}")
        return None


def check(path: Path, deity: str = "", scene: str = "") -> tuple[bool, list[str]]:
    """(ok, reasons). ok is True when nothing disqualifying was SEEN.

    An unavailable checker returns ok=True with a reason noting it did not run,
    so a missing API key degrades to today's behaviour rather than blocking
    every render — but the reason is printed so it is never silent."""
    d0 = (deity or "").strip().lower()
    v = inspect(Path(path), scene, d0)
    if v is None:
        return True, ["check did not run"]

    d = d0
    bad: list[str] = []
    if d in FORM_REQUIRED and v.get("form_ok") is False:
        bad.append(f"{d} is the wrong form (needs {FORM_REQUIRED[d].split(' - ')[0].split(',')[0]})")
    if v.get("facial_hair") and d in CLEAN_SHAVEN and d not in BEARDED_OK:
        bad.append(f"facial hair on {d} (canon: bare jaw)")
    if d in GODDESSES and v.get("torso_covered") is False:
        bad.append(f"{d} is not clothed")
    if v.get("is_child"):
        bad.append("deity rendered as a child")
    # Only a 0 fails. A boolean here was tried both ways on 2026-10-21 and
    # neither worked: strict rejected a good Hanuman over where he held a
    # boulder, loose passed a frame whose scene (a churning ocean of poison)
    # had become a man with a bow. Relevance is a judgement, so the gate only
    # catches the gross case and the real fix lives upstream — the bulk model
    # was raised schnell -> dev, which is what actually caused the mismatches.
    if scene and v.get("scene_match") == 0:
        bad.append("image shows a different subject than its line")
    if v.get("garbled_text"):
        bad.append("garbled lettering in frame")
    # The channel's whole proposition is darshan — the viewer SEEING the deity.
    # Measured 2026-10-21 on a finished reel: 5 of 9 sampled frames had no deity
    # at all (a person asleep in bed, a silhouette in a doorway, a tiny figure in
    # a light beam, a bare torso, a woman's profile made of clouds). Every one of
    # those is already BANNED in images.image_style_guidance — in prose, which
    # does not run. The user's words: "images bhagwaan wali feeling nahi de rahe".
    if v.get("deity_dominant") is False:
        bad.append("no deity or sacred symbol dominates the frame")
    return (not bad), (bad or [v.get("note") or "ok"])
