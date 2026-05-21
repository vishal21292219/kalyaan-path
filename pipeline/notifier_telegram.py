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


def notify(video_path: Path, thumbnail_path: Path | None, script: dict, niche: str) -> None:
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

    channel_name = {"bhakti": "KalyaanPath", "itihaas": "Itihaasvani"}.get(niche, niche.title())
    upload_slots = {
        "bhakti": "Best slots: 7 AM (morning aarti audience) or 7 PM (sandhya pooja)",
        "itihaas": "Best slots: 12 PM (lunch-break browsing) or 8 PM (mythology prime time)",
    }
    slot_hint = upload_slots.get(niche, "Best slot: 7-9 PM IST (peak)")

    # 1. Header
    _send_text(token, chat_id, f"🎬 {channel_name} — Upload Ready\n\n{title}\n\n⏰ {slot_hint}")

    # 2. Video file
    print(f"[telegram] sending video ({video_path.stat().st_size / 1024 / 1024:.1f} MB)...")
    with open(video_path, "rb") as f:
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
