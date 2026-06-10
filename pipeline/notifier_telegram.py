"""Send generated video + thumbnail + metadata to Telegram for manual upload.

Setup:
1. Create a bot via @BotFather → get TELEGRAM_BOT_TOKEN
2. Send any message to the bot → get TELEGRAM_CHAT_ID from
   https://api.telegram.org/bot<TOKEN>/getUpdates
3. Add both to .env

Usage: python run.py --niche itihaas --notify-telegram
"""
from __future__ import annotations

import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

API = "https://api.telegram.org"


def _post(method: str, token: str, data: dict | None = None, files: dict | None = None) -> dict:
    r = requests.post(f"{API}/bot{token}/{method}", data=data, files=files, timeout=300)
    try:
        return r.json()
    except Exception:
        return {"ok": False, "raw": r.text[:200]}


def _send_text(token: str, chat_id: str, text: str) -> None:
    res = _post("sendMessage", token, data={"chat_id": chat_id, "text": text})
    if not res.get("ok"):
        print(f"[telegram] sendMessage failed: {res}")


def _send_code_block(token: str, chat_id: str, header: str, content: str) -> None:
    """Send content wrapped in <pre> tags for tap-to-copy on mobile."""
    # HTML parse mode = cleaner code blocks + no markdown escape pain
    # Escape HTML special chars in content
    safe = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = f"<b>{header}</b>\n\n<pre>{safe}</pre>"
    res = _post("sendMessage", token, data={
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    })
    if not res.get("ok"):
        print(f"[telegram] code block failed: {res}")


def notify(video_path: Path, thumbnail_path: Path | None, script: dict, niche: str,
           seed_offset: int = 0, note: str | None = None) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        print("[telegram] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set, skipping")
        return

    title = script.get("title", "")
    desc = script.get("description", "")
    hashtags = " ".join(script.get("hashtags", []))
    cta = script.get("cta", "")
    tags = ", ".join(h.lstrip("#") for h in script.get("hashtags", []))

    # Per-channel + per-seed scheduling hint (tomorrow's IST slot for user to set in YT Studio)
    channel_name = {
        "bhakti": "@KalyaanPath",
        "itihaas": "@Itihaasvani",
        "ancient": "@TimeDecoders",
        "godmind": "@GodsOfTheMind",
    }.get(niche, niche.title())

    schedule_map = {
        ("itihaas", 1): "TOMORROW 06:00 IST (morning commute audience)",
        ("itihaas", 2): "TOMORROW 13:00 IST (lunch-break browsing)",
        ("itihaas", 3): "TOMORROW 22:30 IST (late-night prime mythology hour)",
        ("bhakti", 0):  "TODAY 19:00 IST (sandhya pooja audience)",
        ("ancient", 1): "TOMORROW 23:30 IST (UK 7PM / EU 8PM prime)",
        ("ancient", 2): "TOMORROW 04:30 IST (US 7PM EST prime)",
    }
    slot_hint = schedule_map.get(
        (niche, seed_offset),
        "Best slot: 7-9 PM IST (peak)"
    )

    # 1. Header — clear YT channel + scheduled upload time so user can use YT Studio scheduler
    header = (
        f"🎬 *Upload-ready video* 🎬\n\n"
        f"📺 Channel: {channel_name}\n"
        f"⏰ Schedule for: {slot_hint}\n\n"
        f"📋 Title:\n{title}"
    )
    if note:
        header = f"{note}\n\n{header}"
    _send_text(token, chat_id, header)

    # 2. Video file — Telegram Bot API caps BOTH sendVideo AND sendDocument
    # at 50MB (not 2GB unless using local Bot API server). If file is over
    # the cap, re-encode to a smaller bitrate so the upload fits.
    size_mb = video_path.stat().st_size / 1024 / 1024
    send_path = video_path
    if size_mb > 48:
        import subprocess
        compressed = video_path.with_name(video_path.stem + "_tg.mp4")
        print(f"[telegram] {size_mb:.1f} MB > 48 MB Bot API cap — compressing to fit...")
        # Target ~2.0 Mbps video + 128 kbps audio ≈ fits 3 min in <45 MB
        proc = subprocess.run([
            "ffmpeg", "-y", "-i", str(video_path),
            "-c:v", "libx264", "-preset", "medium",
            "-b:v", "2000k", "-maxrate", "2400k", "-bufsize", "4M",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(compressed),
        ], capture_output=True)
        if proc.returncode == 0 and compressed.exists():
            send_path = compressed
            size_mb = send_path.stat().st_size / 1024 / 1024
            print(f"[telegram] compressed → {size_mb:.1f} MB")
        else:
            print(f"[telegram] compression failed: {proc.stderr[-300:]}")

    print(f"[telegram] sending video ({size_mb:.1f} MB)...")
    with open(send_path, "rb") as f:
        res = _post("sendVideo", token, data={
            "chat_id": chat_id,
            "caption": "📹 Video — save to phone",
            "supports_streaming": "true",
        }, files={"video": f})
    if not res.get("ok"):
        print(f"[telegram] sendVideo failed: {res}")

    # 3. Thumbnail
    if thumbnail_path and Path(thumbnail_path).exists():
        print(f"[telegram] sending thumbnail...")
        with open(thumbnail_path, "rb") as f:
            res = _post("sendDocument", token, data={
                "chat_id": chat_id,
                "caption": "🎨 Thumbnail — save to phone (sent as document for full quality)",
            }, files={"document": f})
            if not res.get("ok"):
                print(f"[telegram] sendDocument failed: {res}")

    # 4-7. Copy-paste blocks
    _send_code_block(token, chat_id, "📋 TITLE (tap to copy)", title)

    full_desc = f"{desc}\n\n{cta}\n\n{hashtags}".strip()
    _send_code_block(token, chat_id, "📄 DESCRIPTION (tap to copy)", full_desc)

    _send_code_block(token, chat_id, "🏷️ TAGS (tap to copy)", tags)

    pinned = f"{cta}\n\n💭 Comments mein apni राय zaroor batayein!"
    _send_code_block(token, chat_id, "💬 PINNED COMMENT (tap to copy)", pinned)

    # 8. Checklist
    checklist = (
        f"📋 UPLOAD CHECKLIST ({channel_name})\n\n"
        "1️⃣  Save video + thumbnail to phone\n"
        "2️⃣  YT app → Create a Short → upload video\n"
        "3️⃣  Add trending audio (15-20% volume) 🎵 algorithm boost\n"
        "4️⃣  Upload custom thumbnail\n"
        "5️⃣  Paste title + description + tags\n"
        "6️⃣  Audience = NOT made for kids ✅\n"
        f"7️⃣  {slot_hint}\n"
        "8️⃣  Pin the comment above after publish\n"
        "9️⃣  Reply to comments in first hour (algorithm boost window)"
    )
    _send_text(token, chat_id, checklist)

    print(f"[telegram] ✅ sent to chat {chat_id}")


if __name__ == "__main__":
    # Sanity check — sends a hello to confirm credentials
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat_id:
        _send_text(token, chat_id, "🤖 notifier_telegram.py reachable")
        print("Test message sent.")
    else:
        print("Missing credentials in .env")
