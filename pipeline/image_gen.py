"""Image generation via Gemini Nano Banana 2 (primary, only).

Pollinations removed per user direction — Gemini-only stack now.

When Gemini fails (503 high-demand, timeout, etc.):
- 5 in-process retries with 30s spacing (covers brief Google hiccups)
- If all 5 fail → raise GeminiUnavailable so run.py can record the failure
  in retry_queue.json and exit cleanly. Hourly retry cron will pick it up.
"""
from __future__ import annotations

import base64
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from .utils import load_config

load_dotenv()

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
MAX_RETRIES = 5
RETRY_SPACING_SEC = 30


class GeminiUnavailable(RuntimeError):
    """Raised when Gemini image gen fails after all in-process retries."""


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


def generate_images(visual_prompts: list[str], out_dir: Path) -> list[Path]:
    cfg = load_config()
    style = cfg["images"]["style_suffix"]
    negative = cfg["images"]["negative"]
    model = cfg["images"].get("model", "gemini-3.1-flash-image-preview")

    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[Path] = []
    for i, raw_prompt in enumerate(visual_prompts):
        prompt = f"{raw_prompt}{style}. Avoid: {negative}"
        path = out_dir / f"img_{i:02d}.jpg"
        try:
            if _generate_gemini(prompt, path, model):
                results.append(path)
        except GeminiUnavailable:
            # Re-raise so run.py can save to retry queue + exit cleanly.
            # We DO NOT silently skip — partial videos look broken.
            raise
    print(f"[image_gen] generated {len(results)}/{len(visual_prompts)} via gemini")
    return results


# Public exception for run.py to catch
__all__ = ["generate_images", "GeminiUnavailable", "_generate_gemini"]
