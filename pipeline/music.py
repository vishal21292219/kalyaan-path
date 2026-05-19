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


def pick_music(kind: str | None = None) -> Path | None:
    """Pick a background track. For shloka mode use the slow Mridangam Choir;
    for trending/deity/festival use the faster Uplifting track.
    """
    music_dir = ROOT / "data" / "music"
    if kind == "shloka_episode":
        candidate = music_dir / "shloka_track.mp3"
        if candidate.exists():
            return candidate
    if kind in ("deity", "festival", "story", "temple", "custom", "trending"):
        candidate = music_dir / "trending_track.mp3"
        if candidate.exists():
            return candidate
    # fallback — first mp3 in the dir
    tracks = sorted(
        list(music_dir.glob("*.mp3"))
        + list(music_dir.glob("*.wav"))
        + list(music_dir.glob("*.m4a"))
    )
    return tracks[0] if tracks else None


if __name__ == "__main__":
    print(pick_music())
