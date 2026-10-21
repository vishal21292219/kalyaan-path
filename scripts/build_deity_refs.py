#!/usr/bin/env python3
"""Build the pinned deity reference library in assets/refs/.

WHY
---
Text-to-image gets some deities reliably wrong no matter how the prompt is
worded, and the error is not cosmetic: a bearded Indra, a human-faced Hanuman
or an unclothed Kali are the defects a devotee notices first. Five wordings
were tried on Kali and three on Shiva on 2026-10-21; none held.

What DOES hold is a pinned reference. image_gen._build_character_masters
prefers assets/refs/<deity>.jpg over anything it can generate, and every
reference-conditioned scene then inherits that frame's identity — so one
verified file fixes every future reel for that deity.

THE RECIPE (the one that actually worked, automated here)
  1. generate for CANON with the deity's own block leading the prompt
  2. gate it with pipeline.frame_check
  3. if it fails only on a fixable attribute, EDIT that one attribute out with
     nano-banana-2/edit, which preserves pose, palette and art style
  4. re-gate, and pin only on a pass

Nothing is pinned that has not passed the gate. A deity that cannot pass is
left unpinned and reported, rather than shipped.

    python scripts/build_deity_refs.py                 # only missing deities
    python scripts/build_deity_refs.py --only indra    # one deity
    python scripts/build_deity_refs.py --force         # rebuild even if pinned
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.frame_check import check                          # noqa: E402
from pipeline.image_gen import is_blank                          # noqa: E402
from pipeline.utils import load_config                           # noqa: E402

REFS = ROOT / "assets/refs"
GEN_MODEL = "fal-ai/flux/dev"          # dev, not schnell: schnell ignores the
EDIT_MODEL = "fal-ai/nano-banana-2/edit"   # block and returns beards anyway.

POSE = (" He stands calm and frontal, full body, filling the frame against a "
        "plain deep indigo ground.")

# How to EDIT out each defect the gate can report. Each instruction names what
# should be PRESENT (never an absence) and pins everything else to the source,
# because the whole value of the edit is that it changes one thing only.
FIXES = {
    "facial hair": (
        "Shave the figure completely. The jaw, chin, cheeks and upper lip are "
        "now smooth bare skin with no hair of any kind on them — the clean "
        "smooth face of a young man. Keep the eyes, nose, hair, crown, "
        "ornaments, weapons, pose, background, lighting and painting style "
        "EXACTLY as in the reference. Change nothing except removing the "
        "facial hair."),
    "not clothed": (
        "Dress the goddess so her chest, shoulders and torso are completely "
        "covered by a traditional red silk blouse with full sleeves, and drape "
        "her garland over it. Keep her face, skin colour, eyes, tongue, hair, "
        "crown, what she holds, the background, lighting and painting style "
        "EXACTLY as in the reference. Change nothing else."),
    "wrong form": (
        "Give the figure the correct head: a monkey's furred muzzle with a "
        "monkey's nose, mouth and ears for Hanuman, an elephant's head with "
        "trunk and large ears for Ganesha. Keep the body, ornaments, weapons, "
        "pose, background, lighting and painting style EXACTLY as in the "
        "reference. Change nothing else."),
}


def _fal_gen(prompt: str, out: Path) -> bool:
    import fal_client
    try:
        r = fal_client.subscribe(GEN_MODEL, arguments={
            "prompt": prompt, "image_size": "portrait_16_9", "num_images": 1,
            "num_inference_steps": 30, "guidance_scale": 4.0,
            "enable_safety_checker": True, "output_format": "jpeg"}, with_logs=False)
        out.write_bytes(requests.get(r["images"][0]["url"], timeout=120).content)
        return True
    except Exception as e:
        print(f"    gen failed: {type(e).__name__}: {str(e)[:90]}")
        return False


def _fal_edit(src: Path, instruction: str, out: Path) -> bool:
    import fal_client
    try:
        url = fal_client.upload_file(str(src))
        r = fal_client.subscribe(EDIT_MODEL, arguments={
            "prompt": instruction, "image_urls": [url],
            "aspect_ratio": "9:16", "num_images": 1}, with_logs=False)
        u = (r.get("images") or [{}])[0].get("url")
        if not u:
            return False
        out.write_bytes(requests.get(u, timeout=120).content)
        return True
    except Exception as e:
        print(f"    edit failed: {type(e).__name__}: {str(e)[:90]}")
        return False


def _fix_for(reasons: list[str]) -> str | None:
    joined = " ".join(reasons).lower()
    for key, instruction in FIXES.items():
        if key in joined:
            return instruction
    return None


def build(deity: str, block: str, tail: str, tries: int = 3) -> bool:
    out = REFS / f"{deity}.jpg"
    scene = f"a reference portrait of {deity}"
    prompt = f"{block}{POSE}{tail}"
    tmp = out.with_suffix(".tmp.jpg")

    for attempt in range(1, tries + 1):
        if not _fal_gen(prompt, tmp) or is_blank(tmp):
            continue
        good, why = check(tmp, deity, scene)
        if good:
            tmp.replace(out)
            print(f"    PINNED on attempt {attempt}")
            return True
        print(f"    attempt {attempt}: {'; '.join(why)[:90]}")

        instruction = _fix_for(why)
        if instruction and _fal_edit(tmp, instruction, tmp):
            good, why = check(tmp, deity, scene)
            if good:
                tmp.replace(out)
                print(f"    PINNED on attempt {attempt} (after edit)")
                return True
            print(f"    after edit: {'; '.join(why)[:90]}")

    tmp.unlink(missing_ok=True)
    print("    NOT PINNED — left for a human")
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="only these deities")
    ap.add_argument("--force", action="store_true", help="rebuild already-pinned deities")
    args = ap.parse_args()

    cfg = load_config()
    blocks = (cfg.get("images", {}) or {}).get("deity_blocks") or {}
    tail = ((cfg.get("images", {}) or {}).get("style_tail") or "")
    REFS.mkdir(parents=True, exist_ok=True)

    names = args.only or sorted(blocks)
    done, failed, skipped = [], [], []
    for d in names:
        if d not in blocks:
            print(f"{d}: no deity_block — skipped"); skipped.append(d); continue
        if (REFS / f"{d}.jpg").exists() and not args.force:
            print(f"{d}: already pinned"); skipped.append(d); continue
        print(f"{d}:")
        (done if build(d, blocks[d], tail) else failed).append(d)

    print(f"\npinned {len(done)}: {', '.join(done) or '-'}")
    print(f"failed {len(failed)}: {', '.join(failed) or '-'}")
    print(f"skipped {len(skipped)}: {', '.join(skipped) or '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
