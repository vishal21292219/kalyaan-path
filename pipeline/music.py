"""Picks a background music track from data/music/.

Drop royalty-free .mp3/.wav files in data/music/. The pipeline mixes one
in at low volume under the voiceover.

Good sources for royalty-free Hindu/devotional/meditation tracks:
- YouTube Audio Library (https://www.youtube.com/audiolibrary)
- Pixabay Music (https://pixabay.com/music/)
- Freesound (https://freesound.org/) — check license
- Uppbeat free tier (https://uppbeat.io/)

Keywords to search: "meditation", "indian flute", "tabla", "sitar drone",
"spiritual ambient", "raga", "om mantra".
"""
from __future__ import annotations

import random
from pathlib import Path

from .utils import ROOT


def pick_music() -> Path | None:
    music_dir = ROOT / "data" / "music"
    tracks = [
        *music_dir.glob("*.mp3"),
        *music_dir.glob("*.wav"),
        *music_dir.glob("*.m4a"),
    ]
    if not tracks:
        return None
    return random.choice(tracks)


if __name__ == "__main__":
    print(pick_music())
