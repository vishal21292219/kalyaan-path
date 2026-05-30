"""Nightly pre-generation entry point.

Runs all pending slots for next N days (default 5).
Designed to run on GitHub Actions at 21:00 UTC (02:30 IST) when Gemini is idle.

Usage:
  python run_pregen.py            # next 5 days
  python run_pregen.py --days 3   # custom horizon
  python run_pregen.py --cleanup  # also sweep old consumed dirs
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

from pipeline import pregen
from pipeline.scheduler import list_pending


def _notify_telegram(summary: dict) -> None:
    """Send a one-line summary to Telegram (if creds present)."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat_id):
        return
    try:
        import requests
        lines = [
            f"🌙 *Nightly pregen complete*",
            f"_{datetime.now().strftime('%Y-%m-%d %H:%M IST')}_",
            f"",
            f"📊 Total: {summary['total']}  ✅ Ready: {summary['ready']}  ⏭️ Skipped: {summary['skipped']}  ❌ Failed: {summary['failed']}",
        ]
        # Group details by date for readability
        by_date = {}
        for d in summary.get("details", []):
            key = str(d.get("date", "?"))
            by_date.setdefault(key, []).append(d)
        for date_key in sorted(by_date.keys()):
            lines.append(f"\n*{date_key}:*")
            for d in by_date[date_key]:
                icon = {"ready": "✅", "skipped": "⏭️", "failed": "❌"}.get(d.get("status"), "❓")
                topic = d.get("topic", "?") or "?"
                lines.append(f"  {icon} {d['label']}: _{topic[:50]}_")
        msg = "\n".join(lines)
        # Telegram limits message to 4096 chars
        if len(msg) > 3900:
            msg = msg[:3900] + "\n…(truncated)"
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
            timeout=15,
        )
    except Exception:
        traceback.print_exc()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=2, help="How many days ahead to pre-gen (default 2)")
    ap.add_argument("--cleanup", action="store_true", help="Sweep consumed/old pregen dirs after run")
    ap.add_argument("--cleanup-older", type=int, default=7, help="Days to keep consumed pregen dirs")
    ap.add_argument("--dry-run", action="store_true", help="Just list pending, don't generate")
    args = ap.parse_args()

    print(f"== Nightly pregen ({datetime.now().isoformat(timespec='seconds')}) ==")
    pending = list_pending(args.days)
    print(f"[pregen] {len(pending)} pending slots for next {args.days} days")
    for p in pending:
        print(f"  - {p['label']} → {p['date']} ({p['status']})")

    if args.dry_run:
        print("[pregen] dry run — exiting")
        return 0

    if not pending:
        print("[pregen] nothing to do — all slots already pre-generated")
        if args.cleanup:
            removed = pregen.cleanup_consumed(args.cleanup_older)
            print(f"[cleanup] removed {removed} old entries/dirs")
        return 0

    summary = pregen.pregen_all_pending(days_ahead=args.days, sleep_between=5)
    print(f"\n=== SUMMARY ===")
    print(f"  Total:   {summary['total']}")
    print(f"  Ready:   {summary['ready']}")
    print(f"  Skipped: {summary['skipped']}")
    print(f"  Failed:  {summary['failed']}")

    if args.cleanup:
        removed = pregen.cleanup_consumed(args.cleanup_older)
        print(f"[cleanup] removed {removed} consumed/old entries")

    _notify_telegram(summary)

    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
