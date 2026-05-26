"""Picks a background music track from data/music/ and composes the
3-layer cinematic audio mix used by the assembler.

Drop royalty-free .mp3/.wav files in data/music/. The pipeline mixes one
in at low volume under the voiceover.

Good sources for royalty-free Hindu/devotional/meditation tracks:
- YouTube Audio Library (https://www.youtube.com/audiolibrary)
- Pixabay Music (https://pixabay.com/music/)
- Freesound (https://freesound.org/) — check license
- Uppbeat free tier (https://uppbeat.io/)

Keywords to search: "meditation", "indian flute", "tabla", "sitar drone",
"spiritual ambient", "raga", "om mantra".

3-LAYER CINEMATIC MIX (added 2026-05-26):
  Layer 1: VOICE (foreground, full volume)         — TTS narration
  Layer 2: AMBIENT DRONE (-20dB, full duration)    — tabla/sitar bed
  Layer 3: STING HITS (-15dB, key moments)         — bell/cymbal/om
The assembler calls compose_audio_track() to bake all three into one
audio file that's then muxed into the final video.
"""
from __future__ import annotations

import random
import subprocess
from pathlib import Path

from .utils import ROOT, load_config


# ---- music pickers ---------------------------------------------------------

def pick_music(kind: str | None = None) -> Path | None:
    """Pick a background track. For shloka mode use the slow Mridangam Choir;
    for trending/deity/festival use the faster Uplifting track.
    """
    cfg = load_config()
    music_rel = cfg.get("paths", {}).get("music_dir", "data/music")
    music_dir = ROOT / music_rel
    if not music_dir.exists():
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


def pick_drone(niche: str | None = None) -> Path | None:
    """Return an ambient drone track for the middle layer of the cinematic mix.

    Search order:
      1. config.paths.drone_dir if set
      2. data/music_itihaas/ (mythology niche convention)
      3. data/music_ancient/ (existing cinematic_drone.mp3 lives here)
      4. fall back to pick_music() so we always have *something* to bed under
    """
    cfg = load_config()
    drone_rel = cfg.get("paths", {}).get("drone_dir", "")

    candidates: list[Path] = []
    if drone_rel:
        candidates.append(ROOT / drone_rel)
    candidates.extend([
        ROOT / "data" / "music_itihaas",
        ROOT / "data" / "music_ancient",
    ])

    for d in candidates:
        if not d.exists() or not d.is_dir():
            continue
        tracks = sorted(
            list(d.glob("*.mp3")) + list(d.glob("*.wav")) + list(d.glob("*.m4a"))
        )
        if tracks:
            return tracks[0]

    # last resort — the generic background track
    return pick_music(niche)


def pick_sting(emphasis_level: int = 0) -> Path | None:
    """Return a sting hit from data/music_stings/.

    emphasis_level is a 0..N index used to deterministically rotate through the
    sting library, so the same script always gets the same sting sequence
    (instead of random per-render which breaks reruns/regression-testing).
    """
    sting_dir = ROOT / "data" / "music_stings"
    if not sting_dir.exists():
        return None
    stings = sorted(
        list(sting_dir.glob("*.mp3")) + list(sting_dir.glob("*.wav"))
    )
    if not stings:
        return None
    return stings[emphasis_level % len(stings)]


# ---- sting timestamp heuristic ---------------------------------------------

def pick_sting_timestamps(video_duration: float) -> list[float]:
    """Pick 2-4 timestamps (in seconds) where sting hits should fire.

    Heuristic based on script structure:
      - Opening hook: 0.5s in
      - Mid-video pivot: 40% mark
      - Climax reveal: 75% mark
      - Outro: 1.0s before the end
    Returns the subset of these that actually fit inside video_duration with
    enough headroom for the sting to play out.
    """
    candidates: list[float] = []
    if video_duration <= 0:
        return candidates
    candidates.append(0.5)
    if video_duration >= 6.0:
        candidates.append(round(video_duration * 0.40, 2))
    if video_duration >= 10.0:
        candidates.append(round(video_duration * 0.75, 2))
    if video_duration >= 4.0:
        candidates.append(round(max(0.0, video_duration - 1.0), 2))

    # Dedupe + keep stings at least 1.5s apart so they don't overlap
    out: list[float] = []
    for t in candidates:
        if t < 0 or t > video_duration - 0.2:
            continue
        if out and (t - out[-1]) < 1.5:
            continue
        out.append(t)
    return out[:4]


# ---- 3-layer audio composer ------------------------------------------------

def _audio_duration(path: Path) -> float:
    out = subprocess.check_output(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ],
        text=True,
    )
    try:
        return float(out.strip())
    except ValueError:
        return 0.0


def compose_audio_track(
    voice_path: Path,
    video_duration: float,
    drone_path: Path | None,
    sting_timestamps: list[float],
    out_path: Path | None = None,
    voice_volume: float = 1.2,
    drone_volume: float = 0.10,   # ~-20 dB under voice
    sting_volume: float = 0.18,   # ~-15 dB under voice
) -> Path:
    """Bake voice + drone + stings into a single AAC/M4A audio file.

    Returns the path of the mixed audio. The assembler then muxes this with
    the rendered video stream — keeping audio mixing logic out of the
    assembler keeps it testable in isolation.

    If `drone_path` is None and `sting_timestamps` is empty, this still works:
    we just return a re-encoded copy of the voice (so the assembler always has
    a single, predictable input file).
    """
    if out_path is None:
        out_path = voice_path.with_suffix(".mix.m4a")

    inputs: list[str] = ["-i", str(voice_path)]
    filter_parts: list[str] = ["[0:a]anull[voice]"]
    mix_labels: list[str] = ["[voice]"]
    next_input_idx = 1

    # --- drone layer ---
    if drone_path and drone_path.exists():
        # stream-loop so a short drone tiles to cover long videos
        inputs = ["-stream_loop", "-1", "-i", str(drone_path)] + inputs
        # but inputs above appended voice first; rebuild cleanly:
        inputs = [
            "-i", str(voice_path),
            "-stream_loop", "-1", "-i", str(drone_path),
        ]
        next_input_idx = 2
        # Trim to exactly video_duration, soft fade in/out so it doesn't pop.
        fade_out_start = max(0.0, video_duration - 1.0)
        filter_parts.append(
            f"[1:a]volume={drone_volume:.3f},lowpass=f=7000,"
            f"atrim=duration={video_duration:.3f},asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d=0.8,"
            f"afade=t=out:st={fade_out_start:.3f}:d=1.0[drone]"
        )
        mix_labels.append("[drone]")

    # --- sting layer(s) ---
    sting_labels: list[str] = []
    for i, t in enumerate(sting_timestamps or []):
        sting_path = pick_sting(emphasis_level=i)
        if not sting_path or not sting_path.exists():
            continue
        inputs += ["-i", str(sting_path)]
        idx = next_input_idx
        next_input_idx += 1
        lbl = f"sting{i}"
        delay_ms = max(0, int(t * 1000))
        filter_parts.append(
            f"[{idx}:a]volume={sting_volume:.3f},"
            f"adelay={delay_ms}|{delay_ms},apad=pad_dur=0.05[{lbl}]"
        )
        sting_labels.append(f"[{lbl}]")

    mix_labels.extend(sting_labels)

    if len(mix_labels) == 1:
        # voice only — short-circuit to a plain re-encode
        cmd = [
            "ffmpeg", "-y", *inputs,
            "-map", "0:a",
            "-c:a", "aac", "-b:a", "192k",
            str(out_path),
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return out_path

    mix_inputs = "".join(mix_labels)
    filter_parts.append(
        f"{mix_inputs}amix=inputs={len(mix_labels)}:"
        f"duration=first:dropout_transition=0:normalize=0[a]"
    )
    filter_complex = ";".join(filter_parts)

    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", filter_complex,
        "-map", "[a]",
        "-c:a", "aac", "-b:a", "192k",
        "-t", f"{video_duration:.3f}",
        str(out_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        # Bubble up a useful tail of stderr — caller prints it.
        raise RuntimeError(
            "compose_audio_track ffmpeg failed:\n" + res.stderr[-2000:]
        )
    return out_path


if __name__ == "__main__":
    print("music:", pick_music())
    print("drone:", pick_drone())
    print("sting[0]:", pick_sting(0))
    print("stings@20s:", pick_sting_timestamps(20.0))
