"""Image generation — multi-provider chain.

Primary:  fal.ai FLUX 1.1-pro (PAID ~$0.04/img, anatomy-correct, premium quality)
Fallback: HuggingFace FLUX schnell (FREE, anatomy issues but reliable)
Last:     Gemini Nano Banana (FREE, often quota-banned)

If ALL fail after retries → raise GeminiUnavailable so run.py can record
the failure in retry_queue.json and exit cleanly. Hourly retry cron retries.
"""
from __future__ import annotations

import base64
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from .utils import load_config, slugify

load_dotenv(override=True)

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
HF_ROUTER_BASE = "https://router.huggingface.co/hf-inference/models"
HF_DEFAULT_MODEL = "black-forest-labs/FLUX.1-schnell"
FAL_FLUX_PRO = "fal-ai/flux-pro/v1.1"
MAX_RETRIES = 5
RETRY_SPACING_SEC = 30


def _generate_fal_flux(prompt: str, out_path: Path,
                       model: str = FAL_FLUX_PRO,
                       target_w: int = 1080, target_h: int = 1920,
                       seed: int | None = None) -> bool:
    """Generate image via fal.ai FLUX 1.1-pro. PRIMARY (paid, premium quality).
    Returns True on success, False on failure (caller falls back to HF).

    seed: when set, locks the diffusion seed so the same character/appearance
    prompt renders a consistent face across scenes (character-bible feature)."""
    key = os.getenv("FAL_KEY")
    if not key:
        print("[image_gen][fal] FAL_KEY missing, skipping fal provider")
        return False
    try:
        import fal_client
    except ImportError:
        print("[image_gen][fal] fal_client not installed — pip install fal-client")
        return False
    # fal_client uses FAL_KEY env automatically
    # Pick closest supported aspect: portrait 9:16 vs landscape 16:9
    is_portrait = target_h > target_w
    image_size = "portrait_16_9" if is_portrait else "landscape_16_9"
    # schnell is a few-step distilled model (max 12 steps); pro/dev want ~28.
    steps = 8 if "schnell" in str(model).lower() else 28
    arguments = {
        "prompt": prompt,
        "image_size": image_size,
        "num_inference_steps": steps,
        "guidance_scale": 3.5,
        "num_images": 1,
        "enable_safety_checker": True,
        "output_format": "jpeg",
    }
    if seed is not None:
        arguments["seed"] = int(seed)
    try:
        result = fal_client.subscribe(
            model,
            arguments=arguments,
            with_logs=False,
        )
        url = result.get("images", [{}])[0].get("url")
        if not url:
            print(f"[image_gen][fal] no image url in response: {result}")
            return False
        r = requests.get(url, timeout=60)
        if r.status_code == 200 and len(r.content) > 5000:
            out_path.write_bytes(r.content)
            return True
        print(f"[image_gen][fal] download failed: HTTP {r.status_code}, {len(r.content)}B")
        return False
    except Exception as e:
        print(f"[image_gen][fal] error: {type(e).__name__}: {e}")
        return False


class GeminiUnavailable(RuntimeError):
    """Raised when all image providers fail after retries.
    Name kept for backward compat with run.py's catch logic."""


def _generate_hf_flux(prompt: str, out_path: Path, model: str = HF_DEFAULT_MODEL,
                      max_retries: int = 3) -> bool:
    """Generate image via HuggingFace FLUX schnell.
    Returns True on success, False on failure (caller handles fallback)."""
    token = os.getenv("HUGGINGFACE_TOKEN")
    if not token:
        print("[image_gen][hf] HUGGINGFACE_TOKEN missing, skipping HF provider")
        return False
    url = f"{HF_ROUTER_BASE}/{model}"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"inputs": prompt}
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=90)
            ctype = r.headers.get("content-type", "")
            if r.status_code == 200 and "image" in ctype:
                out_path.write_bytes(r.content)
                if out_path.stat().st_size > 5000:
                    return True
                print(f"[image_gen][hf] attempt {attempt}: tiny image ({out_path.stat().st_size}B)")
            elif r.status_code == 503:
                # Model cold-starting — wait + retry
                msg = r.text[:200] if r.text else "503 model loading"
                print(f"[image_gen][hf] attempt {attempt}: {msg}")
                time.sleep(20)  # cold start usually ~20-40s
            elif r.status_code == 429:
                # Rate limited — back off
                print(f"[image_gen][hf] attempt {attempt}: 429 rate-limited, backing off")
                time.sleep(25)
            else:
                print(f"[image_gen][hf] attempt {attempt}: HTTP {r.status_code} {r.text[:150]}")
                if attempt < max_retries:
                    time.sleep(5)
        except Exception as e:
            print(f"[image_gen][hf] attempt {attempt}: {e}")
            if attempt < max_retries:
                time.sleep(5)
    return False


def _generate_gemini(prompt: str, out_path: Path, model: str) -> bool:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise GeminiUnavailable("GEMINI_API_KEY missing in .env")

    url = f"{GEMINI_BASE}/{model}:generateContent?key={api_key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
    }
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.post(url, json=body, timeout=180)
            if r.status_code == 200:
                data = r.json()
                for part in data["candidates"][0]["content"]["parts"]:
                    if "inlineData" in part:
                        out_path.write_bytes(base64.b64decode(part["inlineData"]["data"]))
                        if out_path.stat().st_size > 5000:
                            return True
                last_err = "no inlineData in response"
                print(f"[image_gen][gemini] attempt {attempt}: {last_err}")
            elif r.status_code == 503:
                last_err = "503 UNAVAILABLE (Google high demand)"
                print(f"[image_gen][gemini] attempt {attempt}: {last_err}")
            else:
                last_err = f"HTTP {r.status_code} — {r.text[:200]}"
                print(f"[image_gen][gemini] attempt {attempt}: {last_err}")
        except Exception as e:
            last_err = str(e)
            print(f"[image_gen][gemini] attempt {attempt}: {e}")
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_SPACING_SEC)
    raise GeminiUnavailable(f"Gemini failed after {MAX_RETRIES} retries: {last_err}")


# ─────────────────────────────────────────────────────────────────────────
# CHARACTER CONSISTENCY (Level 2 — reference conditioning)
#
# Each scene image is normally an independent FLUX generation, so a recurring
# deity's face/design drifts across scenes within ONE video. The fix that
# actually works (used by strong AI-reel creators): generate ONE master
# portrait per recurring character, then render every scene that features that
# character via nano-banana-2/edit, passing the master(s) as reference images
# so the SAME identity is reused — only the pose/action/background change.
#
# Driven by the script's "character_bible": a list of recurring characters,
# each { "name": "...", "aliases": [...], "look": "..." }. A scene is
# reference-conditioned off whichever bible characters are named in its prompt.
# Multi-character scenes pass MULTIPLE references (nano-banana keeps each one).
# Scenes with no recurring character fall back to plain FLUX (establishing
# shots, crowds, landscapes) so they are never corrupted by a wrong reference.
# ─────────────────────────────────────────────────────────────────────────

def _detect_cast(prompt: str, bible: list[dict]) -> list[dict]:
    """Return bible characters whose name/alias appears in the scene prompt."""
    low = prompt.lower()
    hits = []
    for ch in bible:
        name = (ch.get("name") or "").strip()
        if not name:
            continue
        tokens = [name] + list(ch.get("aliases") or [])
        if any(t and t.lower() in low for t in tokens):
            hits.append(ch)
    return hits


def _build_character_masters(bible: list[dict], out_dir: Path, style: str,
                             negative: str, target_w: int, target_h: int,
                             fal_model: str = FAL_FLUX_PRO) -> dict[str, str]:
    """Generate (once, cached on disk) a master portrait per recurring character
    and upload it to fal. Returns {character_name: fal_url}. Masters use the
    SAME style_suffix as scenes so the reference matches the video's art style."""
    from .char_consistent import _fal_upload
    masters: dict[str, str] = {}
    for ch in bible:
        name = (ch.get("name") or "").strip()
        look = (ch.get("look") or "").strip()
        if not name or not look:
            continue
        mp = out_dir / f"master_{slugify(name)}.jpg"
        if not mp.exists():
            prompt = (
                f"Full-body single-character reference portrait of {look}. "
                f"Centered frontal hero pose, clean plain simple background, "
                f"dramatic divine lighting, intricate detail, masterpiece{style}. "
                f"Avoid: {negative}"
            )
            if not _generate_fal_flux(prompt, mp, model=fal_model, target_w=target_w, target_h=target_h):
                print(f"[consistency] master FAILED for {name} — scenes will use plain FLUX")
                continue
        url = _fal_upload(mp)
        if url:
            masters[name] = url
            print(f"[consistency] master ready → {name}")
    return masters


def generate_images(visual_prompts: list[str], out_dir: Path,
                    long_form: bool = False,
                    seeds: list[int | None] | None = None,
                    character_bible: list[dict] | None = None) -> list[Path]:
    """Generate scene images. For long-form (documentary), output 1920x1080
    horizontal. For Shorts, output 1080x1920 vertical (existing default).
    Post-processes each image to enforce target aspect (Gemini doesn't always
    honor the prompt orientation).

    seeds: optional per-image diffusion seeds (same length as visual_prompts).
    A scene featuring a recurring character should reuse that character's
    locked seed so the face stays consistent across scenes (character bible).
    Only the fal provider honors the seed; HF/Gemini fallbacks ignore it.
    """
    from PIL import Image
    cfg = load_config()
    style = cfg["images"]["style_suffix"]
    negative = cfg["images"]["negative"]
    cfg_model = cfg["images"].get("model", "gemini-3.1-flash-image-preview")
    # The fal model (e.g. fal-ai/flux/schnell). Falls back to flux-pro default.
    fal_model = cfg_model if str(cfg_model).startswith("fal-ai/") else FAL_FLUX_PRO
    # The Gemini last-resort needs a real Gemini image model — never the fal id.
    gemini_model = cfg["images"].get("gemini_image_model", "gemini-3.1-flash-image-preview")
    model = gemini_model if (str(cfg_model).startswith("fal-ai/") or "flux" in str(cfg_model).lower()) else cfg_model
    # Provider gate: only attempt the PAID fal.ai stack when images.provider == "fal".
    # Set provider to "huggingface" (free stack) to skip fal entirely — no wasted
    # failing calls, no character-master/nano-banana cost. Flip back to "fal" when
    # the fal balance is recharged.
    use_fal = str(cfg["images"].get("provider", "fal")).lower() == "fal"

    if long_form:
        # Override the cfg-supplied vertical hint with landscape orientation
        # Replace common vertical-orientation phrases in style suffix
        style_fixed = style
        for vert_phrase in ["vertical 9:16 portrait composition", "vertical 9:16 portrait",
                            "9:16 portrait", "vertical portrait", "(1080x1920)"]:
            style_fixed = style_fixed.replace(vert_phrase, "")
        orientation_hint = (
            " HORIZONTAL 16:9 LANDSCAPE composition (1920x1080), cinematic widescreen "
            "documentary frame, subject occupies left or center with environmental depth, "
            "wide establishing shot perspective."
        )
        style = style_fixed + orientation_hint
        target_w, target_h = 1920, 1080
        print(f"[image_gen] LONG-FORM mode → 1920x1080 horizontal landscape")
    else:
        target_w, target_h = 1080, 1920

    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[Path] = []
    fal_succeeded = 0
    hf_succeeded = 0
    gemini_succeeded = 0
    ref_succeeded = 0
    last_error = None

    # ── Character consistency: build a master portrait per recurring character.
    # Gated by config (images.consistency, default ON) + a usable bible. Skipped
    # for long-form (horizontal documentary) where recurring deities are rare.
    masters: dict[str, str] = {}
    bible = character_bible or []
    consistency_on = bool(cfg["images"].get("consistency", True)) and not long_form and bible and use_fal
    # Cost guard: only the most impactful scenes are reference-conditioned (each
    # costs a nano-banana edit). Default 3 hero shots/video — ~80% of the visual
    # consistency benefit at a fraction of the cost. 0 = unlimited.
    max_ref = int(cfg["images"].get("consistency_max_scenes", 3))
    ref_used = 0
    if consistency_on:
        masters = _build_character_masters(bible, out_dir, style, negative, target_w, target_h, fal_model=fal_model)
        if masters:
            cap = f"first {max_ref}" if max_ref else "all"
            print(f"[consistency] {len(masters)} character master(s) — reference-conditioning {cap} recurring scene(s)")

    for i, raw_prompt in enumerate(visual_prompts):
        prompt = f"{raw_prompt}{style}. Avoid: {negative}"
        path = out_dir / f"img_{i:02d}.jpg"
        seed = seeds[i] if seeds and i < len(seeds) else None

        # Reference-conditioning path: if this scene names recurring character(s)
        # we have a master for, render it via nano-banana/edit off those master(s)
        # so the identity stays locked. Falls through to FLUX on any failure.
        if masters and (max_ref == 0 or ref_used < max_ref):
            cast = _detect_cast(raw_prompt, bible)
            ref_urls = [masters[c["name"]] for c in cast if c.get("name") in masters]
            if ref_urls:
                from .char_consistent import generate_scene_with_reference
                names = " and ".join(c["name"] for c in cast if c.get("name") in masters)
                if generate_scene_with_reference(
                    ref_urls, raw_prompt, path,
                    char_name=names, art_style=style.lstrip(", ").strip(),
                    target_w=target_w, target_h=target_h,
                ):
                    ref_succeeded += 1
                    ref_used += 1
                    results.append(path)
                    continue
                print(f"[consistency] img {i}: reference edit failed → plain FLUX fallback")

        # Provider chain: fal.ai FLUX 1.1-pro (paid premium) → HF FLUX schnell (free) → Gemini (free)
        ok = False
        if use_fal and _generate_fal_flux(prompt, path, model=fal_model, target_w=target_w, target_h=target_h, seed=seed):
            ok = True
            fal_succeeded += 1
        elif _generate_hf_flux(prompt, path):
            print(f"[image_gen] img {i}: HF FLUX schnell succeeded")
            ok = True
            hf_succeeded += 1
        else:
            print(f"[image_gen] img {i}: fal + HF failed, trying Gemini last-resort...")
            try:
                if _generate_gemini(prompt, path, model):
                    ok = True
                    gemini_succeeded += 1
            except GeminiUnavailable as e:
                last_error = e
                print(f"[image_gen] img {i}: Gemini also failed: {e}")

        if ok:
            # Enforce target aspect ratio: resize+center-crop if provider gave wrong orientation
            try:
                img = Image.open(path)
                if img.size != (target_w, target_h):
                    img = _fit_to_aspect(img, target_w, target_h)
                    img.save(str(path), "JPEG", quality=92)
            except Exception as e:
                print(f"[image_gen] resize warning on img {i}: {e}")
            results.append(path)

    print(f"[image_gen] {len(results)}/{len(visual_prompts)} generated "
          f"(ref-consistent: {ref_succeeded}, fal: {fal_succeeded}, HF: {hf_succeeded}, "
          f"Gemini: {gemini_succeeded}) @ {target_w}x{target_h}")

    # If we got NOTHING and Gemini failed, raise so retry queue catches it
    if not results and last_error is not None:
        raise last_error
    if not results:
        raise GeminiUnavailable("All providers failed for every image")
    return results


def _fit_to_aspect(img, target_w: int, target_h: int):
    """Center-crop + resize image to exact target dimensions, preserving content."""
    from PIL import Image
    sw, sh = img.size
    target_aspect = target_w / target_h
    src_aspect = sw / sh
    if src_aspect > target_aspect:
        # Source is wider — crop sides
        new_w = int(sh * target_aspect)
        left = (sw - new_w) // 2
        img = img.crop((left, 0, left + new_w, sh))
    elif src_aspect < target_aspect:
        # Source is taller — crop top/bottom
        new_h = int(sw / target_aspect)
        top = (sh - new_h) // 2
        img = img.crop((0, top, sw, top + new_h))
    return img.resize((target_w, target_h), Image.LANCZOS)


# Public exception for run.py to catch
__all__ = ["generate_images", "GeminiUnavailable", "_generate_gemini"]
