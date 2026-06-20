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


# Page display name per channel (for the "Follow X for more" CTA on FB/IG).
CHANNEL_NAME = {
    "godmind": "Gods of the Mind", "gom": "Gods of the Mind",
    "ancient": "Time Decoders", "bhakti": "Kalyaan Path",
    "bhajan": "Kalyaan Path", "itihaas": "Itihaasvani",
    "moneurons": "Money Neurons",
}
def _caption(script: dict, channel: str = "") -> str:
    hook = (script.get("hook") or "").strip()
    cta = (script.get("cta") or "").strip()
    name = CHANNEL_NAME.get(channel, "")
    follow = f"👉 Follow {name} for more." if name else ""
    tags = script.get("hashtags") or []
    tagline = " ".join(t if t.startswith("#") else f"#{t}" for t in tags)[:600]
    parts = [p for p in (hook, cta, follow, tagline) if p]
    return "\n\n".join(parts)[:2000]


def _prune_old(cloud: str, key: str, secret: str, prefix: str = "reels/", days: int = 2) -> None:
    """Delete Cloudinary video assets older than `days` (FB/IG already ingested
    them within minutes). Keeps the free tier from filling. Best-effort/non-fatal."""
    import datetime
    try:
        r = requests.get(
            f"https://api.cloudinary.com/v1_1/{cloud}/resources/video/upload",
            params={"prefix": prefix, "max_results": 100}, auth=(key, secret), timeout=30,
        )
        if r.status_code != 200:
            return
        cutoff = time.time() - days * 86400
        old = []
        for res in r.json().get("resources", []):
            try:
                t = datetime.datetime.fromisoformat(res.get("created_at", "").replace("Z", "+00:00")).timestamp()
            except Exception:
                continue
            if t < cutoff:
                old.append(res["public_id"])
        if old:
            requests.delete(
                f"https://api.cloudinary.com/v1_1/{cloud}/resources/video/upload",
                params=[("public_ids[]", p) for p in old], auth=(key, secret), timeout=60,
            )
            print(f"[make-reel] pruned {len(old)} Cloudinary reels older than {days}d")
    except Exception as e:
        print(f"[make-reel] prune skipped: {e}")


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


_PENDING = Path(__file__).resolve().parent.parent / "data/state/pending_reels.json"


def _enqueue(video_url: str, script: dict, channel: str, fb_page_id: str, post_at: str) -> bool:
    """Queue the reel to be posted at post_at by post_pending_reels.py (the poster
    cron). Keyed by channel+post_at so each daily drop is a DISTINCT record (a
    multi-drop channel like GoM has 3 different post_at times) — only a re-gen of
    the SAME slot overwrites (dedup), never a different drop."""
    import json
    _PENDING.parent.mkdir(parents=True, exist_ok=True)
    try:
        recs = json.loads(_PENDING.read_text()) if _PENDING.exists() else []
    except Exception:
        recs = []
    rid = f"{channel}_{post_at}"
    recs = [r for r in recs if r.get("id") != rid]  # dedup → one per slot (channel+time)
    recs.append({"id": rid, "video_url": video_url, "caption": _caption(script, channel),
                 "channel": channel, "fb_page_id": (fb_page_id or "").strip(), "post_at": post_at})
    _PENDING.write_text(json.dumps(recs, ensure_ascii=False, indent=1))
    print(f"[make-reel] QUEUED {rid} for {post_at} → pending_reels.json")
    return True


def upload(video_path, script: dict, channel: str, fb_page_id: str | None = None,
           post_at: str | None = None) -> bool:
    """Upload video to Cloudinary, then either POST the Make webhook now (post_at
    None) or QUEUE it for post_at (the poster cron fires it at that exact time —
    decouples posting from render time). fb_page_id selects the bhakti-family FB
    page; without it the scenario posts to Lakeerein IG+FB."""
    cloud = os.getenv("CLOUDINARY_CLOUD_NAME")
    key = os.getenv("CLOUDINARY_API_KEY")
    secret = os.getenv("CLOUDINARY_API_SECRET")
    webhook = os.getenv("MAKE_REEL_WEBHOOK")
    if not all([cloud, key, secret, webhook]):
        print("[make-reel] missing CLOUDINARY_* or MAKE_REEL_WEBHOOK — skipping")
        return False
    if fb_page_id is not None and not str(fb_page_id).strip():
        print(f"[make-reel] no FB page id for channel '{channel}' — skipping (set FB_PAGE_ID_<NICHE>)")
        return False
    video_path = Path(video_path)
    try:
        _prune_old(cloud, key, secret, prefix="reels/", days=2)
        url = _cloudinary_upload(video_path, cloud, key, secret)
        if not url:
            return False
        print(f"[make-reel] cloudinary: {url}")
        if post_at:                       # scheduled → queue for the poster cron
            return _enqueue(url, script, channel, fb_page_id, post_at)
        payload = {"video_url": url, "caption": _caption(script, channel), "channel": channel}
        if fb_page_id:
            payload["fb_page_id"] = str(fb_page_id).strip()
        r = requests.post(webhook, json=payload, timeout=120)
        ok = r.status_code in (200, 202)
        print(f"[make-reel] webhook ({channel}, page={fb_page_id}): {r.status_code} {r.text[:120]}")
        return ok
    except Exception as e:
        print(f"[make-reel] error: {type(e).__name__}: {e}")
        return False
