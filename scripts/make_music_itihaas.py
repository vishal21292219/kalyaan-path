"""Generate a SUSPENSE / cinematic-mystery background bed for Itihaasvani.

Fully synthesized (MIDI + fluidsynth) → no copyright risk, royalty-free.
Output: data/music_itihaas/suspense_bed.mp3  (picked by pick_drone for itihaas).

Vibe: slow, ominous, building tension — D minor. Layers:
- Low string pad   : sustained Dm chord (D-F-A) — dread bed
- Contrabass pulse : slow root D throb (the "uh-oh" pulse)
- Timpani hits     : sparse low booms on the bar (building dread)
- Tremolo violin   : high A tremolo entering later = unease
- Pizzicato stabs  : sparse tension plucks (the "kya hua?" jab)
Kept low/atmospheric so it sits UNDER the voice (mixed at ~-20 dB in pipeline).
"""
import os
import subprocess
from pathlib import Path

from midiutil import MIDIFile

ROOT = Path(__file__).resolve().parent.parent
SOUNDFONT = os.environ.get("SOUNDFONT", "/tmp/gm.sf2")
OUT_MP3 = ROOT / "data" / "music_itihaas" / "suspense_bed.mp3"

# D minor — cinematic tension. MIDI: D2=38, D3=50, F3=53, A3=57, D4=62, A4=69, Bb3=58, C4=60
ROOT_LOW = 38       # D2 contrabass
D3, F3, A3 = 50, 53, 57
D4, A4 = 62, 69
BPM = 64
DURATION = 120      # seconds
TOTAL_BEATS = DURATION * (BPM / 60)


def main():
    midi = MIDIFile(5, deinterleave=False)
    for t in range(5):
        midi.addTempo(t, 0, BPM)

    # Track 0: low string pad — sustained Dm chord (dread bed)
    midi.addProgramChange(0, 0, 0, 49)  # String Ensemble 2
    t = 0.0
    while t < TOTAL_BEATS:
        for n in (D3, F3, A3):
            midi.addNote(0, 0, n, t, 8.0, 42)   # held 2 bars, soft
        t += 8.0

    # Track 1: contrabass slow root pulse — the ominous throb
    midi.addProgramChange(1, 1, 0, 43)  # Contrabass
    t = 0.0
    while t < TOTAL_BEATS:
        midi.addNote(1, 1, ROOT_LOW, t, 1.6, 60)        # beat 1
        midi.addNote(1, 1, ROOT_LOW, t + 2.0, 1.2, 50)  # beat 3 (softer)
        t += 4.0

    # Track 2: timpani booms — sparse, building dread (every 2 bars)
    midi.addProgramChange(2, 2, 0, 47)  # Timpani
    t = 4.0
    while t < TOTAL_BEATS:
        midi.addNote(2, 2, ROOT_LOW, t, 1.0, 70)
        t += 8.0

    # Track 3: tremolo violin high A — unease, enters after 24 beats, swells in/out
    midi.addProgramChange(3, 3, 0, 44)  # Tremolo Strings
    t = 24.0
    while t < TOTAL_BEATS:
        midi.addNote(3, 3, A4, t, 6.0, 34)   # very soft high shimmer
        t += 16.0

    # Track 4: pizzicato tension stabs — sparse "kya hua?" jabs
    midi.addProgramChange(4, 4, 0, 45)  # Pizzicato Strings
    t = 16.0
    pattern = [A3, F3, D4]
    i = 0
    while t < TOTAL_BEATS:
        midi.addNote(4, 4, pattern[i % len(pattern)], t, 0.4, 55)
        i += 1
        t += 12.0

    mid_path = Path("/tmp/itihaas_suspense.mid")
    with open(mid_path, "wb") as f:
        midi.writeFile(f)
    print(f"midi: {mid_path}")

    wav_path = Path("/tmp/itihaas_suspense.wav")
    subprocess.run([
        "fluidsynth", "-ni", "-F", str(wav_path),
        "-r", "44100", "-g", "0.8", SOUNDFONT, str(mid_path),
    ], check=True, capture_output=True)
    print(f"wav: {wav_path}")

    OUT_MP3.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-i", str(wav_path),
        # gentle reverb-ish lowpass + loudnorm so it sits as a soft bed
        "-af", "lowpass=f=8000,loudnorm=I=-18:TP=-2:LRA=11,"
               "acompressor=threshold=0.3:ratio=3:attack=20:release=400",
        "-c:a", "libmp3lame", "-b:a", "160k",
        str(OUT_MP3),
    ], check=True, capture_output=True)
    print(f"mp3: {OUT_MP3}")


if __name__ == "__main__":
    main()
