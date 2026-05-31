"""Catch-up safety net.

GitHub's scheduled crons are best-effort — they get delayed or DROPPED under
load, so a daily slot can silently not post. This script re-runs any of today's
scheduled slots that haven't been delivered yet (checked via the published_log
marker that run.py writes only on successful YouTube upload / Telegram drop).

Run it several times a day (see .github/workflows/catchup.yml). It is safe to
run repeatedly: a slot already delivered today is skipped.

Usage:
  python run_catchup.py            # recover any missed-and-due slots now
  python run_catchup.py --dry-run  # only print what WOULD be recovered
"""
from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

import run as runner
from pipeline.publish_log import was_published_today

# Each entry mirrors a cron in daily-reels.yml:
# (niche, kind, seed, mode, hour_utc, minute_utc, weekday)
#   mode: "publish" (auto-YT) or "telegram" (drop)
#   weekday: None = daily, else Python weekday (Mon=0 .. Sun=6)
# Saturday long-form is intentionally EXCLUDED (heavy/expensive; recover by hand).
SLOTS = [
    ("bhakti",  "mantra",   0, "publish",   1,  0, None),
    ("itihaas", "trending", 1, "telegram", 15, 30, None),
    ("itihaas", "series",   3, "telegram", 16,  0, None),
    ("ancient", "trending", 1, "publish",  17, 30, None),
    ("ancient", "trending", 2, "publish",  22, 30, None),
    ("bhajan",  "trending", 0, "publish",  13, 30, 6),  # Sunday only
]

# Only recover a slot once it's at least this many minutes past its scheduled
# time — gives the PRIMARY cron run time to finish + write its marker, so the
# catch-up never races it into a double-post.
BUFFER_MIN = 60


def _is_due(now: datetime, hour: int, minute: int, weekday) -> bool:
    if weekday is not None and now.weekday() != weekday:
        return False
    slot_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return (now - slot_dt).total_seconds() >= BUFFER_MIN * 60


def _argv(niche: str, kind: str, seed: int, mode: str) -> list[str]:
    a = ["--niche", niche, "--kind", kind, "--seed-offset", str(seed), "--auto-thumb"]
    if mode == "publish":
        a.append("--publish")
    else:
        a += ["--no-music", "--notify-telegram"]
    return a


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Only print what would be recovered")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    print(f"== Catch-up sweep ({now.isoformat(timespec='minutes')} UTC, weekday={now.weekday()}) ==")
    recovered = 0
    for niche, kind, seed, mode, hour, minute, weekday in SLOTS:
        label = f"{niche}/{kind} s{seed} [{mode}] @ {hour:02d}:{minute:02d}UTC"
        if not _is_due(now, hour, minute, weekday):
            continue
        if was_published_today(niche, kind, seed):
            print(f"  ✓ already delivered: {label}")
            continue
        print(f"  ⚠ MISSED → recovering: {label}")
        if args.dry_run:
            print(f"      (dry-run) would run: run.py {' '.join(_argv(niche, kind, seed, mode))}")
            recovered += 1
            continue
        try:
            rc = runner.main(_argv(niche, kind, seed, mode))
            print(f"      → rc={rc}")
            recovered += 1
        except Exception:
            traceback.print_exc()
            print(f"      → recovery FAILED for {label}")

    if recovered == 0:
        print("  all caught up — nothing missed ✓")
    else:
        print(f"  {'(dry-run) ' if args.dry_run else ''}handled {recovered} missed slot(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
