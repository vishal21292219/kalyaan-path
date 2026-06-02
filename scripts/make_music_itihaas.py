"""Generate royalty-free background beds for Itihaasvani (synthesized → zero
copyright risk; real trending songs would risk YT strikes/mutes).

Outputs (picked by pick_drone via mood-match on the script):
- data/music_itihaas/suspense_bed.mp3  → mystery/dread/danger topics
- data/music_itihaas/upbeat_bed.mp3    → wonder/achievement/glory topics

Run:  SOUNDFONT=/tmp/gm.sf2 python scripts/make_music_itihaas.py
"""
import os
import subprocess
from pathlib import Path

from midiutil import MIDIFile

ROOT = Path(__file__).resolve().parent.parent
SOUNDFONT = os.environ.get("SOUNDFONT", "/tmp/gm.sf2")
MUSIC_DIR = ROOT / "data" / "music_itihaas"
DURATION = 120  # seconds


def _render(midi: MIDIFile, out_mp3: Path, af: str, gain: str = "0.8"):
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


def build_suspense():
    """Slow ominous D-minor dread bed."""
    ROOT_LOW, D3, F3, A3, A4 = 38, 50, 53, 57, 69
    BPM = 64
    beats = DURATION * (BPM / 60)
    m = MIDIFile(5, deinterleave=False)
    for t in range(5):
        m.addTempo(t, 0, BPM)
    m.addProgramChange(0, 0, 0, 49)  # string pad
    t = 0.0
    while t < beats:
        for n in (D3, F3, A3):
            m.addNote(0, 0, n, t, 8.0, 42)
        t += 8.0
    m.addProgramChange(1, 1, 0, 43)  # contrabass throb
    t = 0.0
    while t < beats:
        m.addNote(1, 1, ROOT_LOW, t, 1.6, 60)
        m.addNote(1, 1, ROOT_LOW, t + 2.0, 1.2, 50)
        t += 4.0
    m.addProgramChange(2, 2, 0, 47)  # timpani booms
    t = 4.0
    while t < beats:
        m.addNote(2, 2, ROOT_LOW, t, 1.0, 70)
        t += 8.0
    m.addProgramChange(3, 3, 0, 44)  # tremolo violin unease
    t = 24.0
    while t < beats:
        m.addNote(3, 3, A4, t, 6.0, 34)
        t += 16.0
    m.addProgramChange(4, 4, 0, 45)  # pizzicato stabs
    t, i, pat = 16.0, 0, [A3, F3, 62]
    while t < beats:
        m.addNote(4, 4, pat[i % 3], t, 0.4, 55)
        i += 1
        t += 12.0
    _render(m, MUSIC_DIR / "suspense_bed.mp3",
            "lowpass=f=8000,loudnorm=I=-18:TP=-2:LRA=11,"
            "acompressor=threshold=0.3:ratio=3:attack=20:release=400")


def build_upbeat():
    """Energetic, epic D-major bed — driving dhol/tabla beat + catchy sitar
    arpeggio + bright string stabs. 'Wonder / achievement' vibe."""
    D3, Fs3, A3, D4, Fs4, A4, D5 = 50, 54, 57, 62, 66, 69, 74
    BPM = 96
    beats = DURATION * (BPM / 60)
    m = MIDIFile(5, deinterleave=False)
    for t in range(5):
        m.addTempo(t, 0, BPM)
    # Track 0: catchy sitar arpeggio (the hook)
    m.addProgramChange(0, 0, 0, 104)  # sitar
    arp = [D4, Fs4, A4, D5, A4, Fs4]
    t = 0.0
    while t < beats:
        for i, n in enumerate(arp):
            m.addNote(0, 0, n, t + i * 0.5, 0.45, 72)
        t += 3.0
    # Track 1: bright string pad stabs (D major chord on the bar)
    m.addProgramChange(1, 1, 0, 48)  # string ensemble
    t = 0.0
    while t < beats:
        for n in (D3, Fs3, A3):
            m.addNote(1, 1, n, t, 0.9, 60)
            m.addNote(1, 1, n, t + 2.0, 0.9, 55)
        t += 4.0
    # Track 2: bass groove
    m.addProgramChange(2, 2, 0, 33)  # finger bass
    t = 0.0
    while t < beats:
        m.addNote(2, 2, 38, t, 0.5, 78)        # D2
        m.addNote(2, 2, 38, t + 1.5, 0.5, 64)
        m.addNote(2, 2, 45, t + 2.5, 0.5, 70)  # A2
        t += 4.0
    # Track 3: DRUMS (GM percussion = channel 9) — driving dhol-style beat
    t = 0.0
    while t < beats:
        m.addNote(3, 9, 36, t, 0.4, 100)        # kick beat 1
        m.addNote(3, 9, 38, t + 1.0, 0.4, 90)   # snare/clap beat 2
        m.addNote(3, 9, 36, t + 2.0, 0.4, 95)   # kick beat 3
        m.addNote(3, 9, 38, t + 3.0, 0.4, 90)   # snare/clap beat 4
        for h in range(8):                       # hi-hat 8ths
            m.addNote(3, 9, 42, t + h * 0.5, 0.2, 55)
        t += 4.0
    # Track 4: high taiko accents every 2 bars (epic lift)
    m.addProgramChange(4, 4, 0, 116)  # taiko
    t = 0.0
    while t < beats:
        m.addNote(4, 4, 38, t, 0.6, 85)
        t += 8.0
    _render(m, MUSIC_DIR / "upbeat_bed.mp3",
            "loudnorm=I=-16:TP=-1.5:LRA=10,"
            "acompressor=threshold=0.35:ratio=2.5:attack=15:release=250")


if __name__ == "__main__":
    build_suspense()
    build_upbeat()
