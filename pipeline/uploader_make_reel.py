"""Publish a reel to FB/IG via Cloudinary (public host) + a Make.com webhook.

Why this exists: the Meta dev-app token got flagged, so direct Graph-API posting
(uploader_facebook.py) fails. Make.com posts through ITS OWN Facebook app, which
sidesteps the flag. Flow:
    video.mp4 -> Cloudinary (signed upload -> public direct URL)
              -> POST {video_url, caption, channel} to MAKE_REEL_WEBHOOK
              -> Make scenario routes by `channel` to the right FB Page / IG.

Enable per niche with `publish.facebook_make: true`. Requires env (in .env):
  CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET, MAKE_REEL_WEBHOOK
Never raises into the caller — returns True/False (FB is a bonus, never blocks YT).
"""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

import requests

from dotenv import load_dotenv

load_dotenv()


def _caption(script: dict) -> str:
    hook = (script.get("hook") or "").strip()
    cta = (script.get("cta") or "").strip()
    tags = script.get("hashtags") or []
    tagline = " ".join(t if t.startswith("#") else f"#{t}" for t in tags)[:600]
    parts = [p for p in (hook, cta, tagline) if p]
    return "\n\n".join(parts)[:2000]


def _cloudinary_upload(video_path: Path, cloud: str, key: str, secret: str) -> str | None:
    ts = str(int(time.time()))
    folder = "reels"
    to_sign = f"folder={folder}&timestamp={ts}"
    sig = hashlib.sha1((to_sign + secret).encode()).hexdigest()
    with open(video_path, "rb") as f:
        r = requests.post(
            f"https://api.cloudinary.com/v1_1/{cloud}/video/upload",
            data={"api_key": key, "timestamp": ts, "folder": folder, "signature": sig},
            files={"file": (video_path.name, f, "video/mp4")},
            timeout=300,
        )
    if r.status_code != 200:
        print(f"[make-reel][cloudinary] HTTP {r.status_code}: {r.text[:200]}")
        return None
    return r.json().get("secure_url")


def upload(video_path, script: dict, channel: str) -> bool:
    """Upload video to Cloudinary + trigger the Make reel webhook. channel routes
    the Make scenario (e.g. 'gom' → Gods of the Mind FB page)."""
    cloud = os.getenv("CLOUDINARY_CLOUD_NAME")
    key = os.getenv("CLOUDINARY_API_KEY")
    secret = os.getenv("CLOUDINARY_API_SECRET")
    webhook = os.getenv("MAKE_REEL_WEBHOOK")
    if not all([cloud, key, secret, webhook]):
        print("[make-reel] missing CLOUDINARY_* or MAKE_REEL_WEBHOOK — skipping")
        return False
    video_path = Path(video_path)
    try:
        url = _cloudinary_upload(video_path, cloud, key, secret)
        if not url:
            return False
        print(f"[make-reel] cloudinary: {url}")
        r = requests.post(webhook, json={"video_url": url, "caption": _caption(script), "channel": channel}, timeout=120)
        ok = r.status_code in (200, 202)
        print(f"[make-reel] webhook ({channel}): {r.status_code} {r.text[:120]}")
        return ok
    except Exception as e:
        print(f"[make-reel] error: {type(e).__name__}: {e}")
        return False
