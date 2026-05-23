"""Image generation — multi-provider with auto-fallback.

Supported providers (cfg images.provider):
- "gemini"       — Google Gemini 3.1 Flash Image (Nano Banana 2). Best quality,
                   free tier 1500 req/day. Requires GEMINI_API_KEY in .env.
- "pollinations" — Free no-key tier via pollinations.ai. Lower quality but
                   unlimited.

Models for "gemini" provider:
- gemini-3.1-flash-image-preview  (Nano Banana 2 — default, free-tier friendly)
- nano-banana-pro-preview          (premium quality, lower free tier)
- imagen-4.0-generate-001          (paid only)

If the configured provider fails, falls through to pollinations as a safety net.
"""
from __future__ import annotations

import base64
import hashlib
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image

from .utils import load_config

load_dotenv()

POLLINATIONS_BASE = "https://image.pollinations.ai/prompt/"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


# ─── Gemini (Nano Banana) ────────────────────────────────────────────────
def _generate_gemini(prompt: str, out_path: Path, model: str) -> bool:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[image_gen] GEMINI_API_KEY missing — cannot use gemini provider")
        return False

    url = f"{GEMINI_BASE}/{model}:generateContent?key={api_key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
    }
    for attempt in range(3):
        try:
            r = requests.post(url, json=body, timeout=120)
            if r.status_code == 200:
                data = r.json()
                for part in data["candidates"][0]["content"]["parts"]:
                    if "inlineData" in part:
                        out_path.write_bytes(base64.b64decode(part["inlineData"]["data"]))
                        if out_path.stat().st_size > 5000:
                            return True
                # No image in response
                print(f"[image_gen][gemini] attempt {attempt+1}: no image in response")
            else:
                print(f"[image_gen][gemini] attempt {attempt+1}: HTTP {r.status_code} — {r.text[:200]}")
        except Exception as e:
            print(f"[image_gen][gemini] attempt {attempt+1}: {e}")
        time.sleep(2 ** attempt)
    return False


# ─── Pollinations (free, no key) ─────────────────────────────────────────
def _generate_pollinations(prompt: str, out_path: Path, width: int, height: int, model: str) -> bool:
    seed = int(hashlib.md5(prompt.encode()).hexdigest(), 16) % (10**9)
    full = requests.utils.quote(prompt, safe="")
    url = (
        f"{POLLINATIONS_BASE}{full}"
        f"?width={width}&height={height}&model={model}&seed={seed}&nologo=true&enhance=true"
    )
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=120)
            r.raise_for_status()
            out_path.write_bytes(r.content)
            if out_path.stat().st_size > 5000:
                return True
        except Exception as e:
            print(f"[image_gen][pollinations] attempt {attempt+1}: {e}")
            time.sleep(2 ** attempt)
    return False


# ─── Dispatcher ──────────────────────────────────────────────────────────
def _generate_one(prompt: str, out_path: Path, width: int, height: int, provider: str, model: str) -> bool:
    if provider == "gemini":
        if _generate_gemini(prompt, out_path, model):
            return True
        # Fall through to pollinations as safety
        print("[image_gen] gemini failed, falling back to pollinations (flux)")
        return _generate_pollinations(prompt, out_path, width, height, "flux-realism")
    return _generate_pollinations(prompt, out_path, width, height, model)


def generate_images(visual_prompts: list[str], out_dir: Path) -> list[Path]:
    cfg = load_config()
    style = cfg["images"]["style_suffix"]
    negative = cfg["images"]["negative"]
    provider = cfg["images"].get("provider", "pollinations")
    model = cfg["images"]["model"]
    w = cfg["video"]["width"]
    h = cfg["video"]["height"]

    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[Path] = []
    for i, raw_prompt in enumerate(visual_prompts):
        prompt = f"{raw_prompt}{style}. Avoid: {negative}"
        path = out_dir / f"img_{i:02d}.jpg"
        ok = _generate_one(prompt, path, w, h, provider, model)
        if ok:
            results.append(path)
        else:
            print(f"[image_gen] giving up on image {i}")
    if not results:
        raise RuntimeError(f"No images generated via provider={provider}")
    print(f"[image_gen] generated {len(results)}/{len(visual_prompts)} via {provider}")
    return results


if __name__ == "__main__":
    out = Path("output/images/demo")
    prompts = [
        "Lord Shiva meditating on Mount Kailash, snow peaks, sunrise",
        "Goddess Parvati in a forest, peacock nearby",
    ]
    print(generate_images(prompts, out))
