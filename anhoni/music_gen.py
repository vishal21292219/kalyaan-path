#!/usr/bin/env python3
"""ANHONI music — pick a background track from the local library (music/*.mp3).
Date-rotated so each day gets a different track. assemble.py then trims it to the
video length with fade in/out + loudnorm. (Was fal stable-audio; now uses the
creator's own tracks for a premium, hand-picked vibe.)
  python music_gen.py <slug>   -> out/<slug>/music.mp3"""
import sys, shutil, datetime
from pathlib import Path
OUT = Path(__file__).parent

def main(slug):
    lib = sorted((OUT / "music").glob("*.mp3"))
    if not lib:
        print("no music library — assemble will render silent"); return
    track = lib[datetime.date.today().toordinal() % len(lib)]
    base = OUT / "out" / slug; base.mkdir(parents=True, exist_ok=True)
    shutil.copy(track, base / "music.mp3")
    print("MUSIC:", track.name)

if __name__ == "__main__":
    main(sys.argv[1])
