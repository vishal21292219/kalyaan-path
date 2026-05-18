"""Image generation via pollinations.ai (free, no key) with retry + fallback."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import requests
from PIL import Image

from .utils import load_config

POLLINATIONS_BASE = "https://image.pollinations.ai/prompt/"


def _generate_one(prompt: str, out_path: Path, width: int, height: int, model: str) -> bool:
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
                # Keep the native Pollinations resolution (typically 576x1024).
                # The assembler upscales with lanczos + unsharp in ffmpeg,
                # which looks sharper than a PIL upscale here.
                return True
        except Exception as e:
            print(f"[image_gen] attempt {attempt+1} failed for '{prompt[:50]}...': {e}")
            time.sleep(2 ** attempt)
    return False


def generate_images(visual_prompts: list[str], out_dir: Path) -> list[Path]:
    cfg = load_config()
    style = cfg["images"]["style_suffix"]
    negative = cfg["images"]["negative"]
    model = cfg["images"]["model"]
    w = cfg["video"]["width"]
    h = cfg["video"]["height"]

    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[Path] = []
    for i, raw_prompt in enumerate(visual_prompts):
        prompt = f"{raw_prompt}{style}. Avoid: {negative}"
        path = out_dir / f"img_{i:02d}.jpg"
        ok = _generate_one(prompt, path, w, h, model)
        if ok:
            results.append(path)
        else:
            print(f"[image_gen] giving up on image {i}")
    if not results:
        raise RuntimeError("No images generated — pollinations.ai unreachable?")
    return results


if __name__ == "__main__":
    out = Path("output/images/demo")
    prompts = [
        "Lord Shiva meditating on Mount Kailash, snow peaks, sunrise",
        "Goddess Parvati in a forest, peacock nearby",
    ]
    print(generate_images(prompts, out))
