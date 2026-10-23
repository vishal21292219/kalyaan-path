#!/usr/bin/env python3
"""Build N reels and queue each for its own day's 19:00 UTC slot (00:30 IST).

--start is the UTC date: 19:00 UTC on --start is 00:30 IST on the NEXT
calendar day, so the reel for the 26 Oct (IST) slot needs --start 2026-10-25.

Runs run.py once per day-slot with --publish-at, so each reel takes the next
topic by min-seq and lands its own queue record. Nothing is posted here: the
poster cron fires each record at its exact time, and its per-page gap guard
stays the single posting authority.

    python scripts/batch_reels.py --count 10 --start 2026-10-23
"""
from __future__ import annotations
import argparse, json, subprocess, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--start", required=True)
    ap.add_argument("--hour", default="19:00", help="UTC HH:MM (19:00 = 00:30 IST next day)")
    a = ap.parse_args()

    hh, mm = (int(x) for x in a.hour.split(":"))
    d0 = datetime.strptime(a.start, "%Y-%m-%d").replace(
        hour=hh, minute=mm, tzinfo=timezone.utc)
    logs = ROOT / "output/batch_logs"; logs.mkdir(parents=True, exist_ok=True)
    done, failed = [], []

    for i in range(a.count):
        when = (d0 + timedelta(days=i)).isoformat(timespec="seconds").replace("+00:00", "Z")
        log = logs / f"reel_{i:02d}.log"
        print(f"\n[batch-reel] {i+1}/{a.count} → {when}", flush=True)
        t0 = time.time()
        with open(log, "w") as fh:
            rc = subprocess.run(
                [sys.executable, "-u", "run.py", "--niche", "godmind",
                 "--kind", "trending", "--seed-offset", "1", "--force",
                 # FULL RFC3339, not HH:MM: _publish_at_iso passes a complete
                 # timestamp through as-is, while a bare HH:MM resolves to the
                 # NEAREST occurrence — so every reel in the batch would land on
                 # the same day instead of one per day.
                 "--publish", "--publish-at", when],
                cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT,
                env={**__import__("os").environ, "ACTIVE_NICHE": "godmind",
                     "PUBLISH_AT_ISO": when}).returncode
        txt = log.read_text()
        title = next((l.split("title: ")[-1].strip() for l in txt.splitlines()
                      if "[script] title:" in l), "?")
        gate = [l for l in txt.splitlines() if "STILL FAILING" in l]
        cov = next((l for l in txt.splitlines() if "coverage" in l), "")
        queued = "QUEUED" in txt
        mins = (time.time() - t0) / 60
        status = "OK" if (rc == 0 and queued and not gate) else "CHECK"
        (done if status == "OK" else failed).append((when, title, status))
        print(f"[batch-reel]   {status}  {mins:.1f}m  queued={queued}  "
              f"gate_fails={len(gate)}  {title[:50]}", flush=True)
        for g in gate:
            print(f"[batch-reel]     ! {g.split('] ')[-1][:90]}", flush=True)
        if cov:
            print(f"[batch-reel]     {cov.split('] ')[-1][:60]}", flush=True)

    print(f"\n[batch-reel] clean {len(done)}, needs-check {len(failed)}")
    for w, t, s in failed:
        print(f"   {s}  {w}  {t[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
