#!/usr/bin/env python3
"""Generate the next photo post and QUEUE it for its peak. Cron entry point.

Render and publish stay separate: this builds the image, gates it, and drops a
record into data/state/pending_reels.json with a post_at. post_pending_reels.py
fires it at that exact time — the same poster, ledger, dedup, past-peak drop and
MIN_GAP_HOURS spacing the reel lane already has.

    python scripts/run_photo_post.py --post-at 17:00
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import photo_post                                   # noqa: E402
from pipeline.uploader_make_reel import upload_photo              # noqa: E402
from pipeline.utils import load_config                            # noqa: E402

# First comment. Comment velocity is a top FB reach signal, and the photo lane
# gets the same treatment the reels already had.
COMMENT = ("🕉️ Which part of this is you right now? Tell me honestly — "
           "I read and reply to every comment. 👇")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--post-at", default="17:00", help="UTC HH:MM for the peak")
    ap.add_argument("--now", action="store_true", help="post immediately instead of queueing")
    args = ap.parse_args()

    niche = load_config().get("niche") or "godmind"
    pool_path = ROOT / f"data/photo_lines_{niche}.json"
    pool = json.loads(pool_path.read_text()) if pool_path.exists() else []

    item = next((i for i in pool if not i.get("posted_at")), None)
    if not item:
        print("[photo-cron] pool exhausted — run make_photo_post.py --refill N")
        return 1

    # build() RAISES if the frame fails the vision gate. That is deliberate: a
    # photo post is a single frame posted on its own, so there is nothing to
    # salvage and a bad one is worse than a missed slot.
    res = photo_post.build(item, ROOT / "output/photo")
    print(f"[photo-cron] built {res['image']}")

    cfg = load_config()
    page_id = (str((cfg.get("publish", {}) or {}).get("fb_page_id") or "").strip()
               or (os.getenv(f"FB_PAGE_ID_{niche.upper()}") or "").strip())
    if not page_id:
        print(f"[photo-cron] no publish.fb_page_id and no FB_PAGE_ID_{niche.upper()} — refusing "
              f"(a missing page id does not fail, it posts to the WRONG PAGE)")
        return 1

    post_at = None
    if not args.now:
        hh, mm = (int(x) for x in args.post_at.split(":"))
        now = datetime.now(timezone.utc)
        t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if t <= now:
            t += timedelta(days=1)
        post_at = t.isoformat(timespec="seconds").replace("+00:00", "Z")

    ok = upload_photo(res["image"], res["caption"], niche, page_id,
                      comment=COMMENT, post_at=post_at)
    if not ok:
        return 1

    item["posted_at"] = (post_at or datetime.now(timezone.utc)
                         .isoformat(timespec="seconds").replace("+00:00", "Z"))
    item["slug"] = Path(res["image"]).stem
    pool_path.write_text(json.dumps(pool, ensure_ascii=False, indent=1))
    remaining = sum(1 for i in pool if not i.get("posted_at"))
    print(f"[photo-cron] {'queued for ' + post_at if post_at else 'posted now'} "
          f"| {remaining} lines left in the pool")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
