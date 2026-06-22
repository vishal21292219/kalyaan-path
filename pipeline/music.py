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

import hashlib
import random
import subprocess
from pathlib import Path

from .utils import ROOT, load_config


# ---- dynamic mood-matched track selection ----------------------------------
# The data/music/options/ pool holds several mood-distinct beds. Instead of
# always using one static track, we score each by keywords found in the script
# (title/hook/body) and pick the best fit — so a Tandav video gets shankh-naad
# energy while an aarti gets the mandir bed. Ties / no-match fall back to a
# deterministic per-title rotation so consecutive videos still vary.
_MOOD_TRACKS = [
    ("1_mandir_aarti.mp3", ["aarti", "mandir", "pooja", "puja", "darshan", "kirtan", "temple", "ghanti"]),
    ("2_krishna_bansuri.mp3", ["krishna", "kanha", "kanhaiya", "bansuri", "flute", "radha", "vrindavan", "raas", "murli", "gopal", "govind", "madhav"]),
    ("3_shankh_naad.mp3", ["shiv", "mahadev", "tandav", "shankh", "rudra", "kaal", "durga", "kali", "shakti", "yudh", "war", "bhairav", "asur", "rakshas", "trishul"]),
    ("4_bhakti_beat.mp3", ["chamatkar", "trending", "miracle", "modern", "aaj", "secret", "rahasya", "khatu", "shyam", "sai"]),
    ("A_classic_bhakti.mp3", ["ram", "vishnu", "sita", "hanuman", "bhakti", "devotion", "prem", "shraddha", "bhajan"]),
    ("B_dholak_bansuri.mp3", ["festival", "utsav", "holi", "diwali", "janmashtami", "navratri", "celebration", "dance", "garba"]),
    ("C_mridangam_choir.mp3", ["shloka", "shlok", "gita", "geeta", "gyaan", "mantra", "ved", "upanishad", "dharma", "shanti", "meditative", "moksh"]),
    ("D_uplifting_fast.mp3", ["jai", "vijay", "power", "energy", "uplifting", "glory", "veer", "yoddha", "balwan"]),
]


def _script_text(script: dict | None) -> str:
    if not script:
        return ""
    parts = [str(script.get(k, "")) for k in ("title", "hook", "theme", "topic")]
    body = script.get("body") or []
    parts += [str(x) for x in body[:4]]
    return " ".join(parts).lower()


def _pick_mood_track(options_dir: Path, script: dict | None) -> Path | None:
    """Score the options pool by script keywords; best fit wins, ties/no-match
    rotate deterministically by title hash so videos don't all reuse one track."""
    avail = [(options_dir / f, kws) for f, kws in _MOOD_TRACKS if (options_dir / f).exists()]
    if not avail:
        return None
    text = _script_text(script)
    best, best_score = None, 0
    for path, kws in avail:
        score = sum(1 for k in kws if k in text)
        if score > best_score:
            best, best_score = path, score
    if best_score > 0:
        return best
    # no keyword hit → deterministic rotation (variety across videos)
    h = int(hashlib.md5((text or "default").encode()).hexdigest(), 16)
    return avail[h % len(avail)][0]


# ---- music pickers ---------------------------------------------------------

def pick_music(kind: str | None = None, script: dict | None = None) -> Path | None:
    """Pick a background track, DYNAMICALLY matched to the script's mood when a
    mood pool (music_dir/options/) exists. Shloka mode pins the slow Mridangam
    Choir. Falls back to the legacy static tracks if no pool is present (e.g.
    the ancient niche, which uses its own single cinematic drone)."""
    cfg = load_config()
    music_rel = cfg.get("paths", {}).get("music_dir", "data/music")
    music_dir = ROOT / music_rel
    if not music_dir.exists():
        music_dir = ROOT / "data" / "music"
    options_dir = music_dir / "options"

    if kind == "shloka_episode":
        for cand in (options_dir / "C_mridangam_choir.mp3", music_dir / "shloka_track.mp3"):
            if cand.exists():
                return cand

    # Dynamic mood-matched pick from the options pool (bhakti has one).
    if options_dir.exists():
        chosen = _pick_mood_track(options_dir, script)
        if chosen:
            return chosen

    # Legacy static fallbacks.
    if kind in ("deity", "festival", "story", "temple", "custom", "trending"):
        candidate = music_dir / "trending_track.mp3"
        if candidate.exists():
            return candidate
    tracks = sorted(
        list(music_dir.glob("*.mp3"))
        + list(music_dir.glob("*.wav"))
        + list(music_dir.glob("*.m4a"))
    )
    return tracks[0] if tracks else None


_ITIHAAS_UPBEAT_KWS = [
    "sabse bada", "sabse ooncha", "sabse lamb", "sabse chaud", "sabse purana",
    "duniya ki", "duniya ka", "kaise bana", "kaise banaya", "engineering",
    "marvel", "ajooba", "ajuba", "kamaal", "adbhut", "bhavya", "vishal",
    "shaan", "record", "jeet", "vijay", "taqat", "wonder", "greatest", "khaan",
]
_ITIHAAS_SUSPENSE_KWS = [
    "rahasya", "raaz", "shraap", "shrap", "maut", "doob", "gayab", "khatarnak",
    "bhoot", "pret", "haunted", "andhera", "mystery", "dafan", "kabar", "amar",
    "bhatak", "khoon", "darr", "chhupa", "chupa", "naag", "tabaahi", "gufa",
    "akela", "shaapit", "aatma", "mrityu", "kala jadu", "band", "rahasy",
]


# TimeDecoders (English) — western cinematic beds, mood-matched.
_ANCIENT_EPIC_KWS = [
    "discover", "found", "uncover", "greatest", "largest", "biggest", "advanced",
    "gold", "treasure", "empire", "marvel", "built", "build", "engineering",
    "technology", "wonder", "lost city", "civilization", "rediscover", "reveal",
]
_ANCIENT_MYSTERY_KWS = [
    "mystery", "mysterious", "vanish", "disappear", "unexplained", "lost",
    "hidden", "unknown", "strange", "secret", "ancient", "forbidden", "curse",
    "dark", "eerie", "haunt", "buried", "abandoned", "what happened", "no one knows",
]


def _pick_mood_bed(d: Path, script: dict | None,
                   a_file: str, a_kws: list[str],
                   b_file: str, b_kws: list[str]) -> Path | None:
    """Two-mood bed picker: a_file wins only if its keyword score beats b_file's;
    b_file is the default on tie/no-signal. Returns an existing path or None."""
    a, b = d / a_file, d / b_file
    text = (_script_text(script) or "").lower()
    sa = sum(1 for k in a_kws if k in text)
    sb = sum(1 for k in b_kws if k in text)
    if sa > sb and a.exists():
        return a
    if b.exists():
        return b
    return a if a.exists() else None


# Gods of the Mind — 3 cinematic beds, all on-brand CALM (the bed sits at ~0.09
# vol UNDER the narration; mood = a subtle texture, never hype). power_bed for
# fierce/destroyer themes, shadow_bed for fear/ego/death/illusion, else the
# default meditative_bed for the calm/witness/stillness lane.
_GODMIND_POWER_KWS = [
    "destroy", "destroyer", "destruction", "rage", "fury", "fierce", "wrath",
    "anger", "war", "warrior", "battle", "strength", "power", "powerful",
    "kali", "durga", "tandav", "rudra", "bhairav", "shakti", "fire", "burn",
    "conquer", "force", "weapon", "trident", "slay", "fight", "indra",
]
_GODMIND_SHADOW_KWS = [
    "fear", "death", "die", "dying", "dark", "darkness", "shadow", "ego",
    "illusion", "maya", "anxiety", "suffering", "pain", "loss", "grief",
    "lonely", "loneliness", "doubt", "mystery", "hidden", "secret", "unknown",
    "void", "dissolve", "dissolution", "yama", "yamraj", "kaal", "snake",
    "serpent", "demon", "shani", "attachment",
]


def _pick_godmind_bed(d: Path, script: dict | None) -> Path | None:
    """3-mood bed for Gods of the Mind. power_bed if the script reads fierce,
    shadow_bed if it reads dark/inner, else the default meditative_bed. Always
    returns an existing track (falls back to any mp3 present)."""
    text = (_script_text(script) or "").lower()
    sp = sum(1 for k in _GODMIND_POWER_KWS if k in text)
    ss = sum(1 for k in _GODMIND_SHADOW_KWS if k in text)
    power = d / "power_bed.mp3"
    shadow = d / "shadow_bed.mp3"
    calm = d / "meditative_bed.mp3"
    if sp > 0 and sp >= ss and power.exists():
        return power
    if ss > 0 and shadow.exists():
        return shadow
    if calm.exists():
        return calm
    tracks = sorted(d.glob("*.mp3") )
    return tracks[0] if tracks else None


def pick_drone(niche: str | None = None, script: dict | None = None) -> Path | None:
    """Return the background bed track for the cinematic mix.

    Search order:
      1. DYNAMIC mood-matched track from music_dir/options/ (bhakti pool) —
         makes the bed change per script (aarti vs tandav vs krishna).
      2. config.paths.drone_dir if set
      3. data/music_itihaas/
      4. data/music_ancient/ (cinematic_drone.mp3 — used by TimeDecoders)
      5. fall back to pick_music() so we always have *something* to bed under
    """
    cfg = load_config()
    music_rel = cfg.get("paths", {}).get("music_dir", "data/music")
    music_dir = ROOT / music_rel
    options_dir = music_dir / "options"
    if options_dir.exists():
        chosen = _pick_mood_track(options_dir, script)
        if chosen:
            return chosen

    drone_rel = cfg.get("paths", {}).get("drone_dir", "")
    active_niche = cfg.get("niche", "")
    candidates: list[Path] = []
    if drone_rel:
        candidates.append(ROOT / drone_rel)
    # music_itihaas holds Itihaasvani-specific mood beds — ONLY for that niche
    # (else TimeDecoders/ancient would wrongly grab them).
    if active_niche == "itihaas":
        candidates.append(ROOT / "data" / "music_itihaas")
    candidates.append(ROOT / "data" / "music_ancient")

    for d in candidates:
        if not d.exists() or not d.is_dir():
            continue
        # Mood-match the bed to the script (suspense/upbeat for itihaas;
        # mystery/epic western cinematic for ancient/TimeDecoders).
        if d.name == "music_itihaas":
            bed = _pick_mood_bed(d, script, "upbeat_bed.mp3", _ITIHAAS_UPBEAT_KWS,
                                 "suspense_bed.mp3", _ITIHAAS_SUSPENSE_KWS)
            if bed:
                return bed
        if d.name == "music_ancient":
            bed = _pick_mood_bed(d, script, "epic_bed.mp3", _ANCIENT_EPIC_KWS,
                                 "mystery_bed.mp3", _ANCIENT_MYSTERY_KWS)
            if bed:
                return bed
        if d.name == "music_godmind":
            bed = _pick_godmind_bed(d, script)
            if bed:
                return bed
        tracks = sorted(
            list(d.glob("*.mp3")) + list(d.glob("*.wav")) + list(d.glob("*.m4a"))
        )
        if tracks:
            return tracks[0]

    # last resort — the generic background track
    return pick_music(niche, script=script)


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
    hook_boom: bool = False,           # deep impact on the opening jolt
    whoosh_timestamps: list[float] | None = None,  # riser ~0.3s before each reveal
    heartbeat: bool = False,           # subtle looped suspense bed
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

    # --- tension SFX layers (boom on hook, whoosh risers, heartbeat bed) ---
    sfx_dir = ROOT / "data" / "sfx"
    sfx_labels: list[str] = []

    def _add_oneshot(fname: str, at_t: float, vol: float, label: str):
        nonlocal next_input_idx
        p = sfx_dir / fname
        if not p.exists():
            return
        inputs.extend(["-i", str(p)])
        idx = next_input_idx
        next_input_idx += 1
        delay_ms = max(0, int(at_t * 1000))
        filter_parts.append(
            f"[{idx}:a]volume={vol:.3f},adelay={delay_ms}|{delay_ms},"
            f"apad=pad_dur=0.05[{label}]"
        )
        sfx_labels.append(f"[{label}]")

    if hook_boom:
        _add_oneshot("boom.wav", 0.12, 0.55, "boom")
    for j, t in enumerate(whoosh_timestamps or []):
        _add_oneshot("whoosh.wav", max(0.0, float(t) - 0.30), 0.30, f"whoosh{j}")

    if heartbeat:
        hb = sfx_dir / "heartbeat.wav"
        if hb.exists():
            inputs.extend(["-stream_loop", "-1", "-i", str(hb)])
            idx = next_input_idx
            next_input_idx += 1
            fade_out_start = max(0.0, video_duration - 1.0)
            filter_parts.append(
                f"[{idx}:a]volume=0.085,atrim=duration={video_duration:.3f},"
                f"asetpts=PTS-STARTPTS,afade=t=in:st=0:d=0.8,"
                f"afade=t=out:st={fade_out_start:.3f}:d=1.0[hb]"
            )
            sfx_labels.append("[hb]")

    mix_labels.extend(sting_labels)
    mix_labels.extend(sfx_labels)

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
