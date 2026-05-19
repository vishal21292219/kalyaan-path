"""Generate cinematic Indian devotional background loop via MIDI + fluidsynth.

Output: data/music/cinematic_drone.mp3 (no copyright risk — fully synthesized).
Layers:
- Track 0: Sitar (GM #104) — slow arpeggio over Sa/Pa/Sa-octave
- Track 1: Pad (GM #88 "new age") — sustained drone
- Track 2: Bell / Tinkle (GM #112 "tinkle bell") — sparse high notes
- Track 3: Drums — kick + clap pattern at 72 BPM
"""
import subprocess
from pathlib import Path

from midiutil import MIDIFile

ROOT = Path(__file__).resolve().parent.parent
SOUNDFONT = "/tmp/gm.sf2"
OUT_MP3 = ROOT / "data" / "music" / "cinematic_drone.mp3"

# Indian-style tonic = C# (the Om frequency neighborhood). MIDI note 61 = C#4.
# We'll use C#3 = 49, C#4 = 61, G#3 = 56, E4 = 64, G#4 = 68.
TONIC = 49           # C#3 — Sa
FIFTH = TONIC + 7    # G#3 — Pa
OCTAVE = TONIC + 12  # C#4 — Sa octave
MINOR_THIRD = TONIC + 3   # E3 — komal Ga
SHARP_FOURTH = TONIC + 6  # F#3 — Ma

BPM = 72
DURATION = 120  # seconds → ~144 bars at 72 BPM


def main():
    midi = MIDIFile(4)  # 4 tracks
    for t in range(4):
        midi.addTempo(t, 0, BPM)

    # Track 0: Sitar arpeggio (channel 0, program 104 = Sitar in GM)
    midi.addProgramChange(0, 0, 0, 104)
    arpeggio = [TONIC + 12, TONIC + 15, TONIC + 19, TONIC + 24,
                TONIC + 19, TONIC + 15, TONIC + 12, TONIC + 7]
    t = 0
    bar_beats = 4
    while t < DURATION * (BPM / 60):  # total beats
        for i, note in enumerate(arpeggio):
            midi.addNote(0, 0, note, t + i * 0.5, 0.45, 70)
        t += bar_beats

    # Track 1: Pad drone (channel 1, program 88 = "new age" / fantasia)
    midi.addProgramChange(1, 1, 0, 88)
    t = 0
    while t < DURATION * (BPM / 60):
        midi.addNote(1, 1, TONIC, t, 4.0, 55)        # Sa held 4 beats
        midi.addNote(1, 1, FIFTH, t, 4.0, 50)        # Pa held 4 beats
        midi.addNote(1, 1, OCTAVE, t, 4.0, 45)       # Sa-octave
        t += 4.0

    # Track 2: Tinkle bell shimmer (channel 2, program 14 = tubular bells)
    midi.addProgramChange(2, 2, 0, 14)
    t = 0
    while t < DURATION * (BPM / 60):
        midi.addNote(2, 2, TONIC + 24, t, 1.5, 60)        # Sa double octave
        midi.addNote(2, 2, TONIC + 31, t + 2, 1.5, 50)    # Pa double octave
        t += 4.0

    # Track 3: Drums (channel 9 is GM drums; ignore program — uses drum kit)
    # Kick = note 36, Snare/clap = 38, hi-hat closed = 42, hi-hat open = 46
    t = 0
    while t < DURATION * (BPM / 60):
        midi.addNote(3, 9, 36, t + 0.0, 0.2, 100)       # kick on beat 1
        midi.addNote(3, 9, 42, t + 0.5, 0.2, 70)         # hat on offbeat
        midi.addNote(3, 9, 38, t + 1.0, 0.2, 90)         # snare on beat 2
        midi.addNote(3, 9, 42, t + 1.5, 0.2, 70)
        midi.addNote(3, 9, 36, t + 2.0, 0.2, 100)        # kick on beat 3
        midi.addNote(3, 9, 42, t + 2.5, 0.2, 70)
        midi.addNote(3, 9, 38, t + 3.0, 0.2, 90)         # snare on beat 4
        midi.addNote(3, 9, 42, t + 3.5, 0.2, 70)
        t += 4.0

    mid_path = Path("/tmp/cinematic.mid")
    with open(mid_path, "wb") as f:
        midi.writeFile(f)
    print(f"midi: {mid_path}")

    # Render with fluidsynth → wav → mp3 via ffmpeg
    wav_path = Path("/tmp/cinematic.wav")
    subprocess.run([
        "fluidsynth", "-ni", "-F", str(wav_path),
        "-r", "44100", "-g", "0.7", SOUNDFONT, str(mid_path),
    ], check=True, capture_output=True)
    print(f"wav: {wav_path}")

    OUT_MP3.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-i", str(wav_path),
        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11,acompressor=threshold=0.4:ratio=2.5:attack=20:release=300",
        "-c:a", "libmp3lame", "-b:a", "160k",
        str(OUT_MP3),
    ], check=True, capture_output=True)
    print(f"mp3: {OUT_MP3}")


if __name__ == "__main__":
    main()
