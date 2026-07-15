#!/usr/bin/env python3
"""ANHONI daily automation (GitHub Actions cron, also runs locally).
Picks the day's suspense seed (date-based rotation → no repeats for len(seeds)
days), generates a PREMIUM character-locked comic video, and publishes to
YouTube + Instagram + Facebook. Scheduled for NIGHT IST (~9:30 PM) — best time
for suspense/thriller content.
  python daily_anhoni.py [--dry-run]   (--dry-run = build video, do NOT publish)
"""
import sys, json, datetime, traceback
from pathlib import Path
import story_gen, gen_art, music_gen, assemble, publish

OUT = Path(__file__).parent
SEEDS = json.loads((OUT / "topics_anhoni.json").read_text())["seeds"]
STATE = OUT / "published_log.json"

def pick_seed():
    idx = datetime.date.today().toordinal() % len(SEEDS)
    return idx, SEEDS[idx]

def log(slug, seed, yt):
    data = json.loads(STATE.read_text()) if STATE.exists() else []
    data.append({"date": datetime.date.today().isoformat(), "slug": slug, "seed": seed[:80], "yt": yt})
    STATE.write_text(json.dumps(data, ensure_ascii=False, indent=2))

def main(dry=False):
    idx, seed = pick_seed()
    slug = "anhoni_" + datetime.date.today().strftime("%Y%m%d")
    print(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] seed#{idx} slug={slug}\n  {seed}")
    # skip if already published today
    if STATE.exists() and any(r["slug"] == slug for r in json.loads(STATE.read_text())):
        print("Already published today — skipping."); return
    story_gen.generate(seed, slug)
    gen_art.main(slug)
    try: music_gen.main(slug)
    except Exception as e: print("music skipped:", e)
    assemble.main(slug)
    if dry:
        print("DRY RUN — video ready at", OUT / "out" / slug / "final.mp4", "(not published)"); return
    yt = publish.main(slug)
    if not yt:
        # YouTube is the primary target; a None link means the upload failed.
        # Fail loudly so the CI run goes red (and is retried) instead of a false green.
        raise RuntimeError(f"YouTube upload failed for {slug} — no video link returned")
    log(slug, seed, yt)
    print("PUBLISHED ALL.")

if __name__ == "__main__":
    try:
        main("--dry-run" in sys.argv)
    except Exception:
        traceback.print_exc(); sys.exit(1)
