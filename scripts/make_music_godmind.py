"""Meditative ambient bed for Gods of the Mind (synthesized → royalty-free).
Calm, spacious, slightly hypnotic — the kind of bed you lean in and listen
through. Warm pad + deep drone + soft choir + sparse singing-bowl bells.
Output: data/music_godmind/meditative_bed.mp3 (picked by pick_drone).

Run:  SOUNDFONT=/tmp/gm.sf2 python scripts/make_music_godmind.py
"""
import os
import subprocess
from pathlib import Path

from midiutil import MIDIFile

ROOT = Path(__file__).resolve().parent.parent
SOUNDFONT = os.environ.get("SOUNDFONT", "/tmp/gm.sf2")
OUT = ROOT / "data" / "music_godmind" / "meditative_bed.mp3"
DURATION = 120
BPM = 50
BEATS = DURATION * (BPM / 60)

# C major / add9 peaceful voicing
C3, E3, G3, D4, C4, G4, C2 = 48, 52, 55, 62, 60, 67, 36


def main():
    m = MIDIFile(5, deinterleave=False)
    for t in range(5):
        m.addTempo(t, 0, BPM)
    # Track 0: warm pad — sustained Cadd9 bed, very soft
    m.addProgramChange(0, 0, 0, 89)  # warm pad
    t = 0.0
    while t < BEATS:
        for n in (C3, E3, G3, D4):
            m.addNote(0, 0, n, t, 8.0, 38)
        t += 8.0
    # Track 1: deep string drone — root, calm
    m.addProgramChange(1, 1, 0, 49)
    t = 0.0
    while t < BEATS:
        m.addNote(1, 1, C2, t, 8.0, 34)
        m.addNote(1, 1, C2 + 7, t, 8.0, 28)
        t += 8.0
    # Track 2: soft choir aahs — ethereal, enters after a while
    m.addProgramChange(2, 2, 0, 52)
    t = 8.0
    while t < BEATS:
        m.addNote(2, 2, G3, t, 7.0, 26)
        t += 16.0
    # Track 3: sparse singing-bowl / tubular bell — peaceful chime
    m.addProgramChange(3, 3, 0, 14)
    t = 6.0
    notes = [C4, G3, E3, G4]
    i = 0
    while t < BEATS:
        m.addNote(3, 3, notes[i % len(notes)], t, 3.0, 30)
        i += 1
        t += 10.0
    # Track 4: very soft high pad shimmer
    m.addProgramChange(4, 4, 0, 88)  # new age pad
    t = 16.0
    while t < BEATS:
        m.addNote(4, 4, C4 + 12, t, 8.0, 18)
        t += 24.0

    mid = Path("/tmp/godmind_med.mid")
    with open(mid, "wb") as f:
        m.writeFile(f)
    wav = Path("/tmp/godmind_med.wav")
    subprocess.run(["fluidsynth", "-ni", "-F", str(wav), "-r", "44100", "-g", "0.8",
                    SOUNDFONT, str(mid)], check=True, capture_output=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-i", str(wav),
                    "-af", "lowpass=f=7000,loudnorm=I=-19:TP=-2:LRA=12,"
                           "acompressor=threshold=0.25:ratio=2.5:attack=30:release=600",
                    "-c:a", "libmp3lame", "-b:a", "160k", str(OUT)],
                   check=True, capture_output=True)
    print(f"mp3: {OUT}")


if __name__ == "__main__":
    main()
