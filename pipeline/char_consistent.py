"""Character-consistent scene generation (Level 2 — reference conditioning).

Why this exists: seed-locking FLUX did NOT keep a deity's face consistent
across scenes (prompt changes shift the face). The fix that actually works
(and what strong AI-reel creators use) is REFERENCE-IMAGE conditioning:

  1. Generate ONE premium master portrait of the deity.
  2. Generate every scene with nano-banana-2/edit, passing that master
     portrait as a reference so the SAME face/design is reused, only the
     pose/action/background change.

All fal-paid. Master ~$0.04 (FLUX 1.1-pro), each scene a nano-banana-2 edit.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests
from dotenv import load_dotenv

from .image_gen import _fit_to_aspect, _generate_fal_flux

load_dotenv(override=True)

NANO_EDIT_MODEL = "fal-ai/nano-banana-2/edit"

# The ONE locked art style for the whole reel (chosen 2026-05-30: Amar Chitra
# Katha). Every scene must repeat this verbatim so there is zero style drift.
ART_STYLE = (
    "Amar Chitra Katha comic illustration style — bold clean black ink outlines, "
    "flat vibrant saturated colors, classic Indian mythology comic-book look, "
    "smooth cel shading, no photorealism, no 3D render"
)


def generate_master_portrait(out_path: Path, look: str, art_style: str = ART_STYLE,
                             target_w: int = 1080, target_h: int = 1920) -> bool:
    """Generate the canonical master portrait via FLUX 1.1-pro (premium, anatomy
    correct). This single image defines the deity's face/design for the whole reel."""
    prompt = (
        f"{art_style}. Full-body character reference portrait of {look}. "
        "Centered frontal hero pose, clean simple background, dramatic divine "
        "lighting, intricate detail, devotional comic poster art, ultra detailed "
        "expressive vanara monkey face, majestic and beautiful, masterpiece. "
        "Vertical 9:16."
    )
    ok = _generate_fal_flux(prompt, out_path, target_w=target_w, target_h=target_h)
    if ok:
        print(f"[char] master portrait → {out_path.name}")
    else:
        print("[char] master portrait generation FAILED")
    return ok


def _fal_upload(path: Path) -> str | None:
    try:
        import fal_client
        return fal_client.upload_file(str(path))
    except Exception as e:
        print(f"[char] upload failed: {type(e).__name__}: {e}")
        return None


def generate_scene_with_reference(
    master_url: str | list[str],
    scene_action: str,
    out_path: Path,
    char_name: str = "the same character",
    art_style: str = ART_STYLE,
    aspect_ratio: str = "9:16",
    target_w: int = 1080,
    target_h: int = 1920,
) -> bool:
    """Generate one scene that keeps the master portrait's character identity.

    master_url: a single reference image URL, or a list of reference URLs when
    multiple recurring characters appear in the same scene (nano-banana-2/edit
    accepts several reference images and keeps each one's identity).

    scene_action: what is happening (English), e.g. "lifting an entire glowing
    mountain over his head, dust falling, epic low angle".
    """
    image_urls = [master_url] if isinstance(master_url, str) else list(master_url)
    if not image_urls:
        print("[char] no reference url(s) provided")
        return False
    if not os.getenv("FAL_KEY"):
        print("[char] FAL_KEY missing")
        return False
    try:
        import fal_client
    except ImportError:
        print("[char] fal_client not installed")
        return False

    prompt = (
        f"Keep {char_name} EXACTLY as in the reference image — identical face, "
        f"skin color, hair, crown, jewelry and features. Do not redesign the "
        f"character(s). Render the entire image in {art_style} — match the "
        f"reference's art style exactly. New scene: {scene_action}. Vertical 9:16 "
        f"devotional frame, soft lighting, highly detailed, no text or watermark."
    )
    try:
        result = fal_client.subscribe(
            NANO_EDIT_MODEL,
            arguments={
                "prompt": prompt,
                "image_urls": image_urls,
                "aspect_ratio": aspect_ratio,
                "num_images": 1,
            },
            with_logs=False,
        )
    except Exception as e:
        print(f"[char] nano-banana edit failed: {type(e).__name__}: {e}")
        return False

    images = result.get("images") or []
    url = images[0].get("url") if images and isinstance(images[0], dict) else None
    if not url:
        print(f"[char] no image url in response: {result}")
        return False

    try:
        r = requests.get(url, timeout=90)
        if r.status_code != 200 or len(r.content) < 5000:
            print(f"[char] download failed: HTTP {r.status_code}, {len(r.content)}B")
            return False
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(r.content)
    except Exception as e:
        print(f"[char] download error: {type(e).__name__}: {e}")
        return False

    # Enforce exact 9:16 frame for the assembler
    try:
        from PIL import Image
        img = Image.open(out_path)
        if img.size != (target_w, target_h):
            img = _fit_to_aspect(img, target_w, target_h)
            img.convert("RGB").save(str(out_path), "JPEG", quality=92)
    except Exception as e:
        print(f"[char] resize warning: {e}")
    return True
