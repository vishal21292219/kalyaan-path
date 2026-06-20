"""Discord notifications — Telegram replacement (Telegram banned in India).

Setup (one-time):
  Discord server → pick/create a channel (e.g. #reels-alerts) → channel
  Settings → Integrations → Webhooks → New Webhook → Copy Webhook URL.
  Put it in env as DISCORD_WEBHOOK (and as a GitHub secret for the cloud runs).

Used for run alerts (success / failure) and the GoM manual-review notify. The big
mp4 is NOT uploaded (Discord webhooks cap uploads ~8 MB) — only the thumbnail +
title/hook/metadata, which is all you need for an alert.
"""
from __future__ import annotations

import os
from pathlib import Path

import requests


def _webhook() -> str | None:
    return (os.getenv("DISCORD_WEBHOOK") or "").strip() or None


def alert(text: str) -> bool:
    """Post a plain text alert to the Discord channel. No-op (returns False) if
    DISCORD_WEBHOOK is not set, so it never breaks a pipeline run."""
    hook = _webhook()
    if not hook:
        return False
    try:
        r = requests.post(hook, json={"content": text[:1900]}, timeout=30)
        ok = r.status_code in (200, 204)
        if not ok:
            print(f"[discord] alert failed: {r.status_code} {r.text[:120]}")
        return ok
    except Exception as e:
        print(f"[discord] alert error: {type(e).__name__}: {e}")
        return False


def notify(video_path, thumbnail_path, script, niche: str,
           seed_offset: int = 0, note: str | None = None,
           schedule_iso: str | None = None, **kwargs) -> bool:
    """Telegram-compatible signature so run.py can call it interchangeably.
    Posts title/hook/metadata + the thumbnail image (if < 8 MB)."""
    hook = _webhook()
    if not hook:
        print("[discord] DISCORD_WEBHOOK not set, skipping")
        return False
    s = script or {}
    title = s.get("title", "(untitled)")
    hookline = s.get("hook", "")
    lines = [f"🎬 **{niche}** s{seed_offset} — {title}"]
    if hookline:
        lines.append(f"> {hookline}")
    if schedule_iso:
        lines.append(f"🕒 go-live: {schedule_iso}")
    if note:
        lines.append(note)
    vp = Path(video_path) if video_path else None
    if vp:
        lines.append(f"📄 {vp.name}")
    content = "\n".join(lines)[:1900]

    tp = Path(thumbnail_path) if thumbnail_path else None
    try:
        if tp and tp.exists() and tp.stat().st_size < 8_000_000:
            with open(tp, "rb") as f:
                files = {"file": (tp.name, f.read())}
            r = requests.post(hook, data={"content": content}, files=files, timeout=60)
        else:
            r = requests.post(hook, json={"content": content}, timeout=30)
        ok = r.status_code in (200, 204)
        if not ok:
            print(f"[discord] notify failed: {r.status_code} {r.text[:120]}")
        return ok
    except Exception as e:
        print(f"[discord] notify error: {type(e).__name__}: {e}")
        return False
