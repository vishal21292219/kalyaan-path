"""Telegram-control action handler (EXTRA feature — fully isolated from the
auto-post pipeline). Invoked only by .github/workflows/telegram-control.yml,
which is triggered by repository_dispatch from a Cloudflare Worker (never on a
schedule). Does NOT import or modify run.py / daily-reels / configs.

Commands: status | skip | ack  (generate/approve run run.py directly in the
workflow; this script handles state-only actions + Telegram replies).

Usage:
  python scripts/tg_action.py status  --channel itihaas
  python scripts/tg_action.py skip    --niche itihaas --kind series --seed 3
  python scripts/tg_action.py ack     --text "..."
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHANNEL_NAMES = {
    "bhakti": "KalyaanPath",
    "itihaas": "Itihaasvani",
    "ancient": "TimeDecoders",
}


def tg_send(text: str) -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("[tg] missing TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID")
        return
    data = json.dumps({
        "chat_id": chat, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data, headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=20)
        print("[tg] sent")
    except Exception as e:
        print(f"[tg] send failed: {e}")


def _published_log() -> dict:
    p = ROOT / "data/state/published_log.json"
    return json.loads(p.read_text()) if p.exists() else {}


def cmd_status(channel: str | None) -> None:
    log = _published_log()
    days = sorted(log.keys())[-3:]
    name = CHANNEL_NAMES.get(channel or "", "All channels")
    lines = [f"📊 <b>Status — {name}</b>", ""]
    pref = {"bhakti": "bhakti", "itihaas": "itihaas", "ancient": "ancient"}.get(channel or "")
    for d in days:
        slots = log.get(d, {})
        if pref:
            slots = {k: v for k, v in slots.items() if k.startswith(pref)}
        done = ", ".join(sorted(slots.keys())) if slots else "—"
        lines.append(f"<b>{d}</b>: {done}")
    # series + viral cursors for context
    if channel == "itihaas":
        sp = ROOT / "data/state/series_progress.json"
        if sp.exists():
            lines.append(f"\nseries cursor: {json.loads(sp.read_text()).get('cursor')}")
    lines.append("\n(slots: kind_sN ✓ = uploaded/scheduled that day)")
    tg_send("\n".join(lines))


def cmd_skip(niche: str, kind: str, seed: int) -> None:
    """Skip today's would-be pick so the next scheduled run chooses something
    else. For series: advance the cursor. For trending/viral: record today's
    pick into recency history so it's avoided. State files only — the workflow
    commits them. Never touches the schedule."""
    changed = []
    if kind == "series":
        sp = ROOT / "data/state/series_progress.json"
        st = json.loads(sp.read_text()) if sp.exists() else {"cursor": 0}
        st["cursor"] = int(st.get("cursor", 0)) + 1
        st["last_date"] = date.today().isoformat()
        sp.write_text(json.dumps(st, indent=2))
        changed.append(f"series cursor → {st['cursor']}")
    else:
        # mark current viral pick as used so recency skips it
        try:
            import sys
            sys.path.insert(0, str(ROOT))
            os.environ["ACTIVE_NICHE"] = niche
            from pipeline.topic_generator import pick_viral
            picked = pick_viral(seed_offset=seed)  # this records it in history
            if picked:
                changed.append(f"skipped viral topic: {picked.get('title')}")
        except Exception as e:
            changed.append(f"(viral skip noop: {type(e).__name__})")
    msg = f"⏭️ <b>Skipped</b> {CHANNEL_NAMES.get(niche, niche)} ({kind})\n" + "\n".join(changed)
    tg_send(msg)
    print(msg)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status"); s.add_argument("--channel", default=None)
    k = sub.add_parser("skip")
    k.add_argument("--niche", required=True); k.add_argument("--kind", default="trending")
    k.add_argument("--seed", type=int, default=1)
    a = sub.add_parser("ack"); a.add_argument("--text", required=True)
    args = ap.parse_args()

    if args.cmd == "status":
        cmd_status(args.channel)
    elif args.cmd == "skip":
        cmd_skip(args.niche, args.kind, args.seed)
    elif args.cmd == "ack":
        tg_send(args.text)


if __name__ == "__main__":
    main()
