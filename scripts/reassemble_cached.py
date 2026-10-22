#!/usr/bin/env python3
"""Re-render finished reels from their CACHED assets — no API spend at all.

WHY THIS EXISTS
---------------
A change that lives in the assembler (the hard-cut opener, caption timing, the
brand mark) only reaches already-built reels if they are rendered again. Running
run.py would re-pick a topic, re-write the script, re-generate every image on
fal and re-voice it on ElevenLabs — paying a second time for assets that are
already on disk and already approved.

Everything the assembler needs survives a build:
    output/scripts/<base>.json      script (hook, body, visuals, cta)
    output/audio/<base>.mp3         narration, plus its .words.json sidecar
    output/images/<base>/img_NN.jpg one image per body line, in order

So this re-runs ONLY pipeline.assembler.assemble() over those. Zero fal.ai,
zero ElevenLabs, zero Claude. The voice is the same take, so nothing about the
reel changes except what the assembler itself does differently.

It writes to output/upload/ and never touches the original in output/videos/,
so the previous render stays available for an A/B until you delete it.

    python scripts/reassemble_cached.py --list
    python scripts/reassemble_cached.py --since 20261022
    python scripts/reassemble_cached.py --base 20261023_the-real-meaning-of-shiva
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SCRIPTS = ROOT / "output/scripts"
AUDIO = ROOT / "output/audio"
IMAGES = ROOT / "output/images"
OUT = ROOT / "output/reassembled"


def assets_for(base: str) -> tuple[Path, Path, list[Path]] | None:
    """Return (script, voice, images) when the full cached set is present."""
    s = SCRIPTS / f"{base}.json"
    v = AUDIO / f"{base}.mp3"
    d = IMAGES / base
    if not (s.exists() and v.exists() and d.is_dir()):
        return None
    imgs = sorted(d.glob("img_*.jpg"))
    return (s, v, imgs) if imgs else None


def candidates(since: str | None) -> list[str]:
    out = []
    for s in sorted(SCRIPTS.glob("*.json")):
        base = s.stem
        if since and base[:8] < since:
            continue
        if assets_for(base):
            out.append(base)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", action="append", help="re-render just this base (repeatable)")
    ap.add_argument("--since", help="only bases dated on/after YYYYMMDD")
    ap.add_argument("--list", action="store_true", help="show what would be rendered, then exit")
    a = ap.parse_args()

    bases = a.base or candidates(a.since)
    if not bases:
        print("nothing to do — no cached asset set matched")
        return 1

    print(f"{len(bases)} reel(s) with a complete cached asset set:\n")
    for b in bases:
        got = assets_for(b)
        if not got:
            print(f"  SKIP {b} — incomplete cache")
            continue
        s, v, imgs = got
        body = len(json.loads(s.read_text()).get("body") or [])
        flag = "" if len(imgs) == body else f"  [!] {len(imgs)} images vs {body} body lines"
        print(f"  {b[:58]:<58} {len(imgs):>3} imgs{flag}")
    if a.list:
        return 0

    from pipeline.assembler import assemble, caption_coverage       # noqa: E402
    OUT.mkdir(parents=True, exist_ok=True)

    ok, failed = [], []
    for i, b in enumerate(bases, 1):
        got = assets_for(b)
        if not got:
            failed.append((b, "incomplete cache"))
            continue
        s, v, imgs = got
        script = json.loads(s.read_text())
        dest = OUT / f"{b}.mp4"
        print(f"\n[{i}/{len(bases)}] {b}")
        t0 = time.time()
        try:
            assemble(script, v, imgs, dest)
        except Exception as e:
            print(f"   FAILED: {type(e).__name__}: {e}")
            failed.append((b, f"{type(e).__name__}: {e}"))
            continue
        if not dest.exists():
            failed.append((b, "no output file"))
            continue
        mb = dest.stat().st_size / 1048576
        print(f"   OK  {mb:.1f} MB  {(time.time()-t0)/60:.1f} min  → {dest}")
        ok.append(b)

    print(f"\nre-rendered {len(ok)}, failed {len(failed)}")
    for b, why in failed:
        print(f"  FAIL {b}: {why}")
    return 0 if ok and not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
