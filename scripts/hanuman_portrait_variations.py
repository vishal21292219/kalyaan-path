"""Generate 4 master Hanuman portrait STYLE variations so the user can pick
one canonical look before we lock it for the whole reel.

Run: .venv/bin/python -m scripts.hanuman_portrait_variations
Cost: 4 x ~$0.04 (FLUX 1.1-pro) ~= $0.16 (~Rs 14).
"""
from __future__ import annotations

import sys

from pipeline.image_gen import _generate_fal_flux
from pipeline.utils import out_path

SUBJECT = (
    "Lord Hanuman, the divine vanara deity — powerful muscular warrior with a "
    "noble monkey face, devoted expression, golden crown (mukut), gold earrings "
    "and necklaces, saffron-red dhoti, red-and-white tilak, radiant divine halo, "
    "majestic. Centered frontal hero portrait, clean background, vertical 9:16"
)

VARIATIONS = [
    ("photoreal_cinematic",
     f"{SUBJECT}. Photorealistic cinematic 3D render, dramatic studio lighting, "
     "ultra-detailed, volumetric god-rays, epic divine atmosphere, 8k, masterpiece."),
    ("raja_ravi_varma",
     f"{SUBJECT}. Raja Ravi Varma classical Indian oil painting style, soft warm "
     "tones, devotional poster art, fine brushwork, traditional calendar art."),
    ("amar_chitra_katha",
     f"{SUBJECT}. Amar Chitra Katha comic illustration style, bold clean line art, "
     "flat vibrant colors, classic Indian mythology comic book look."),
    ("modern_concept_art",
     f"{SUBJECT}. Modern cinematic concept art, semi-realistic, dramatic rim "
     "lighting, highly detailed digital painting, ArtStation trending, heroic mood."),
]


def main() -> int:
    out_dir = out_path("images", "portrait_variations")
    out_dir.mkdir(parents=True, exist_ok=True)
    print("== Hanuman master portrait — 4 style variations ==")
    made = []
    for i, (name, prompt) in enumerate(VARIATIONS, 1):
        path = out_dir / f"var_{i}_{name}.jpg"
        print(f"[{i}/4] generating {name}...")
        if _generate_fal_flux(prompt, path):
            made.append(path)
            print(f"      -> {path}")
        else:
            print(f"      FAILED: {name}")
    print(f"\n[done] {len(made)}/4 variations in {out_dir}")
    for p in made:
        print("  ", p)
    return 0 if made else 1


if __name__ == "__main__":
    sys.exit(main())
