"""Publish a vertical Short to a Facebook Page as a REEL via the Graph API.

Uses the Page Reels API (3-phase resumable upload):
  1. start   -> POST /{page_id}/video_reels  (upload_phase=start) -> video_id + upload_url
  2. upload  -> POST upload_url               (binary, Authorization: OAuth <page_token>)
  3. finish  -> POST /{page_id}/video_reels  (upload_phase=finish, video_state=PUBLISHED)

Credentials (GitHub secrets / .env), NO app review needed for your own Page in
Development mode because you're a Page admin with the CREATE_CONTENT task.
Per-niche secrets (preferred), with a generic fallback so old configs keep working:
  FB_PAGE_ID_<NICHE>    e.g. FB_PAGE_ID_GODMIND, FB_PAGE_ID_ANCIENT
  FB_PAGE_TOKEN_<NICHE> e.g. FB_PAGE_TOKEN_GODMIND, FB_PAGE_TOKEN_ANCIENT
  FB_PAGE_ID / FB_PAGE_TOKEN   (generic fallback — currently the GodsOfTheMind page)
The token is a long-lived (non-expiring) Page access token with
pages_manage_posts + pages_read_engagement + pages_show_list.

Returns the reel URL on success, or None on any failure (never raises — Facebook
is a bonus channel and must never break the YouTube publish).
"""
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

from .utils import load_config

load_dotenv()

GRAPH_VERSION = "v21.0"
GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"


def _caption(script: dict, cfg: dict) -> str:
    """Build the reel caption from the script + branding hashtags (≤2200 chars)."""
    title = (script.get("title") or "").strip()
    desc = (script.get("description") or "").strip()
    brand_tags = " ".join(cfg.get("branding", {}).get("hashtags", []))
    script_tags = " ".join(script.get("hashtags", []))
    parts = [p for p in (title, desc, f"{brand_tags} {script_tags}".strip()) if p]
    return "\n\n".join(parts)[:2200]


def _creds(cfg: dict):
    """Per-niche FB page creds with generic fallback. Returns (page_id, token)."""
    niche = (cfg.get("niche") or "").upper()
    token = os.environ.get(f"FB_PAGE_TOKEN_{niche}") or os.environ.get("FB_PAGE_TOKEN")
    page_id = os.environ.get(f"FB_PAGE_ID_{niche}") or os.environ.get("FB_PAGE_ID")
    return page_id, token


def _scheduled_ts(publish_at_iso: str | None) -> int | None:
    """If publish_at_iso is a FAR-future timestamp (>6h ahead), return its unix ts so
    the reel can be SCHEDULED on Facebook to match YouTube's go-live (e.g. a 15-Jun
    Jayanti drop). Near-future daily slots (<6h) keep posting immediately — unchanged."""
    if not publish_at_iso:
        return None
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(publish_at_iso.replace("Z", "+00:00"))
        if (dt - datetime.now(timezone.utc)).total_seconds() > 6 * 3600:
            return int(dt.timestamp())
    except Exception as e:
        print(f"[facebook] bad publish_at {publish_at_iso!r} ({e}) — posting immediately")
    return None


def upload(video_path, script: dict, cfg: dict | None = None,
           publish_at_iso: str | None = None) -> str | None:
    cfg = cfg or load_config()
    page_id, token = _creds(cfg)
    if not token or not page_id:
        print("[facebook] FB_PAGE_TOKEN/FB_PAGE_ID not set for this niche — skipping Facebook")
        return None

    video_path = Path(video_path)
    if not video_path.exists():
        print(f"[facebook] video missing: {video_path} — skipping")
        return None
    size = video_path.stat().st_size
    sched_ts = _scheduled_ts(publish_at_iso)

    try:
        # 1. START — reserve a video container + get the rupload URL.
        start = requests.post(
            f"{GRAPH}/{page_id}/video_reels",
            data={"upload_phase": "start", "access_token": token},
            timeout=60,
        ).json()
        vid = start.get("video_id")
        upload_url = start.get("upload_url")
        if not vid or not upload_url:
            print(f"[facebook] start failed: {start}")
            return None

        # 2. UPLOAD — stream the file bytes to the rupload endpoint.
        with open(video_path, "rb") as f:
            resp = requests.post(
                upload_url,
                headers={
                    "Authorization": f"OAuth {token}",
                    "offset": "0",
                    "file_size": str(size),
                },
                data=f,
                timeout=600,
            )
        if resp.status_code != 200 or not resp.json().get("success", True):
            print(f"[facebook] binary upload failed: {resp.status_code} {resp.text[:300]}")
            return None

        # 3. FINISH — publish now, or SCHEDULE for a far-future go-live (matches YT).
        finish_data = {
            "upload_phase": "finish",
            "video_id": vid,
            "description": _caption(script, cfg),
            "access_token": token,
        }
        if sched_ts:
            finish_data["video_state"] = "SCHEDULED"
            finish_data["scheduled_publish_time"] = sched_ts
            print(f"[facebook] scheduling reel go-live at unix {sched_ts}")
        else:
            finish_data["video_state"] = "PUBLISHED"
        finish = requests.post(
            f"{GRAPH}/{page_id}/video_reels", data=finish_data, timeout=120,
        ).json()
        if not finish.get("success"):
            # Some accounts return {"success":true} only after processing; treat a
            # missing-but-no-error response as soft-OK and still return the URL.
            if finish.get("error"):
                print(f"[facebook] finish failed: {finish}")
                return None

        url = f"https://www.facebook.com/reel/{vid}"
        print(f"[facebook] reel published: {url}")
        return url
    except Exception as e:
        print(f"[facebook] upload error (non-fatal): {e}")
        return None
