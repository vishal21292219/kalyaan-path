#!/usr/bin/env python3
"""Post FB/IG reels whose scheduled time has arrived (decoupled from generation).

Why: Make's reel modules can't schedule, and video render time varies (10-45 min),
so "post at generation time" drifts off the target peak. Instead, the generation
run uploads to Cloudinary EARLY and queues a record here; this poster (run by
reel-poster.yml at the exact peak times) fires the Make webhook when due.

Guarantees:
  - No duplicates: each record posts once, then is REMOVED. As a SECOND, robust
    safety net we also keep a persistent posted-ledger keyed by video_url
    (data/state/posted_reels_log.json): once a video has been fired to the
    webhook it is NEVER fired again, even if removing it from the queue fails to
    commit/push (a git race between this poster and the generation run used to
    leave a posted record in the queue → the reel-poster cron re-fired it at
    every run = the same video posted to the Page over and over).
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
# Persistent "this video was already posted" ledger. Keyed by video_url (the
# Cloudinary URL is unique per render → a legitimate re-gen gets a NEW url and is
# never blocked, while a re-fire of the SAME url is always blocked). Survives
# even when the queue-dequeue commit loses a git race, so a posted reel can never
# be double-posted to the Page.
POSTED_LOG = ROOT / "data/state/posted_reels_log.json"
POSTED_KEEP_DAYS = 7
WEBHOOK = os.getenv("MAKE_REEL_WEBHOOK")


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(s):
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _load_posted() -> dict:
    """Ledger of already-posted video_urls → {posted_at}. Pruned to last N days."""
    try:
        data = json.loads(POSTED_LOG.read_text()) if POSTED_LOG.exists() else {}
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    cutoff = _now() - datetime.timedelta(days=POSTED_KEEP_DAYS)
    pruned, dropped = {}, 0
    for url, meta in data.items():
        ts = _parse((meta or {}).get("posted_at")) if isinstance(meta, dict) else None
        if ts is None or ts >= cutoff:
            pruned[url] = meta
        else:
            dropped += 1
    if dropped:
        print(f"[poster] pruned {dropped} ledger entries older than {POSTED_KEEP_DAYS}d")
    return pruned


def _save_posted(posted: dict) -> None:
    POSTED_LOG.parent.mkdir(parents=True, exist_ok=True)
    POSTED_LOG.write_text(json.dumps(posted, ensure_ascii=False, indent=1))


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

    posted_log = _load_posted()
    n = _now()
    grace = datetime.timedelta(minutes=2)
    stale_cut = n - datetime.timedelta(days=1)
    keep, posted, dropped, skipped = [], 0, 0, 0

    for r in recs:
        pa = _parse(r.get("post_at"))
        if pa is None:
            dropped += 1
            continue  # malformed → drop
        url = r.get("video_url")
        # Already fired this exact video before → never post it again (even if a
        # previous dequeue failed to commit). Drop it from the queue silently.
        if url and url in posted_log:
            skipped += 1
            print(f"[poster] SKIP already-posted {r.get('id')} ({r.get('channel')})")
            continue
        if pa > n + grace:
            keep.append(r)            # not due yet → keep
            continue
        # due now → try to post
        try:
            payload = {"video_url": url, "caption": r.get("caption", ""),
                       "channel": r.get("channel", "")}
            if r.get("fb_page_id"):
                payload["fb_page_id"] = r["fb_page_id"]
            resp = requests.post(WEBHOOK, json=payload, timeout=120)
            if resp.status_code in (200, 202):
                posted += 1
                # Record in the ledger BEFORE we drop it from the queue, so the
                # video is protected from re-firing even if the queue write/commit
                # is later lost. Persist immediately (crash-safe).
                if url:
                    posted_log[url] = {"posted_at": n.isoformat(), "id": r.get("id"),
                                       "channel": r.get("channel")}
                    _save_posted(posted_log)
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
    _save_posted(posted_log)
    print(f"[poster] posted={posted} skipped={skipped} dropped={dropped} remaining={len(keep)}")


if __name__ == "__main__":
    main()
