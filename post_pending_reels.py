#!/usr/bin/env python3
"""Post FB/IG reels whose scheduled time has arrived (decoupled from generation).

Why: Make's reel modules can't schedule, and video render time varies (10-45 min),
so "post at generation time" drifts off the target peak. Instead, the generation
run uploads to Cloudinary EARLY and queues a record here; this poster (run by
reel-poster.yml at the exact peak times) fires the Make webhook when due.

Guarantees:
  - No duplicates: each record posts once, then is REMOVED. Records are keyed by
    channel+date so a re-generation overwrites rather than duplicates.
  - Cleanup: posted records removed; stale records (>1 day past due) dropped.
Reads data/state/pending_reels.json. Needs MAKE_REEL_WEBHOOK in env.
"""
import json
import os
import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent
PENDING = ROOT / "data/state/pending_reels.json"
WEBHOOK = os.getenv("MAKE_REEL_WEBHOOK")


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(s):
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def main():
    if not WEBHOOK:
        print("[poster] MAKE_REEL_WEBHOOK not set — skipping")
        return
    if not PENDING.exists():
        print("[poster] no pending queue")
        return
    try:
        recs = json.loads(PENDING.read_text() or "[]")
    except Exception:
        print("[poster] pending file unreadable — resetting")
        recs = []

    n = _now()
    grace = datetime.timedelta(minutes=2)
    stale_cut = n - datetime.timedelta(days=1)
    keep, posted, dropped = [], 0, 0

    for r in recs:
        pa = _parse(r.get("post_at"))
        if pa is None:
            dropped += 1
            continue  # malformed → drop
        if pa > n + grace:
            keep.append(r)            # not due yet → keep
            continue
        # due now → try to post
        try:
            payload = {"video_url": r["video_url"], "caption": r.get("caption", ""),
                       "channel": r.get("channel", "")}
            if r.get("fb_page_id"):
                payload["fb_page_id"] = r["fb_page_id"]
            resp = requests.post(WEBHOOK, json=payload, timeout=120)
            if resp.status_code in (200, 202):
                posted += 1
                print(f"[poster] POSTED {r.get('id')} ({r.get('channel')}) @ {r.get('post_at')}")
                continue  # success → remove (don't keep)
            print(f"[poster] FAIL {r.get('id')}: {resp.status_code} {resp.text[:120]}")
        except Exception as e:
            print(f"[poster] ERR {r.get('id')}: {type(e).__name__}: {e}")
        # failed → retry next run, unless stale
        if pa > stale_cut:
            keep.append(r)
        else:
            dropped += 1
            print(f"[poster] DROP stale {r.get('id')}")

    PENDING.write_text(json.dumps(keep, ensure_ascii=False, indent=1))
    print(f"[poster] posted={posted} dropped={dropped} remaining={len(keep)}")


if __name__ == "__main__":
    main()
