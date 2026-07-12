#!/usr/bin/env python3
"""ANHONI music — generate a suspense track (fal stable-audio) for a story.
  python music_gen.py <slug>   -> out/<slug>/music.mp3"""
import os, sys, json, urllib.request
from pathlib import Path
OUT = Path(__file__).parent
ENV = OUT.parent / ".env"; E = dict(os.environ)
if ENV.exists():
    for l in ENV.read_text().splitlines():
        if "=" in l and not l.strip().startswith("#"):
            k, v = l.split("=", 1); E.setdefault(k.strip(), v.strip())
KEY = E["FAL_KEY"]
def main(slug):
    spec = json.loads((OUT / f"story_{slug}.json").read_text())
    prompt = spec.get("music_prompt") or "dark cinematic suspense background music, tense low drone, eerie, no vocals, no drums"
    base = OUT / "out" / slug; base.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"prompt": prompt, "seconds_total": 47}).encode()
    req = urllib.request.Request("https://fal.run/fal-ai/stable-audio", data=body,
        headers={"Authorization": "Key " + KEY, "Content-Type": "application/json"})
    d = json.load(urllib.request.urlopen(req, timeout=180))
    url = (d.get("audio_file") or {}).get("url") or (d.get("audio") or {}).get("url")
    urllib.request.urlretrieve(url, base / "music.mp3")
    print("MUSIC ->", base / "music.mp3")
if __name__ == "__main__":
    main(sys.argv[1])
