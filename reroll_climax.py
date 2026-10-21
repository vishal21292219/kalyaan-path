"""Re-roll the WEAK scenes (accident=6, grief=7, climax=11) for both the
photoreal and comic builds, then re-assemble each — reusing the existing
voiceover + all other scene images. Cheap: 3 images per version.

Run from repo root:  python reroll_climax.py
"""
from __future__ import annotations
import shutil
from pathlib import Path

from pipeline.utils import set_active_niche, out_path
from pipeline.image_gen import generate_images
from pipeline.assembler import assemble
from render_aakhri import SCRIPT, CHARACTER_BIBLE

REROLL_IDX = [6, 7, 11]          # accident, grief, climax
VOICE = out_path("audio", "aakhri_mulaqat.mp3")

# (niche, image_slug, video_slug)
BUILDS = [
    ("aakhri",       "aakhri_mulaqat",       "aakhri_mulaqat"),
    ("aakhri_comic", "aakhri_mulaqat_comic", "aakhri_mulaqat_comic"),
]


def main() -> None:
    for niche, img_slug, vid_slug in BUILDS:
        print(f"\n== re-rolling {REROLL_IDX} for {niche} ==")
        set_active_niche(niche)
        img_dir = out_path("images", img_slug)

        for idx in REROLL_IDX:
            prompt = SCRIPT["visuals"][idx]
            tmp = out_path("images", f"_reroll_{img_slug}_{idx}")
            for f in Path(tmp).glob("*.jpg"):
                f.unlink()
            new_imgs = generate_images([prompt], tmp, character_bible=CHARACTER_BIBLE)
            if not new_imgs:
                print(f"  scene {idx}: gen failed — keeping old frame")
                continue
            dst = img_dir / f"img_{idx:02d}.jpg"
            shutil.copy2(new_imgs[0], dst)
            print(f"  scene {idx}: new frame → {dst.name}")

        images = sorted(img_dir.glob("img_*.jpg"))
        video_path = out_path("videos", f"{vid_slug}.mp4")
        assemble(SCRIPT, VOICE, images, video_path, skip_music=False, skip_captions=False)
        print(f"  FINAL → {video_path}")


if __name__ == "__main__":
    main()
