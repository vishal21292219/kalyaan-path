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
    secrets_path = ROOT / os.getenv(
        "YOUTUBE_CLIENT_SECRETS_FILE", "secrets/youtube_client_secret.json"
    )
    token_path = ROOT / os.getenv("YOUTUBE_TOKEN_FILE", "secrets/youtube_token.json")
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


def upload(video_path: Path, script: dict) -> str:
    cfg = load_config()
    privacy = cfg["publish"]["privacy"]
    hashtags = " ".join(cfg["branding"]["hashtags"])
    title = script.get("title") or "Daily Bhakti"
    if "#shorts" not in title.lower():
        title = (title[:90] + " #Shorts").strip()
    credit = cfg["branding"].get("music_credit", "")
    description = (
        f"{script.get('description', '')}\n\n"
        f"{cfg['branding']['cta']}\n\n"
        f"{credit}\n\n"
        f"{hashtags} {' '.join(script.get('hashtags', []))}"
    )
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": [h.lstrip("#") for h in script.get("hashtags", [])][:25],
            "categoryId": "22",  # People & Blogs
        },
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False},
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
    return url


if __name__ == "__main__":
    print("Run via run.py --publish")
