"""Upload to YouTube Shorts via Data API v3.

One-time OAuth setup:
1. Go to https://console.cloud.google.com/, create project.
2. Enable "YouTube Data API v3".
3. Create OAuth Desktop credentials, download as
   secrets/youtube_client_secret.json
4. First run will open browser to authorize; token cached at
   secrets/youtube_token.json

Quota cost per upload: ~1600 units of the daily 10,000 unit quota
(6 uploads/day free).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .utils import ROOT, load_config

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def _get_service():
    cfg = load_config()
    secrets = cfg.get("secrets", {})
    secrets_path = ROOT / secrets.get("youtube_client_secret", "secrets/youtube_client_secret.json")
    token_path = ROOT / secrets.get("youtube_token", "secrets/youtube_token.json")
    token_path.parent.mkdir(parents=True, exist_ok=True)

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not secrets_path.exists():
                raise RuntimeError(
                    f"Missing YouTube client secret at {secrets_path}. "
                    "Create OAuth desktop credentials in Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json())
    return build("youtube", "v3", credentials=creds)


def upload(video_path: Path, script: dict, thumb_path: Path | None = None,
           publish_at: str | None = None) -> str:
    cfg = load_config()
    privacy = cfg["publish"]["privacy"]
    hashtags = " ".join(cfg["branding"]["hashtags"])
    title = script.get("title") or "Daily Bhakti"
    if "#shorts" not in title.lower():
        title = (title[:90] + " #Shorts").strip()
    credit = cfg["branding"].get("music_credit", "")
    # Friendly disclosure footer (helps trust signal + YT AI policy compliance)
    disclosure = cfg["branding"].get(
        "ai_disclosure",
        "🤖 Made with AI tools | Hand-curated by our team for authentic devotional/educational content."
    )
    # Optional per-niche promo (lead-magnet + paid product), high in the description.
    # Only niches whose config defines branding.promo carry it; else "" → no-op.
    promo = (cfg.get("branding", {}).get("promo") or "").strip()
    description = (
        f"{script.get('description', '')}\n\n"
        + (f"{promo}\n\n" if promo else "")
        + f"{cfg['branding']['cta']}\n\n"
        f"{credit}\n\n"
        f"{disclosure}\n\n"
        f"{hashtags} {' '.join(script.get('hashtags', []))}"
    )
    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}
    # Scheduled publish: upload PRIVATE now, YouTube flips it public EXACTLY at
    # publish_at (RFC3339 UTC). This decouples generation time (which GitHub crons
    # make late/unreliable) from go-live time (which becomes precise). publishAt
    # REQUIRES privacyStatus=private and a FUTURE timestamp.
    if publish_at:
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at
        print(f"[youtube] scheduling go-live at {publish_at} (uploading private)")
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": [h.lstrip("#") for h in script.get("hashtags", [])][:25],
            "categoryId": "22",  # People & Blogs
        },
        "status": status,
    }
    service = _get_service()
    media = MediaFileUpload(str(video_path), chunksize=-1, resumable=True, mimetype="video/mp4")
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"[youtube] upload {int(status.progress()*100)}%")
    video_id = response["id"]
    url = f"https://youtube.com/shorts/{video_id}"
    print(f"[youtube] published: {url}")

    # Set our CUSTOM thumbnail (dramatic image + bold text). Without this YouTube
    # auto-picks a random video frame. NOTE: custom thumbnails require the channel
    # to be phone-verified; if not, the API 403s and we keep the auto frame.
    if thumb_path and Path(thumb_path).exists():
        try:
            service.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumb_path), mimetype="image/jpeg"),
            ).execute()
            print(f"[youtube] custom thumbnail set ✓")
        except Exception as e:
            print(f"[youtube] thumbnail set failed ({type(e).__name__}: {str(e)[:120]}) "
                  f"— video live with auto-frame. (Channel may need phone verification.)")
    return url


if __name__ == "__main__":
    print("Run via run.py --publish")
