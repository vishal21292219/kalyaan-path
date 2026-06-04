"""EXPERIMENT: Bal-Krishna POV comfort reel (Yelefinn-style).

Insight from a viral IG reel (@yelefinn.official, 109k plays in 2 days): a
DEAD-SIMPLE flat 2D cartoon of baby Krishna + one emotional Hinglish POV line +
a cute voice beats our expensive photoreal epics. Emotion > production value.

This builds that format:
  - flat 2D cartoon ART STYLE (cute chibi Bal Gopal), consistent via one master
  - a short POV comfort script (Krishna speaks directly to the viewer)
  - a CUTE CHILD voice (edge-tts pitched up, since Hindi has no kid voice)
  - ~12s, no Kling, no epic war drums

Run: .venv/bin/python -m scripts.experiment_krishna_pov
     .venv/bin/python -m scripts.experiment_krishna_pov --reuse-master
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from pipeline.assembler import assemble
from pipeline.char_consistent import (
    _fal_upload,
    generate_master_portrait,
    generate_scene_with_reference,
)
from pipeline.tts import (
    _build_text,
    _edge_synth_with_boundaries,
    _estimate_word_boundaries,
    _silence_align,
)
from pipeline.utils import out_path, set_active_niche, today_stamp

# ── Locked look + style (flat cute cartoon, NOT photoreal) ────────────────
ART_STYLE = (
    "flat 2D cartoon animation style — simple clean thick black outlines, flat "
    "bright cel-shaded colors, cute wholesome children's-storybook look, minimal "
    "shading, soft calm pastel background, adorable Instagram devotional cartoon"
)
KRISHNA_LOOK = (
    "baby Krishna (Bal Gopal), an adorable chubby-cheeked little toddler god with "
    "soft blue skin, big sparkling kind eyes, a sweet gentle smile, a small golden "
    "crown (mukut) holding a single peacock feather, tiny delicate gold jewelry, a "
    "yellow-and-orange silk dhoti, barefoot — utterly cute, wholesome and divine"
)

# ── POV comfort script (Krishna talks to the viewer). 4 spoken lines = 4 images.
SCRIPT = {
    "title": "POV: छोटे कान्हा तुमसे कुछ कहना चाहते हैं 💙🥹",
    "hook": "तुम बहुत थक गए हो ना?",
    "body": [
        "इस दुनिया में सब कुछ मिल जाएगा।",
        "पर असली सुकून सिर्फ मेरे पास मिलेगा।",
    ],
    "cta": "मैं हमेशा तुम्हारे साथ हूँ। जय श्री कृष्ण।",
    "description": "Bal Gopal ki pyaari baat. #Krishna #BalGopal #Bhakti #Shorts",
    "hashtags": ["#Krishna", "#BalGopal", "#Bhakti", "#Shorts", "#JaiShreeKrishna"],
}

# Per-line scene action (POV — baby Krishna facing the viewer/camera)
VISUALS = [
    "baby Krishna sitting cross-legged on soft green grass under a big leafy tree "
    "in a sunny meadow, looking warmly and lovingly straight at the viewer",
    "baby Krishna gently reaching his little hand out toward the viewer, a "
    "comforting caring expression, soft warm glow around him",
    "baby Krishna resting one little hand on his heart, eyes softly closed, a "
    "peaceful serene smile, gentle divine golden light",
    "baby Krishna giving a warm reassuring smile with tiny folded hands in "
    "namaste, soft heavenly light, utterly comforting",
]

# Cute child voice: female Hindi voice pitched up + slightly faster = kid-like
CHILD_VOICE = "hi-IN-SwaraNeural"
CHILD_RATE = "+6%"
CHILD_PITCH = "+40Hz"


def synth_child_voice(script: dict, out_file) -> None:
    """Edge-tts with a high pitch so it sounds like a cute child, plus the
    usual word-boundary sidecar the assembler/captions need."""
    text = _build_text(script)
    asyncio.run(_edge_synth_with_boundaries(text, out_file, CHILD_VOICE, CHILD_RATE, CHILD_PITCH))
    boundaries = _silence_align(text, out_file) or _estimate_word_boundaries(text, out_file)
    out_file.with_suffix(".words.json").write_text(
        json.dumps(boundaries, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"[tts] cute child voice ({CHILD_VOICE} pitch {CHILD_PITCH}) → {len(boundaries)} words")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse-master", action="store_true")
    args = ap.parse_args(argv)

    set_active_niche("bhakti")
    base = f"{today_stamp()}_experiment_krishna_pov"
    img_dir = out_path("images", base)
    img_dir.mkdir(parents=True, exist_ok=True)
    print("== EXPERIMENT: Bal-Krishna POV comfort reel (flat cartoon + cute voice) ==")

    out_path("scripts", f"{base}.json").write_text(
        json.dumps(SCRIPT, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # 1. Master baby-Krishna portrait (flat cartoon)
    master = img_dir / "master_krishna.jpg"
    if args.reuse_master and master.exists():
        print("[char] reusing existing master portrait")
    elif not generate_master_portrait(master, KRISHNA_LOOK, art_style=ART_STYLE):
        print("[fatal] master portrait failed")
        return 1
    master_url = _fal_upload(master)
    if not master_url:
        print("[fatal] master upload failed")
        return 1

    # 2. Scenes — all reference the master, same flat cartoon style
    images = []
    for i, action in enumerate(VISUALS):
        path = img_dir / f"img_{i:02d}.jpg"
        if generate_scene_with_reference(master_url, action, path,
                                         char_name="baby Krishna", art_style=ART_STYLE):
            images.append(path)
            print(f"[scene {i+1}/{len(VISUALS)}] ok")
        else:
            print(f"[scene {i+1}/{len(VISUALS)}] FAILED")

    if len(images) < 3:
        print(f"[fatal] only {len(images)} scenes — aborting")
        return 1

    # 3. Cute child voice + assemble (no epic music for a soft comfort reel)
    voice_path = out_path("audio", f"{base}.mp3")
    synth_child_voice(SCRIPT, voice_path)
    video_path = out_path("videos", f"{base}.mp4")
    assemble(SCRIPT, voice_path, images, video_path, skip_music=True)

    print(f"\n[done] FINAL → {video_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
