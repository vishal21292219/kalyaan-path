#!/usr/bin/env python3
"""Publish a Lakeerein video to BOTH YouTube + Instagram from one command.
  python publish_all.py <slug> [yt_publishAt_ISO_UTC]
- YouTube: Short (public, or scheduled if publishAt given) on Lakeerein channel.
- Instagram: Reel via Cloudinary + Make webhook on @lakeereinstories.
Derives title/caption from story_<slug>.json. Isolated."""
import json, sys
from pathlib import Path
OUT=Path(__file__).parent
sys.path.insert(0, str(OUT))
from publish_yt import publish_yt
from publish_ig import cloudinary_upload, trigger

def caption_from(story):
    lines=[s["line"] for s in story["scenes"]]
    return (f"{lines[0]}\n{lines[-1]}\n\nहर लकीर, एक कहानी। ❤️ Lakeerein\n\n"
            "#nostalgia #bachpan #90skids #emotional #yaadein #relatable #hindistory #lakeerein #reels #trending #viral #childhoodmemories")

def main(slug, publish_at=None):
    story=json.loads((OUT/f"story_{slug}.json").read_text())
    mp4=str(OUT/f"final_{slug}.mp4")
    print("== YouTube ==")
    yt=publish_yt(slug, publish_at)
    print("== Instagram ==")
    url=cloudinary_upload(mp4)
    trigger(url, caption_from(story))
    print("\nDONE — YT:",yt,"| IG: posting on @lakeereinstories")

if __name__=="__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv)>2 else None)
