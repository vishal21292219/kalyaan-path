#!/usr/bin/env python3
"""Photo lane CLI — the cheap daily post. See pipeline/photo_post.py for why.

    python scripts/make_photo_post.py --refill 10     # top the line pool up
    python scripts/make_photo_post.py                 # build the next post
    python scripts/make_photo_post.py --line "..." --deity kali --visual "..."
    python scripts/make_photo_post.py --mark <slug>   # mark one as posted

The pool is data/photo_lines_<niche>.json and is consumed in order, so the
schedule is just "run this once a day". Nothing here publishes — rendering and
publishing stay separate so a bad line can be caught before it goes out.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import photo_post                                    # noqa: E402
from pipeline.utils import load_config                             # noqa: E402


def pool_path(niche: str) -> Path:
    return ROOT / f"data/photo_lines_{niche}.json"


def load_pool(p: Path) -> list[dict]:
    return json.loads(p.read_text()) if p.exists() else []


def save_pool(p: Path, pool: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(pool, ensure_ascii=False, indent=1))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refill", type=int, default=0, help="write N new lines into the pool and exit")
    ap.add_argument("--line"); ap.add_argument("--deity"); ap.add_argument("--visual")
    ap.add_argument("--model", default="fal-ai/flux/dev")
    ap.add_argument("--out", default="output/photo")
    ap.add_argument("--mark", help="mark this slug as posted")
    args = ap.parse_args()

    niche = load_config().get("niche") or "godmind"
    pp = pool_path(niche)
    pool = load_pool(pp)

    if args.mark:
        for it in pool:
            if it.get("slug") == args.mark:
                it["posted_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                save_pool(pp, pool)
                print(f"marked {args.mark} posted")
                return 0
        print(f"slug not found: {args.mark}")
        return 1

    if args.refill:
        avoid = [f"{it['deity']}: {it['line']}" for it in pool]
        new = photo_post.write_lines(args.refill, avoid=avoid)
        have = {it["line"].lower() for it in pool}
        added = [n for n in new if n["line"].lower() not in have]
        pool.extend(added)
        save_pool(pp, pool)
        print(f"+{len(added)} lines (pool: {len(pool)}, unused: "
              f"{sum(1 for i in pool if not i.get('posted_at') and not i.get('built_at'))})")
        for a in added:
            print(f"  [{a['deity']}] {a['line']}")
        return 0

    if args.line:
        item = {"line": args.line, "deity": (args.deity or "").lower(),
                "visual": args.visual or args.line}
    else:
        item = next((i for i in pool if not i.get("built_at")), None)
        if not item:
            print("pool empty — run with --refill N")
            return 1

    res = photo_post.build(item, ROOT / args.out, model=args.model)
    if not args.line:
        item["built_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        item["slug"] = Path(res["image"]).stem
        save_pool(pp, pool)

    print(f"\nIMAGE   {res['image']}")
    print(f"\nCAPTION\n{res['caption']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
