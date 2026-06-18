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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

import run as runner
from pipeline.publish_log import last_published

# Each entry mirrors a GENERATION cron in daily-reels.yml:
# (niche, kind, seed, mode, hour_utc, minute_utc, weekday)
#   mode: "publish" (auto-YT) or "telegram" (drop)
#   weekday: None = daily, else Python weekday (Mon=0 .. Sun=6)
# Saturday long-form is intentionally EXCLUDED (heavy/expensive; recover by hand).
# hour/minute = the GENERATION cron time (UTC). run.py auto-schedules each
# publish slot's exact go-live via its PUBLISH_TIMES map, so recovered videos
# also get the right scheduled go-live — no need to pass it here.
#
# KEEP IN SYNC with the active crons in .github/workflows/daily-reels.yml. The
# GodsOfTheMind (godmind) slots are the busiest channel and MUST be covered here
# — a skipped GoM generation cron is otherwise unrecoverable.
SLOTS = [
    ("bhakti",  "mantra",   0, "publish",  15, 32, None),  # daily-reels.yml cron 32 15
    ("itihaas", "series",   3, "telegram", 16,  0, None),  # cron 0 16
    ("ancient", "trending", 1, "publish",  15, 37, None),  # cron 37 15
    ("ancient", "trending", 2, "publish",  16, 42, None),  # cron 42 16
    ("godmind", "trending", 1, "publish",  15,  0, None),  # cron 0 15  → go-live 17:00 UTC
    ("godmind", "trending", 2, "publish",  19,  0, None),  # cron 0 19  → go-live 21:00 UTC
    ("godmind", "trending", 3, "publish",  23,  0, None),  # cron 0 23  → go-live 01:00 UTC (next day)
    ("bhajan",  "trending", 0, "publish",  10,  0, 6),     # cron 0 10 Sun only
]

# Only recover a slot once it's at least this many minutes past its scheduled
# time — gives the PRIMARY cron run time to finish + write its marker, so the
# catch-up never races it into a double-post.
BUFFER_MIN = 60
# Stop trying to recover a slot once it's older than this — its NEXT day's cron
# (or the next catch-up sweep) owns it from here, and re-running a day-old slot
# would just publish stale content to a future go-live.
MAX_AGE_H = 20


def _due_occurrence(now: datetime, hour: int, minute: int, weekday):
    """Most recent occurrence of this slot's generation time, or None if it's
    not currently inside the recovery window [BUFFER_MIN, MAX_AGE_H].

    Crucially this looks BACK across the UTC midnight boundary: if the slot's
    gen time hasn't happened yet *today*, we consider *yesterday's* occurrence.
    That's how the godmind 23:00 slot stays recoverable by the 02:00 sweep."""
    occ = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if occ > now:
        occ -= timedelta(days=1)
    if weekday is not None and occ.weekday() != weekday:
        return None
    age = (now - occ).total_seconds()
    if age < BUFFER_MIN * 60 or age > MAX_AGE_H * 3600:
        return None
    return occ


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
        occ = _due_occurrence(now, hour, minute, weekday)
        if occ is None:
            continue
        # Delivered AT OR AFTER this occurrence → done (day-boundary safe: a
        # 23:00 slot delivered yesterday is matched against yesterday's occ).
        lp = last_published(niche, kind, seed)
        if lp is not None and lp >= occ:
            print(f"  ✓ already delivered: {label} (at {lp.isoformat(timespec='minutes')})")
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
