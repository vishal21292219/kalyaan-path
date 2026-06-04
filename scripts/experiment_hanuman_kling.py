"""EXPERIMENT: Hanuman + Sanjeevani — character-bible + Kling hero shots.

Goal of this one-off test (NOT the daily pipeline):
  1. Level-1 character consistency — every Hanuman scene reuses the same
     appearance description + a LOCKED diffusion seed, so his face stays
     consistent across shots (vs the current "different Hanuman every frame").
  2. Hybrid video cost control — only 2 "hero" shots (mountain lift + flight)
     are real Kling v3 generative video; the other 4 stay on cheap Ken Burns
     stills.

Run:
    .venv/bin/python -m scripts.experiment_hanuman_kling            # full run
    .venv/bin/python -m scripts.experiment_hanuman_kling --reuse-images
    .venv/bin/python -m scripts.experiment_hanuman_kling --no-kling # stills only (cheap)

Est. fal cost (full run): 6 stills x ~$0.04 + 2 hero x 5s x $0.084
  ≈ $0.24 + $0.84 = ~$1.08 (~Rs 90).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pipeline.assembler import assemble
from pipeline.image_gen import generate_images
from pipeline.kling_video import generate_hero_clip
from pipeline.tts import synthesize
from pipeline.utils import out_path, set_active_niche, today_stamp

# ── Character bible: one canonical Hanuman, reused in every scene ──────────
HANUMAN_SEED = 770111
HANUMAN_LOOK = (
    "Lord Hanuman, muscular divine vanara (monkey-faced deity) with golden-orange "
    "fur, devout determined expression, golden crown and large gold earrings, "
    "red loincloth, sacred tilak on forehead, glowing divine aura"
)

# ── Story: Hanuman brings the Sanjeevani mountain (6 beats) ────────────────
# Each tuple: (devanagari narration, roman caption, english visual, uses_hanuman, is_hero, hero_motion)
SCENES = [
    (
        "रात के अंधेरे में लक्ष्मण मूर्छित पड़े थे, और राम टूट चुके थे।",
        "Raat ke andhere mein Lakshman murchhit pade the, aur Ram toot chuke the.",
        "Lakshman lying unconscious on the Lanka battlefield at night, Lord Rama "
        "kneeling beside him in grief, torchlight, somber cinematic mood",
        False, False, None,
    ),
    (
        "तभी हनुमान को आदेश मिला — संजीवनी बूटी लेकर आओ।",
        "Tabhi Hanuman ko aadesh mila — Sanjeevani booti lekar aao.",
        "{look}, kneeling and receiving an urgent command, looking up with resolve, "
        "battlefield camp at night behind him",
        True, False, None,
    ),
    (
        "हिमालय पहुँचकर हनुमान सही बूटी पहचान नहीं पाए।",
        "Himalaya pahunchkar Hanuman sahi booti pehchan nahi paye.",
        "{look}, standing on a glowing herb-covered Himalayan mountainside at dawn, "
        "looking confused among thousands of luminous herbs",
        True, False, None,
    ),
    (
        "तब हनुमान ने पूरा पर्वत ही उठा लिया!",
        "Tab Hanuman ne poora parvat hi utha liya!",
        "{look}, lifting an entire glowing Himalayan mountain over his head with both "
        "hands, muscles straining, dust and rocks falling, epic low-angle shot",
        True, True,
        "Hanuman strains and lifts the entire glowing mountain off the ground, "
        "rocks and dust falling away, muscles flexing, dramatic divine golden light, "
        "slow powerful upward motion, camera slowly pushing in",
    ),
    (
        "पर्वत लेकर वे आकाश में उड़ चले।",
        "Parvat lekar ve aakash mein ud chale.",
        "{look}, flying through the dramatic night sky carrying the glowing mountain, "
        "clouds and stars rushing past, fur and cloth flowing, cinematic aerial view",
        True, True,
        "Hanuman flies powerfully through the night sky carrying the glowing mountain, "
        "clouds rushing past, fur and cloth streaming in the wind, moon glowing, "
        "sweeping cinematic aerial motion",
    ),
    (
        "संजीवनी से लक्ष्मण की जान बच गई — चारों ओर जयकार गूँज उठा।",
        "Sanjeevani se Lakshman ki jaan bach gayi — charon or jaikaar goonj utha.",
        "{look} standing proudly as Lakshman awakens and rises, Lord Rama embracing his "
        "brother, joyful warriors celebrating, golden sunrise, triumphant divine mood",
        True, False, None,
    ),
]


def build_script() -> dict:
    body = [s[0] for s in SCENES]
    body_roman = [s[1] for s in SCENES]
    visuals = [
        s[2].format(look=HANUMAN_LOOK) if "{look}" in s[2] else s[2]
        for s in SCENES
    ]
    return {
        "title": "Hanuman ne poora parvat utha liya 🔥 Sanjeevani ka rahasya",
        "hook": "क्या आप जानते हैं हनुमान संजीवनी बूटी कैसे लाए?",
        "hook_roman": "Kya aap jaante hain Hanuman Sanjeevani booti kaise laaye?",
        "body": body,
        "body_roman": body_roman,
        "cta": "जय हनुमान! कमेंट में लिखें — बजरंगबली।",
        "cta_roman": "Jai Hanuman! Comment mein likhein — Bajrangbali.",
        "visuals": visuals,
        "description": "Hanuman aur Sanjeevani parvat ki katha. #Hanuman #Ramayan #Bhakti",
        "hashtags": ["#Hanuman", "#Ramayan", "#Sanjeevani", "#Bhakti", "#Shorts"],
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse-images", action="store_true", help="Reuse existing stills if present")
    ap.add_argument("--reuse-hero", action="store_true", help="Reuse existing hero clips if present")
    ap.add_argument("--no-kling", action="store_true", help="Skip Kling — stills only (cheap dry run)")
    ap.add_argument("--no-music", action="store_true", help="Voice-only output")
    args = ap.parse_args(argv)

    set_active_niche("bhakti")
    base = f"{today_stamp()}_experiment_hanuman_sanjeevani"
    print("== EXPERIMENT: Hanuman Sanjeevani (character-bible + Kling hero shots) ==")

    script = build_script()
    script_path = out_path("scripts", f"{base}.json")
    script_path.write_text(json.dumps(script, indent=2, ensure_ascii=False))

    # 1. Voiceover
    voice_path = out_path("audio", f"{base}.mp3")
    synthesize(script, voice_path)
    print(f"[tts] saved → {voice_path}")

    # 2. Seed-locked stills — every Hanuman scene reuses HANUMAN_SEED
    seeds = [HANUMAN_SEED if s[3] else None for s in SCENES]
    img_dir = out_path("images", base)
    if args.reuse_images and img_dir.exists() and any(img_dir.glob("img_*.jpg")):
        images = sorted(img_dir.glob("img_*.jpg"))
        print(f"[images] reusing {len(images)} cached stills")
    else:
        images = generate_images(script["visuals"], img_dir, seeds=seeds)
        print(f"[images] generated {len(images)} stills (Hanuman seed={HANUMAN_SEED})")
    if len(images) != len(SCENES):
        print(f"[warn] expected {len(SCENES)} images, got {len(images)} — hero indices may drift")

    # 3. Kling hero clips for the 2 hero scenes, animating their seed-locked still
    hero_clips: dict[int, Path] = {}
    if not args.no_kling:
        for i, s in enumerate(SCENES):
            if not s[4] or i >= len(images):
                continue
            clip_path = img_dir / f"hero_{i:02d}.mp4"
            if args.reuse_hero and clip_path.exists():
                hero_clips[i] = clip_path
                print(f"[hero] reusing cached clip for scene {i + 1}")
                continue
            print(f"[hero] generating Kling clip for scene {i + 1} (~5s, ~$0.42)...")
            if generate_hero_clip(prompt=s[5], ref_image=images[i], out_path=clip_path):
                hero_clips[i] = clip_path
            else:
                print(f"[hero] scene {i + 1} failed — will fall back to Ken Burns still")
    else:
        print("[hero] --no-kling → stills only")

    # 4. Assemble hybrid reel (Kling hero scenes + Ken Burns stills)
    video_path = out_path("videos", f"{base}.mp4")
    assemble(script, voice_path, images, video_path,
             skip_music=args.no_music, hero_clips=hero_clips)

    n_hero = len(hero_clips)
    est = len(images) * 0.04 + n_hero * 5 * 0.084
    print(f"\n[done] FINAL → {video_path}")
    print(f"[done] {n_hero} hero clips, {len(images)} stills | est. fal cost ~${est:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
