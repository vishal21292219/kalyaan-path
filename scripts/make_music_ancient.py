"""Western cinematic-ambient beds for TimeDecoders (English ancient-mysteries).

Fully synthesized (MIDI+fluidsynth) → royalty-free. NO Indian instruments
(sitar/tabla/bells) — those felt out of place before. Pure orchestral:
strings, cello, choir, French horn, timpani. Kept very soft (documentary bed).

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


def _render(midi: MIDIFile, out_mp3: Path, af: str, gain: str = "0.7"):
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
    """A-minor slow ambient dread — strings + choir + lone violin. Eerie, sparse."""
    A2, C3, E3, A3, E4, A1 = 45, 48, 52, 57, 64, 33
    BPM = 60
    beats = DURATION * (BPM / 60)
    m = MIDIFile(5, deinterleave=False)
    for t in range(5):
        m.addTempo(t, 0, BPM)
    m.addProgramChange(0, 0, 0, 49)   # string ensemble 2 — pad
    t = 0.0
    while t < beats:
        for n in (A2, C3, E3):
            m.addNote(0, 0, n, t, 8.0, 40)
        t += 8.0
    m.addProgramChange(1, 1, 0, 43)   # contrabass — sparse root
    t = 0.0
    while t < beats:
        m.addNote(1, 1, A1, t, 3.0, 52)
        t += 8.0
    m.addProgramChange(2, 2, 0, 52)   # choir aahs — soft air
    t = 8.0
    while t < beats:
        m.addNote(2, 2, A3, t, 7.0, 30)
        t += 16.0
    m.addProgramChange(3, 3, 0, 40)   # solo violin — eerie high long tone
    t = 24.0
    while t < beats:
        m.addNote(3, 3, E4, t, 6.0, 30)
        t += 20.0
    m.addProgramChange(4, 4, 0, 47)   # timpani — very sparse
    t = 16.0
    while t < beats:
        m.addNote(4, 4, A1, t, 1.0, 55)
        t += 32.0
    _render(m, MUSIC_DIR / "mystery_bed.mp3",
            "lowpass=f=7500,loudnorm=I=-20:TP=-2:LRA=11,"
            "acompressor=threshold=0.25:ratio=3:attack=25:release=450")


def build_epic():
    """C-major grand discovery bed — swelling strings + French horn + choir +
    timpani builds. Hopeful, cinematic, still soft."""
    C3, E3, G3, C4, G2, C2 = 48, 52, 55, 60, 43, 36
    BPM = 72
    beats = DURATION * (BPM / 60)
    m = MIDIFile(5, deinterleave=False)
    for t in range(5):
        m.addTempo(t, 0, BPM)
    m.addProgramChange(0, 0, 0, 48)   # string ensemble 1 — swelling chords
    t = 0.0
    while t < beats:
        for n in (C3, E3, G3, C4):
            m.addNote(0, 0, n, t, 8.0, 46)
        t += 8.0
    m.addProgramChange(1, 1, 0, 60)   # french horn — noble melody
    horn = [G3, C4, E3, G3]
    t = 4.0
    i = 0
    while t < beats:
        m.addNote(1, 1, horn[i % len(horn)], t, 3.5, 48)
        i += 1
        t += 8.0
    m.addProgramChange(2, 2, 0, 52)   # choir aahs
    t = 0.0
    while t < beats:
        m.addNote(2, 2, G3, t, 8.0, 34)
        t += 8.0
    m.addProgramChange(3, 3, 0, 42)   # cello — moving bassline
    bass = [C2, G2, C2, E3 - 12]
    t = 0.0
    i = 0
    while t < beats:
        m.addNote(3, 3, bass[i % len(bass)], t, 1.8, 58)
        i += 1
        t += 2.0
    m.addProgramChange(4, 4, 0, 47)   # timpani — building pulse on the bar
    t = 0.0
    while t < beats:
        m.addNote(4, 4, C2, t, 1.0, 60)
        m.addNote(4, 4, G2, t + 4.0, 0.8, 50)
        t += 8.0
    _render(m, MUSIC_DIR / "epic_bed.mp3",
            "loudnorm=I=-18:TP=-1.5:LRA=10,"
            "acompressor=threshold=0.3:ratio=2.5:attack=20:release=300")


if __name__ == "__main__":
    build_mystery()
    build_epic()
