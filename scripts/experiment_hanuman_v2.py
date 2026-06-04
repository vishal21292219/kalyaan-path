"""EXPERIMENT v2: Hanuman Sanjeevani — REAL face consistency + viral hook.

Fixes the v1 failures:
  - v1 seed-lock did NOT keep Hanuman's face consistent. v2 uses a single
    MASTER PORTRAIT + nano-banana-2 reference conditioning so every scene
    reuses the exact same deity design.
  - v1 story was flat. v2 gets a viral hook + narration from Claude
    (channel's scriptwriter), not hand-written.
  - No Kling this round (fix images first, cheap).

Run:
    .venv/bin/python -m scripts.experiment_hanuman_v2
    .venv/bin/python -m scripts.experiment_hanuman_v2 --reuse-master   # keep portrait, redo scenes
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pipeline.assembler import assemble
from pipeline.char_consistent import (
    ART_STYLE,
    _fal_upload,
    generate_master_portrait,
    generate_scene_with_reference,
)
from pipeline.image_gen import _generate_fal_flux
from pipeline.script_writer import _claude, _extract_json
from pipeline.tts import synthesize
from pipeline.utils import out_path, set_active_niche, today_stamp

# The canonical Hanuman design — premium, divine. Defines the master portrait.
HANUMAN_LOOK = (
    "Lord Hanuman, the divine vanara (monkey) god — a powerful muscular warrior "
    "with an AUTHENTIC langur monkey face: furry simian muzzle, flat monkey nose, "
    "expressive devoted monkey eyes (NOT a bearded human face, NO human nose), "
    "deep reddish-golden fur covering the face and body, a glowing golden crown "
    "(mukut), heavy gold earrings and necklaces, a saffron-red dhoti, sacred "
    "red-and-white tilak on the forehead, a golden gada (mace), a radiant divine "
    "halo, majestic yet serene"
)

SCRIPT_SYSTEM = (
    "You are the lead scriptwriter for a viral Hindi devotional Shorts channel. "
    "You write scroll-stopping, emotionally gripping mythology Shorts with a "
    "strong curiosity hook in the first 3 seconds, pattern-interrupts, and "
    "mini-cliffhangers. Output JSON only, no markdown fences."
)

SCRIPT_USER = """Write a 6-scene Hindi Shorts script on: Hanuman bringing the Sanjeevani mountain to save Lakshman.

MUST be viral: open with a shocking question or claim (3-second hook), build curiosity, end with an engagement CTA. Simple grade-8 Hindi.

Return ONLY this JSON:
{
  "title": "viral Hinglish title <=70 chars with 1-2 power emojis",
  "hook": "Devanagari Hindi 3-second scroll-stopper, <=14 words",
  "hook_roman": "roman transliteration of hook",
  "cta": "Devanagari Hindi engagement CTA mentioning a binary question or 'Jai Hanuman'",
  "cta_roman": "roman transliteration of cta",
  "scenes": [
    {
      "hi": "Devanagari narration line for this beat (~10-14 words, one breath)",
      "roman": "roman transliteration (short, <60 chars)",
      "action": "English visual: what is happening in this shot (the scene action only, NOT the character's appearance)",
      "has_hanuman": true
    }
    // EXACTLY 6 scenes covering: (1) Lakshman struck down / Ram's grief [has_hanuman=false],
    // (2) Hanuman ordered to fetch Sanjeevani, (3) Hanuman cannot identify the herb on the mountain,
    // (4) Hanuman lifts the entire mountain, (5) Hanuman flies across the sky carrying it,
    // (6) Lakshman revived, jubilation. Scenes 2-6 has_hanuman=true.
  ]
}"""


def get_viral_script() -> dict:
    raw = _claude(SCRIPT_SYSTEM, SCRIPT_USER, "claude-sonnet-4-6")
    data = _extract_json(raw)
    scenes = data.get("scenes") or []
    if len(scenes) != 6:
        print(f"[script] WARNING: Claude returned {len(scenes)} scenes (expected 6)")
    script = {
        "title": data.get("title", "Hanuman aur Sanjeevani"),
        "hook": data["hook"],
        "hook_roman": data.get("hook_roman", data["hook"]),
        "body": [s["hi"] for s in scenes],
        "body_roman": [s.get("roman", s["hi"]) for s in scenes],
        "cta": data.get("cta", "Jai Hanuman!"),
        "cta_roman": data.get("cta_roman", "Jai Hanuman!"),
        "visuals": [s["action"] for s in scenes],
        "description": "Hanuman aur Sanjeevani parvat. #Hanuman #Ramayan #Bhakti",
        "hashtags": ["#Hanuman", "#Ramayan", "#Sanjeevani", "#Bhakti", "#Shorts"],
        "_has_hanuman": [bool(s.get("has_hanuman", True)) for s in scenes],
    }
    return script


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse-master", action="store_true", help="Reuse existing master portrait")
    ap.add_argument("--no-music", action="store_true")
    args = ap.parse_args(argv)

    set_active_niche("bhakti")
    base = f"{today_stamp()}_experiment_hanuman_v2"
    img_dir = out_path("images", base)
    img_dir.mkdir(parents=True, exist_ok=True)
    print("== EXPERIMENT v2: Hanuman Sanjeevani (master portrait + reference conditioning) ==")

    # 1. Viral script via Claude
    print("[script] requesting viral script from Claude...")
    script = get_viral_script()
    has_hanuman = script.pop("_has_hanuman")
    print(f"[script] title: {script['title']}")
    print(f"[script] hook : {script['hook']}")
    out_path("scripts", f"{base}.json").write_text(json.dumps(script, indent=2, ensure_ascii=False))

    # 2. Master Hanuman portrait
    master = img_dir / "master_hanuman.jpg"
    if args.reuse_master and master.exists():
        print("[char] reusing existing master portrait")
    elif not generate_master_portrait(master, HANUMAN_LOOK):
        print("[fatal] master portrait failed — aborting")
        return 1
    master_url = _fal_upload(master)
    if not master_url:
        print("[fatal] could not upload master portrait — aborting")
        return 1

    # 3. Scenes — Hanuman scenes reference the master; others plain FLUX
    images: list[Path] = []
    for i, action in enumerate(script["visuals"]):
        path = img_dir / f"img_{i:02d}.jpg"
        if has_hanuman[i]:
            ok = generate_scene_with_reference(master_url, action, path, char_name="Lord Hanuman")
            tag = "ref"
        else:
            prompt = f"{ART_STYLE}. {action}. Devotional comic 9:16 vertical, dramatic lighting, highly detailed, no text."
            ok = _generate_fal_flux(prompt, path)
            tag = "flux"
        if ok:
            images.append(path)
            print(f"[scene {i+1}/6] {tag} ok")
        else:
            print(f"[scene {i+1}/6] FAILED ({tag}) — skipping")

    if len(images) < 4:
        print(f"[fatal] only {len(images)} scenes generated — aborting")
        return 1

    # 4. Voiceover + assemble (no Kling this round)
    voice_path = out_path("audio", f"{base}.mp3")
    synthesize(script, voice_path)
    video_path = out_path("videos", f"{base}.mp4")
    assemble(script, voice_path, images, video_path, skip_music=args.no_music)

    print(f"\n[done] FINAL → {video_path}")
    print(f"[done] master portrait + {len(images)} reference-conditioned scenes (no Kling)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
