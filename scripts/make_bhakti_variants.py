"""4 variations of the Bhakti Beat style — energetic devotional."""
import subprocess
from pathlib import Path

from midiutil import MIDIFile

ROOT = Path(__file__).resolve().parent.parent
SOUNDFONT = "/tmp/gm.sf2"
OUT_DIR = ROOT / "data" / "music" / "options"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SA = 49        # C#3
PA = SA + 7
SA8 = SA + 12

DURATION_SEC = 60


def render(midi_path: Path, mp3_path: Path, gain: float = 0.55):
    wav = mp3_path.with_suffix(".wav")
    subprocess.run([
        "fluidsynth", "-ni", "-F", str(wav), "-r", "44100", "-g", str(gain),
        SOUNDFONT, str(midi_path),
    ], check=True, capture_output=True)
    subprocess.run([
        "ffmpeg", "-y", "-i", str(wav),
        "-af", "loudnorm=I=-18:TP=-2:LRA=11",
        "-c:a", "libmp3lame", "-b:a", "160k", str(mp3_path),
    ], check=True, capture_output=True)
    wav.unlink()


def variant_a_classic_bhakti(bpm=72):
    """Sitar + tabla teen-taal feel + drone."""
    m = MIDIFile(3)
    for t in range(3): m.addTempo(t, 0, bpm)
    total_beats = DURATION_SEC * bpm / 60

    m.addProgramChange(0, 0, 0, 104)  # sitar
    arp = [SA + 12, SA + 15, SA + 19, SA + 24, SA + 19, SA + 15, SA + 12, SA + 19]
    t = 0
    while t < total_beats:
        for i, n in enumerate(arp):
            m.addNote(0, 0, n, t + i * 0.5, 0.4, 75)
        t += 4.0

    m.addProgramChange(1, 1, 0, 89)  # warm pad
    t = 0
    while t < total_beats:
        m.addNote(1, 1, SA, t, 4.0, 55)
        m.addNote(1, 1, PA, t, 4.0, 48)
        t += 4.0

    # Teen taal (16-beat cycle) — kick/snare pattern
    t = 0
    while t < total_beats:
        for beat, note, vel in [
            (0, 36, 100), (0.5, 42, 65), (1, 38, 75), (1.5, 42, 65),
            (2, 36, 95), (2.5, 42, 65), (3, 38, 80), (3.5, 42, 65),
        ]:
            m.addNote(2, 9, note, t + beat, 0.2, vel)
        t += 4.0
    p = Path("/tmp/v_classic.mid")
    with open(p, "wb") as f: m.writeFile(f)
    render(p, OUT_DIR / "A_classic_bhakti.mp3")


def variant_b_dholak_bansuri(bpm=84):
    """Dholak-style rhythm + flute melody + drone — wedding/garba feel."""
    m = MIDIFile(3)
    for t in range(3): m.addTempo(t, 0, bpm)
    total_beats = DURATION_SEC * bpm / 60

    m.addProgramChange(0, 0, 0, 73)  # flute
    melody = [SA + 12, SA + 14, SA + 15, SA + 17, SA + 19, SA + 17, SA + 15, SA + 14,
              SA + 15, SA + 17, SA + 19, SA + 21, SA + 19, SA + 17, SA + 15, SA + 12]
    t = 0
    while t < total_beats:
        for i, n in enumerate(melody):
            m.addNote(0, 0, n, t + i * 0.5, 0.45, 80)
        t += 8.0

    m.addProgramChange(1, 1, 0, 88)  # new age pad
    t = 0
    while t < total_beats:
        m.addNote(1, 1, SA, t, 8.0, 50)
        m.addNote(1, 1, PA, t, 8.0, 45)
        t += 8.0

    # Dholak-style 8-beat keherwa
    t = 0
    while t < total_beats:
        for beat, note, vel in [
            (0, 36, 105), (0.5, 41, 70), (1, 38, 75),
            (1.5, 36, 80), (2, 38, 90), (2.5, 41, 65), (3, 38, 75), (3.5, 36, 85),
        ]:
            m.addNote(2, 9, note, t + beat, 0.2, vel)
        t += 4.0
    p = Path("/tmp/v_dholak.mid")
    with open(p, "wb") as f: m.writeFile(f)
    render(p, OUT_DIR / "B_dholak_bansuri.mp3")


def variant_c_mridangam_choir(bpm=66):
    """Slow mridangam-style + sitar + om-choir pad. Reverent + epic."""
    m = MIDIFile(4)
    for t in range(4): m.addTempo(t, 0, bpm)
    total_beats = DURATION_SEC * bpm / 60

    m.addProgramChange(0, 0, 0, 104)  # sitar
    pattern = [SA + 12, SA + 15, SA + 19, SA + 15, SA + 12, SA + 7]
    t = 0
    while t < total_beats:
        for i, n in enumerate(pattern):
            m.addNote(0, 0, n, t + i * 1.0, 0.8, 65)
        t += 6.0

    m.addProgramChange(1, 1, 0, 91)  # choir aahs
    t = 0
    while t < total_beats:
        m.addNote(1, 1, SA, t, 8.0, 60)
        m.addNote(1, 1, PA, t, 8.0, 55)
        m.addNote(1, 1, SA8, t + 4.0, 4.0, 45)
        t += 8.0

    # Mridangam-ish — deeper tom pattern (different drum note 43 = low tom)
    t = 0
    while t < total_beats:
        for beat, note, vel in [
            (0, 36, 100), (1, 41, 75), (2, 43, 80), (3, 38, 70),
        ]:
            m.addNote(2, 9, note, t + beat, 0.2, vel)
        t += 4.0

    # Bell on key beats
    m.addProgramChange(3, 3, 0, 14)
    t = 0
    while t < total_beats:
        m.addNote(3, 3, SA + 24, t, 2.0, 70)
        t += 8.0
    p = Path("/tmp/v_mridangam.mid")
    with open(p, "wb") as f: m.writeFile(f)
    render(p, OUT_DIR / "C_mridangam_choir.mp3")


def variant_d_uplifting_fast(bpm=96):
    """Faster bhajan tempo — sitar + tabla + bell, more uplifting energy."""
    m = MIDIFile(3)
    for t in range(3): m.addTempo(t, 0, bpm)
    total_beats = DURATION_SEC * bpm / 60

    m.addProgramChange(0, 0, 0, 104)  # sitar
    # 8th-note arpeggio cycling
    arp = [SA + 12, SA + 15, SA + 19, SA + 22, SA + 19, SA + 15,
           SA + 17, SA + 14, SA + 12, SA + 14, SA + 15, SA + 17]
    t = 0
    while t < total_beats:
        for i, n in enumerate(arp):
            m.addNote(0, 0, n, t + i * 0.5, 0.4, 80)
        t += 6.0

    m.addProgramChange(1, 1, 0, 89)  # warm pad
    t = 0
    while t < total_beats:
        m.addNote(1, 1, SA, t, 4.0, 50)
        m.addNote(1, 1, PA, t, 4.0, 45)
        t += 4.0

    # Faster keherwa
    t = 0
    while t < total_beats:
        for beat, note, vel in [
            (0, 36, 110), (0.5, 42, 65), (1, 38, 85),
            (1.5, 42, 65), (2, 36, 100), (2.5, 42, 65),
            (3, 38, 90), (3.5, 36, 75),
        ]:
            m.addNote(2, 9, note, t + beat, 0.2, vel)
        t += 4.0
    p = Path("/tmp/v_uplifting.mid")
    with open(p, "wb") as f: m.writeFile(f)
    render(p, OUT_DIR / "D_uplifting_fast.mp3")


if __name__ == "__main__":
    # remove old options A-D if any, keep 1-4 originals if user wants comparison
    for f in OUT_DIR.glob("[A-D]_*.mp3"):
        f.unlink()
    variant_a_classic_bhakti()
    variant_b_dholak_bansuri()
    variant_c_mridangam_choir()
    variant_d_uplifting_fast()
    print("DONE")
