"""Kling v3 hero-clip generation on fal.ai (image-to-video).

Used for the 1-2 "hero" shots of a reel (deity reveal, climax) where real
generative motion is worth the cost. The rest of the reel stays on cheap
ffmpeg Ken Burns stills. Cost (audio off): ~$0.084/sec → a 5s clip ≈ $0.42.

generate_hero_clip() takes a reference still (the scene image already produced
by the seed-locked image_gen step), uploads it to fal, and asks Kling v3 to
animate it with a motion prompt. Audio is generated separately by the pipeline
(edge-tts/ElevenLabs), so generate_audio is forced off to save money.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

KLING_I2V_MODEL = "fal-ai/kling-video/v3/standard/image-to-video"


def generate_hero_clip(
    prompt: str,
    ref_image: Path,
    out_path: Path,
    duration: int = 5,
    negative_prompt: str = "blur, distortion, low quality, extra limbs, deformed face, watermark, text",
    cfg_scale: float = 0.5,
) -> bool:
    """Animate a reference still into a short hero clip via Kling v3 I2V.

    prompt:     motion description (what moves/happens in the shot).
    ref_image:  local path to the scene still (must be >=300px, aspect 0.4-2.5).
    out_path:   where to write the resulting mp4.
    duration:   clip length in seconds (Kling allows 3-15; default 5).

    Returns True on success, False on failure. Never raises for provider
    errors — caller falls back to a Ken Burns still for that scene.
    """
    if not os.getenv("FAL_KEY"):
        print("[kling] FAL_KEY missing — skipping hero clip")
        return False
    if not ref_image.exists():
        print(f"[kling] reference image not found: {ref_image}")
        return False
    try:
        import fal_client
    except ImportError:
        print("[kling] fal_client not installed — pip install fal-client")
        return False

    duration = max(3, min(15, int(duration)))
    try:
        ref_url = fal_client.upload_file(str(ref_image))
    except Exception as e:
        print(f"[kling] reference upload failed: {type(e).__name__}: {e}")
        return False

    try:
        result = fal_client.subscribe(
            KLING_I2V_MODEL,
            arguments={
                "start_image_url": ref_url,
                "prompt": prompt,
                "duration": str(duration),
                "negative_prompt": negative_prompt,
                "cfg_scale": cfg_scale,
                "generate_audio": False,  # voice added later by pipeline — keeps cost at $0.084/sec
            },
            with_logs=False,
        )
    except Exception as e:
        print(f"[kling] generation failed: {type(e).__name__}: {e}")
        return False

    video = result.get("video") or {}
    url = video.get("url") if isinstance(video, dict) else None
    if not url:
        print(f"[kling] no video url in response: {result}")
        return False

    try:
        r = requests.get(url, timeout=180)
        if r.status_code == 200 and len(r.content) > 20000:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(r.content)
            print(f"[kling] hero clip saved → {out_path.name} ({len(r.content)//1024} KB, {duration}s)")
            return True
        print(f"[kling] download failed: HTTP {r.status_code}, {len(r.content)}B")
        return False
    except Exception as e:
        print(f"[kling] download error: {type(e).__name__}: {e}")
        return False
