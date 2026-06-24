"""Discord notifications — Telegram replacement (Telegram banned in India).

Setup (one-time):
  Discord server → channel → Settings → Integrations → Webhooks → New Webhook →
  Copy URL → env DISCORD_WEBHOOK (+ GitHub secret for cloud runs).

Messages are sent as RICH EMBEDS (colour-coded, with a clear title, per-platform
status, and clickable links) so a glance tells you: which channel, which platform
(YouTube / Facebook / Instagram), what posted, what failed, and the link.
  • report()  — a reel was delivered (success/partial) — the main per-reel card.
  • alert()   — a plain status/error line (crash, retry, watchdog) — colour from
                the leading emoji (❌ red / ⚠️ yellow / ✅ green / else blue).
Never raises into a pipeline run (returns False if DISCORD_WEBHOOK unset).
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import requests

GREEN, YELLOW, RED, BLUE = 0x2ECC71, 0xF1C40F, 0xE74C3C, 0x3498DB

# niche → (display name, emoji) so the card says the real channel, not "godmind".
CHANNEL = {
    "godmind": ("Gods of the Mind", "🧠"), "gom": ("Gods of the Mind", "🧠"),
    "ancient": ("TimeDecoders", "⏳"),
    "moneurons": ("Money Neurons", "💰"),
    "bhakti": ("Kalyaan Path", "🕉️"), "bhajan": ("Kalyaan Path", "🕉️"),
    "itihaas": ("Itihaasvani", "📜"),
    "lakeerein": ("Lakeerein", "✍️"),
}


def _webhook() -> str | None:
    return (os.getenv("DISCORD_WEBHOOK") or "").strip() or None


def _send_embed(embed: dict) -> bool:
    hook = _webhook()
    if not hook:
        return False
    try:
        r = requests.post(hook, json={"embeds": [embed]}, timeout=30)
        ok = r.status_code in (200, 204)
        if not ok:
            print(f"[discord] embed failed: {r.status_code} {r.text[:120]}")
        return ok
    except Exception as e:
        print(f"[discord] embed error: {type(e).__name__}: {e}")
        return False


def report(niche: str, seed_offset, script: dict, platforms: dict | None = None,
           schedule_iso: str | None = None) -> bool:
    """The per-reel card. `platforms` maps each platform to its outcome:
      youtube  : "<url>" | "failed"
      facebook : ("queued", "<iso>") | "posted" | "<url>" | "failed"
      instagram: "posted" | "failed"
    Builds one colour-coded embed: channel header + a field per platform with a
    clear status and a clickable link, plus the topic + hook."""
    if not _webhook():
        return False
    platforms = platforms or {}
    name, emoji = CHANNEL.get(niche, (niche, "🎬"))
    s = script or {}
    title = (s.get("title") or "(untitled)").strip()
    hookline = (s.get("hook") or "").strip()

    fields, any_fail = [], False

    if "youtube" in platforms:
        v = platforms["youtube"]
        if isinstance(v, str) and v.startswith("http"):
            val = f"[▶ Watch on YouTube]({v})"
        else:
            val, any_fail = "❌ Upload failed", True
        fields.append({"name": "📺 YouTube", "value": val, "inline": True})

    if "facebook" in platforms:
        v = platforms["facebook"]
        if isinstance(v, (list, tuple)) and v and v[0] == "queued":
            t = (str(v[1]) if len(v) > 1 and v[1] else "")[11:16]
            val = f"⏳ Scheduled — posts ~{t} UTC" if t else "⏳ Scheduled for peak"
        elif isinstance(v, str) and v.startswith("http"):
            val = f"[▶ Open on Facebook]({v})"
        elif v == "posted":
            val = "✅ Posted"
        else:
            val, any_fail = "❌ Failed", True
        fields.append({"name": "📘 Facebook", "value": val, "inline": True})

    if "instagram" in platforms:
        v = platforms["instagram"]
        if v == "posted":
            val = "✅ Posted"
        else:
            val, any_fail = "❌ Failed", True
        fields.append({"name": "📸 Instagram", "value": val, "inline": True})

    desc = f"**{title}**"
    if hookline:
        desc += f"\n> {hookline[:180]}"

    status = "⚠️ Posted (one platform had an issue)" if any_fail else "✅ New reel posted"
    embed = {
        "title": f"{emoji} {name} — {status}",
        "description": desc[:1500],
        "color": YELLOW if any_fail else GREEN,
        "fields": fields or [{"name": "Status", "value": "✅ Delivered", "inline": True}],
        "footer": {"text": f"slot s{seed_offset} · {datetime.now(timezone.utc):%b %d, %H:%M} UTC"},
    }
    return _send_embed(embed)


def alert(text: str) -> bool:
    """Plain status/error line as a colour-coded embed (colour from leading emoji).
    Kept for crash / retry / watchdog / poster alerts. No-op if webhook unset."""
    if not _webhook():
        return False
    t = (text or "").strip()
    color, head = BLUE, "ℹ️ Pipeline"
    if t.startswith("❌"):
        color, head = RED, "❌ Pipeline Error"
    elif t.startswith("⚠️"):
        color, head = YELLOW, "⚠️ Pipeline Warning"
    elif t.startswith("✅") or t.startswith("🟢"):
        color, head = GREEN, "✅ Pipeline OK"
    return _send_embed({"title": head, "description": t[:1900], "color": color})


def notify(video_path, thumbnail_path, script, niche: str,
           seed_offset: int = 0, note: str | None = None,
           schedule_iso: str | None = None, **kwargs) -> bool:
    """Telegram-compatible signature (manual-review drop). Sends the card via
    report() + the thumbnail image if present (< 8 MB)."""
    if not _webhook():
        print("[discord] DISCORD_WEBHOOK not set, skipping")
        return False
    plats = {}
    if schedule_iso:
        plats["facebook"] = ("queued", schedule_iso)
    report(niche, seed_offset, script, plats, schedule_iso)
    tp = Path(thumbnail_path) if thumbnail_path else None
    if tp and tp.exists() and tp.stat().st_size < 8_000_000:
        try:
            with open(tp, "rb") as f:
                requests.post(_webhook(), data={"content": (note or "")[:200]},
                              files={"file": (tp.name, f.read())}, timeout=60)
        except Exception as e:
            print(f"[discord] thumb send error: {type(e).__name__}: {e}")
    return True
