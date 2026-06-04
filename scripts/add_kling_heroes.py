"""Add Kling v3 hero motion to an already-built Hanuman v2 reel.

Reuses the existing master/scene stills, script JSON and voiceover — only
generates 2 Kling I2V hero clips (mountain-lift + sky-flight) and re-assembles
so we don't re-pay for images. Output is a separate *_kling.mp4 so the stills
version is preserved.

Run: .venv/bin/python -m scripts.add_kling_heroes
Cost: 2 x ~$0.42 (5s Kling v3, audio off) ~= $0.84 (~Rs 70).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pipeline.assembler import assemble
from pipeline.kling_video import generate_hero_clip
from pipeline.utils import out_path, set_active_niche

BASE = "20260530_experiment_hanuman_v2"
# scene index -> short motion description for Kling (what MOVES in the shot)
HERO_MOTION = {
    3: "Hanuman heaves the entire glowing mountain overhead, muscles straining, "
       "rocks and dust tumbling, camera slowly pushing in, dramatic epic motion",
    4: "Hanuman soars through the night sky carrying the glowing herb-mountain on "
       "his palm, fur and dhoti billowing, clouds streaking past, cape-like motion",
}


def main() -> int:
    set_active_niche("bhakti")
    img_dir = out_path("images", BASE)
    images = sorted(img_dir.glob("img_*.jpg"))
    if len(images) < 6:
        print(f"[fatal] expected 6 scene stills in {img_dir}, found {len(images)}")
        return 1

    script_path = out_path("scripts", f"{BASE}.json")
    script = json.loads(script_path.read_text())
    voice_path = out_path("audio", f"{BASE}.mp3")
    if not voice_path.exists():
        print(f"[fatal] voiceover missing: {voice_path}")
        return 1

    clip_dir = out_path("videos", f"_kling_{BASE}")
    clip_dir.mkdir(parents=True, exist_ok=True)
    hero_clips: dict[int, Path] = {}
    for idx, motion in HERO_MOTION.items():
        ref = images[idx]
        clip = clip_dir / f"hero_{idx:02d}.mp4"
        print(f"[kling] scene {idx+1}: animating {ref.name} ...")
        if generate_hero_clip(motion, ref, clip, duration=5):
            hero_clips[idx] = clip
        else:
            print(f"[kling] scene {idx+1} FAILED — will stay a Ken Burns still")

    if not hero_clips:
        print("[fatal] no hero clips generated — aborting")
        return 1

    video_path = out_path("videos", f"{BASE}_kling.mp4")
    assemble(script, voice_path, images, video_path, hero_clips=hero_clips)
    print(f"\n[done] FINAL (with Kling heroes) → {video_path}")
    print(f"[done] hero scenes: {sorted(i+1 for i in hero_clips)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
