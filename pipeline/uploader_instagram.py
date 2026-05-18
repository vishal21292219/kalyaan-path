"""Upload to Instagram Reels via Graph API.

Requirements:
- Instagram Business or Creator account, connected to a Facebook Page.
- Facebook App with `instagram_basic`, `instagram_content_publish`,
  `pages_read_engagement` permissions.
- Long-lived page access token in IG_ACCESS_TOKEN.
- IG_USER_ID = Instagram Business Account ID (numeric).

Instagram requires the video to be hosted on a public HTTPS URL. The easiest
free options:
- Push to a public GitHub repo + `https://raw.githubusercontent.com/...`
- Upload to a Cloudflare R2 / Backblaze B2 / Bunny Storage bucket
- For local testing: use ngrok to expose a local file server

This module accepts `public_url` directly. Set up hosting separately (see
README "Daily auto-publish" section).
"""
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from .utils import load_config

load_dotenv()

GRAPH = "https://graph.facebook.com/v19.0"


def upload(video_public_url: str, script: dict) -> str:
    ig_user = os.getenv("IG_USER_ID")
    token = os.getenv("IG_ACCESS_TOKEN")
    if not ig_user or not token:
        raise RuntimeError("IG_USER_ID and IG_ACCESS_TOKEN must be set in .env")

    cfg = load_config()
    caption = (
        f"{script.get('title','')}\n\n"
        f"{script.get('description','')}\n\n"
        f"{cfg['branding']['cta']}\n\n"
        f"{' '.join(cfg['branding']['hashtags'])} "
        f"{' '.join(script.get('hashtags', []))}"
    )[:2200]

    # 1. Create media container
    r = requests.post(
        f"{GRAPH}/{ig_user}/media",
        data={
            "media_type": "REELS",
            "video_url": video_public_url,
            "caption": caption,
            "share_to_feed": "true",
            "access_token": token,
        },
        timeout=30,
    )
    r.raise_for_status()
    creation_id = r.json()["id"]

    # 2. Poll until processed
    for _ in range(40):
        time.sleep(5)
        s = requests.get(
            f"{GRAPH}/{creation_id}",
            params={"fields": "status_code", "access_token": token},
            timeout=15,
        ).json()
        status = s.get("status_code")
        print(f"[instagram] container status: {status}")
        if status == "FINISHED":
            break
        if status == "ERROR":
            raise RuntimeError(f"IG processing error: {s}")
    else:
        raise RuntimeError("IG processing timed out")

    # 3. Publish
    pub = requests.post(
        f"{GRAPH}/{ig_user}/media_publish",
        data={"creation_id": creation_id, "access_token": token},
        timeout=30,
    )
    pub.raise_for_status()
    media_id = pub.json()["id"]
    print(f"[instagram] published media id: {media_id}")
    return media_id


if __name__ == "__main__":
    print("Pass a public video URL via run.py.")
