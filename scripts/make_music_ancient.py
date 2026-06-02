"""Western cinematic beds for TimeDecoders (English ancient-mysteries) — fully
synthesized, royalty-free. DISTINCT from Itihaasvani (which is Indian). Pure
Western: piano, orchestral strings, brass, timpani, choir. NO Indian instruments.

Built with an ARC (sparse intro → build → climax ~40-45s → settle) so it tracks
a short reel instead of a flat loop.

Outputs (mood-matched by pick_drone):
- data/music_ancient/mystery_bed.mp3  → lost/vanished/unexplained (default)
- data/music_ancient/epic_bed.mp3     → discovery/greatest/advanced/marvel

Run:  SOUNDFONT=/tmp/gm.sf2 python scripts/make_music_ancient.py
"""
import os
import subprocess
from pathlib import Path

from midiutil import MIDIFile

ROOT = Path(__file__).resolve().parent.parent
SOUNDFONT = os.environ.get("SOUNDFONT", "/tmp/gm.sf2")
MUSIC_DIR = ROOT / "data" / "music_ancient"
DURATION = 120

PIANO, STR1, STR2, HORN, BRASS, CHOIR, TIMP, TAIKO, CELLO, VLN = 0, 48, 49, 60, 61, 52, 47, 116, 42, 40


def _arc_vel(t, beats, base, peak):
    frac = t / beats
    if frac < 0.38:
        v = base + (peak - base) * (frac / 0.38)
    else:
        v = peak - (peak - base) * 0.4 * ((frac - 0.38) / 0.62)
    return int(max(1, min(127, v)))


def _render(midi, out_mp3, af, gain="0.7"):
    mid = Path(f"/tmp/{out_mp3.stem}.mid")
    with open(mid, "wb") as f:
        midi.writeFile(f)
    wav = Path(f"/tmp/{out_mp3.stem}.wav")
    subprocess.run(["fluidsynth", "-ni", "-F", str(wav), "-r", "44100",
                    "-g", gain, SOUNDFONT, str(mid)], check=True, capture_output=True)
    out_mp3.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-i", str(wav), "-af", af,
                    "-c:a", "libmp3lame", "-b:a", "160k", str(out_mp3)],
                   check=True, capture_output=True)
    print(f"mp3: {out_mp3}")


def build_mystery():
    """Western investigative dread — lone PIANO motif over low string drone +
    sub bass + sparse high violin. Sparse, modern-documentary. A minor."""
    A2, C3, E3, A3, E4, A1, B2, G3 = 45, 48, 52, 57, 64, 33, 47, 55
    BPM = 64
    beats = DURATION * (BPM / 60)
    m = MIDIFile(5, deinterleave=False)
    for t in range(5):
        m.addTempo(t, 0, BPM)
    # Track 0: low string drone pad (Am)
    m.addProgramChange(0, 0, 0, STR2)
    t = 0.0
    while t < beats:
        for n in (A2, C3, E3):
            m.addNote(0, 0, n, t, 8.0, _arc_vel(t, beats, 26, 42))
        t += 8.0
    # Track 1: lone piano motif (the 'investigation' hook) — repeats, builds
    m.addProgramChange(1, 1, 0, PIANO)
    motif = [(A3, 1), (C3 + 12, 1), (B2 + 12, 2), (E3 + 12, 1), (A3, 3)]
    t = 8.0
    while t < beats:
        for note, dur in motif:
            if t >= beats:
                break
            m.addNote(1, 1, note, t, dur * 0.95, _arc_vel(t, beats, 34, 70))
            t += dur
        t += 3.0
    # Track 2: sub bass
    m.addProgramChange(2, 2, 0, CELLO)
    t = 0.0
    while t < beats:
        m.addNote(2, 2, A1, t, 3.5, _arc_vel(t, beats, 40, 64))
        t += 8.0
    # Track 3: sparse high violin tension long-tone
    m.addProgramChange(3, 3, 0, VLN)
    t = 24.0
    while t < beats:
        m.addNote(3, 3, E4, t, 6.0, _arc_vel(t, beats, 24, 44))
        t += 18.0
    # Track 4: very sparse timpani pulse, density rises
    m.addProgramChange(4, 4, 0, TIMP)
    t = 16.0
    while t < beats:
        m.addNote(4, 4, A1, t, 1.0, _arc_vel(t, beats, 40, 66))
        t += (16.0 if t / beats < 0.4 else 8.0)
    _render(m, MUSIC_DIR / "mystery_bed.mp3",
            "lowpass=f=8000,loudnorm=I=-20:TP=-2:LRA=11,"
            "acompressor=threshold=0.25:ratio=3:attack=25:release=450")


def build_epic():
    """Western discovery trailer — BRASS + horn fanfare + swelling strings +
    choir + timpani/taiko builds. C major, grand."""
    C3, E3, G3, C4, G2, C2, E4 = 48, 52, 55, 60, 43, 36, 64
    BPM = 76
    beats = DURATION * (BPM / 60)
    m = MIDIFile(6, deinterleave=False)
    for t in range(6):
        m.addTempo(t, 0, BPM)
    # Track 0: swelling string ensemble chords
    m.addProgramChange(0, 0, 0, STR1)
    t = 0.0
    while t < beats:
        for n in (C3, E3, G3, C4):
            m.addNote(0, 0, n, t, 8.0, _arc_vel(t, beats, 38, 60))
        t += 8.0
    # Track 1: brass fanfare (the trailer hook)
    m.addProgramChange(1, 1, 0, BRASS)
    fan = [(G3, 1), (C4, 2), (E4, 1), (G3, 2), (C4, 2)]
    t = 8.0
    while t < beats:
        for note, dur in fan:
            if t >= beats:
                break
            m.addNote(1, 1, note, t, dur * 0.9, _arc_vel(t, beats, 36, 74))
            t += dur
        t += 4.0
    # Track 2: french horn pad
    m.addProgramChange(2, 2, 0, HORN)
    t = 4.0
    while t < beats:
        m.addNote(2, 2, G3, t, 4.0, _arc_vel(t, beats, 30, 52))
        t += 8.0
    # Track 3: choir aahs
    m.addProgramChange(3, 3, 0, CHOIR)
    t = 16.0
    while t < beats:
        m.addNote(3, 3, C4, t, 8.0, _arc_vel(t, beats, 28, 48))
        t += 16.0
    # Track 4: cello moving bassline
    m.addProgramChange(4, 4, 0, CELLO)
    bass = [C2, G2, C2, E3 - 12]
    t = 0.0
    i = 0
    while t < beats:
        m.addNote(4, 4, bass[i % 4], t, 1.8, _arc_vel(t, beats, 50, 70))
        i += 1
        t += 2.0
    # Track 5: timpani + taiko trailer hits (ch via programs), build
    m.addProgramChange(5, 5, 0, TIMP)
    t = 0.0
    while t < beats:
        v = _arc_vel(t, beats, 45, 95)
        m.addNote(5, 5, C2, t, 1.0, v)
        m.addNote(5, 5, G2, t + 4.0, 0.8, v - 10)
        if t / beats > 0.35:
            m.addNote(5, 5, C2, t + 6.0, 0.6, v - 6)
        t += 8.0
    _render(m, MUSIC_DIR / "epic_bed.mp3",
            "loudnorm=I=-18:TP=-1.5:LRA=10,"
            "acompressor=threshold=0.3:ratio=2.5:attack=20:release=300")


if __name__ == "__main__":
    build_mystery()
    build_epic()
