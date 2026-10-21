"""Comic-style variant of the 'Aakhri Mulaqat' reel — premium graphic-novel art
+ the SAME voiceover storyline (no speech bubbles). Reuses the existing
voiceover audio (no extra ElevenLabs spend); only re-generates images in the
comic style and re-assembles.

Run from repo root:  python render_aakhri_comic.py
"""
from __future__ import annotations

from pipeline.utils import set_active_niche, out_path
from pipeline.image_gen import generate_images
from pipeline.tts import synthesize
from pipeline.assembler import assemble

# Reuse the identical script + character bible + scene list from the photoreal build.
from render_aakhri import SCRIPT, CHARACTER_BIBLE

set_active_niche("aakhri_comic")   # override (importing render_aakhri set it to "aakhri")

SLUG = "aakhri_mulaqat_comic"
VOICE_SLUG = "aakhri_mulaqat"      # reuse the already-rendered voiceover


def main() -> None:
    img_dir = out_path("images", SLUG)
    voice_path = out_path("audio", f"{VOICE_SLUG}.mp3")   # reuse existing VO + words.json
    video_path = out_path("videos", f"{SLUG}.mp4")

    print(f"== Rendering COMIC '{SCRIPT['title']}' ==")

    words_path = voice_path.with_suffix(".words.json")
    if voice_path.exists() and words_path.exists():
        print("[1/3] voiceover — reusing existing (narration unchanged)")
    else:
        print("[1/3] voiceover (ElevenLabs Aakash / thriller)…")
        synthesize(SCRIPT, voice_path)

    print("[2/3] images (comic style, fal FLUX + character consistency)…")
    images = generate_images(
        SCRIPT["visuals"], img_dir, character_bible=CHARACTER_BIBLE
    )
    print(f"      {len(images)} comic scenes generated")

    print("[3/3] assemble (Ken-Burns + captions + emotional music + SFX)…")
    assemble(SCRIPT, voice_path, images, video_path,
             skip_music=False, skip_captions=False)

    print(f"\nFINAL → {video_path}")


if __name__ == "__main__":
    main()
