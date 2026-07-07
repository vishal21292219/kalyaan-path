#!/usr/bin/env python3
"""Daily 'money race' generator + publisher for moneurons.

Picks the least-recently-used topic from data/money_races/, renders a PREMIUM
animated bar-race video ($0 — pure PIL+ffmpeg, no fal), and publishes it to the
moneurons YouTube channel + Facebook (via Make). This REPLACES the old
money-psychology format for moneurons (2 subs / dead) with a proven, viral,
fully-automated bar-race format (Data-is-Beautiful style). Free + scalable.
"""
from __future__ import annotations
import json, os, sys, glob, datetime, traceback
from pathlib import Path
from pipeline.utils import ROOT, set_active_niche, load_config
from pipeline import money_race, money_line

USED = ROOT / "data/state/money_race_used.json"

def _load(p):
    try: return json.loads(Path(p).read_text())
    except Exception: return {}

def pick_topic() -> str:
    files = sorted(glob.glob(str(ROOT / "data/money_races/*.json")))
    used = _load(USED)
    files.sort(key=lambda f: (used.get(Path(f).stem, "0000-00-00"), f))  # least-recently-used first
    return files[0]

def mark_used(stem: str):
    used = _load(USED); used[stem] = datetime.date.today().isoformat()
    USED.parent.mkdir(parents=True, exist_ok=True)
    USED.write_text(json.dumps(used, indent=1))

def build_script(spec: dict) -> dict:
    yr = spec.get("subtitle", "").split("-")[-1].strip() or "2026"
    yt_title = spec.get("yt_title") or f"{spec['title'].title()} — {yr} 📈"
    desc = (spec.get("yt_desc", f"Watch how {spec['title'].title()} changed over the years.")
            + "\n\nMusic: Deliberate Thought by Kevin MacLeod (incompetech.com) — Licensed under CC BY 4.0")
    return {"title": yt_title, "description": desc,
            "hashtags": spec.get("hashtags", ["#Moneurons", "#Money", "#Finance", "#DataViz", "#Shorts"]),
            "hook": spec.get("intro", ["", ""])[1]}

def main(argv):
    publish = "--no-publish" not in argv
    set_active_niche("moneurons")
    tf = pick_topic(); stem = Path(tf).stem
    spec = json.loads(Path(tf).read_text())
    outdir = ROOT / "output/money_races"; outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / f"{stem}.mp4"; spec["out"] = str(out)
    engine = money_line if spec.get("format") == "line" else money_race
    print(f"[money-race] topic={stem}  title={spec['title']}  format={spec.get('format','bar')}  publish={publish}")
    engine.make_video(spec, str(ROOT / "assets/money_race/bg.jpg"), str(outdir))
    if not out.exists() or out.stat().st_size < 100000:
        print("[money-race] render FAILED"); return 1
    print(f"[money-race] rendered {out} ({out.stat().st_size} bytes)")
    if not publish:
        print("[money-race] --no-publish: skipping upload"); return 0
    script = build_script(spec); cfg = load_config()
    if cfg.get("publish", {}).get("youtube", True):
        try:
            from pipeline.uploader_youtube import upload as yt_upload
            print("[money-race] youtube:", yt_upload(out, script))
        except Exception: traceback.print_exc(); print("[money-race] youtube failed")
    if cfg.get("publish", {}).get("facebook_make", False):
        try:
            from pipeline.uploader_make_reel import upload as make_upload
            pg = (os.getenv("FB_PAGE_ID_MONEURONS") or "").strip()
            make_upload(out, script, channel="moneurons", fb_page_id=pg)
            print("[money-race] facebook queued")
        except Exception: traceback.print_exc(); print("[money-race] facebook failed")
    mark_used(stem)
    print("[money-race] DONE")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
