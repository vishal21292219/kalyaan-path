#!/usr/bin/env python3
"""Build N photo posts and queue each for its own day's 01:00 UTC slot.

Batch mode exists because a daily cron that nobody watches shipped a bearded
Indra and a weeping Durga. Building ahead means every post is looked at before
it is scheduled, and a late or skipped GitHub cron cannot cost a day's post —
the record is already in the queue for the poster to find.

    python scripts/batch_photos.py --count 10 --start 2026-10-24
"""
from __future__ import annotations
import argparse, json, sys, traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline import photo_post                                    # noqa: E402
from pipeline.uploader_make_reel import upload_photo               # noqa: E402
from pipeline.utils import load_config                             # noqa: E402

COMMENT = ("🕉️ Which part of this is you right now? Tell me honestly — "
           "I read and reply to every comment. 👇")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--start", required=True, help="first post date, YYYY-MM-DD")
    ap.add_argument("--hour", default="01:00", help="UTC HH:MM")
    ap.add_argument("--dry", action="store_true", help="build + gate only, do not queue")
    a = ap.parse_args()

    cfg = load_config()
    niche = cfg.get("niche") or "godmind"
    page = str((cfg.get("publish", {}) or {}).get("fb_page_id") or "").strip()
    if not page and not a.dry:
        print("[batch-photo] no publish.fb_page_id — refusing"); return 1

    pool_path = ROOT / f"data/photo_lines_{niche}.json"
    pool = json.loads(pool_path.read_text())
    hh, mm = (int(x) for x in a.hour.split(":"))
    d0 = datetime.strptime(a.start, "%Y-%m-%d").replace(
        hour=hh, minute=mm, tzinfo=timezone.utc)

    built, failed, day = [], [], 0
    for item in pool:
        if len(built) >= a.count:
            break
        if item.get("built_at") or item.get("posted_at"):
            continue
        when = (d0 + timedelta(days=day)).isoformat(timespec="seconds").replace("+00:00", "Z")
        try:
            # build() RAISES if the frame fails the vision gate — a bad photo
            # must never reach a schedule, and the next line takes its slot.
            res = photo_post.build(item, ROOT / "output/photo")
        except Exception as e:
            print(f"[batch-photo] REJECTED [{item['deity']}] {str(e)[:110]}")
            failed.append((item["deity"], str(e)[:90]))
            continue
        if not a.dry:
            if not upload_photo(res["image"], res["caption"], niche, page,
                                comment=COMMENT, post_at=when):
                print(f"[batch-photo] queue FAILED for {item['deity']}")
                failed.append((item["deity"], "queue failed")); continue
            item["posted_at"] = when
        item["slug"] = Path(res["image"]).stem
        built.append((when, item["deity"], item["line"], res["image"]))
        day += 1
        print(f"[batch-photo] {when}  [{item['deity']}]  {Path(res['image']).name}")

    if not a.dry:
        pool_path.write_text(json.dumps(pool, ensure_ascii=False, indent=2))
    print(f"\n[batch-photo] built+queued {len(built)}, rejected {len(failed)}")
    for d, w in failed:
        print(f"   rejected: {d} — {w}")
    (ROOT / "output/photo/BATCH_MANIFEST.json").write_text(
        json.dumps([{"post_at": w, "deity": d, "line": l, "image": i}
                    for w, d, l, i in built], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
