#!/usr/bin/env python3
"""Lakeerein DAILY automation (run by GitHub Actions, also works locally).
Picks the day's viral-nostalgia topic (date-based rotation → cycles the whole
pool, no repeats for len(pool) days, no state file needed), generates a premium
video via make_video.py, and publishes to YT + IG + FB via publish_all.py —
scheduled for 8:30 PM IST (15:00 UTC).
  python daily_lakeerein.py [--dry-run]
"""
import json, sys, subprocess, datetime
from pathlib import Path

OUT = Path(__file__).parent
PY = sys.executable  # CI venv / local venv — whatever runs this
TOPICS = json.loads((OUT / "topics_lakeerein.json").read_text())["topics"]


def pick_topic():
    # Deterministic date-based rotation — cycles through the whole pool in order,
    # so each topic repeats only once every len(TOPICS) days. No state file.
    idx = datetime.date.today().toordinal() % len(TOPICS)
    return TOPICS[idx]


def publish_at_utc():
    """8:30 PM IST == 15:00 UTC. Schedule for today if still >5 min away, else
    tomorrow (so a late run never tries to schedule in the past)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    target = now.replace(hour=15, minute=0, second=0, microsecond=0)
    if now >= target - datetime.timedelta(minutes=5):
        target += datetime.timedelta(days=1)
    return target.strftime("%Y-%m-%dT%H:%M:%SZ")


def main(dry=False):
    topic = pick_topic()
    slug = "auto_" + datetime.date.today().strftime("%Y%m%d")
    pub = publish_at_utc()
    print(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] "
          f"topic={topic!r} slug={slug} publishAt={pub}")
    if dry:
        print("[lakeerein] DRY-RUN — skipped generation/publish")
        return
    subprocess.run([PY, str(OUT / "make_video.py"), topic, slug], check=True, cwd=str(OUT))
    subprocess.run([PY, str(OUT / "publish_all.py"), slug, pub], check=True, cwd=str(OUT))
    print("[lakeerein] DONE — scheduled YT+IG+FB for", pub)


if __name__ == "__main__":
    main("--dry-run" in sys.argv)
