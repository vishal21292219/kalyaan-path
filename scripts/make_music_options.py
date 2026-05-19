"""Generate 4 different background music options. User picks the best."""
import subprocess
from pathlib import Path

from midiutil import MIDIFile

ROOT = Path(__file__).resolve().parent.parent
SOUNDFONT = "/tmp/gm.sf2"
OUT_DIR = ROOT / "data" / "music" / "options"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# C# tuning — common for Hindu chants
SA = 49        # C#3
PA = SA + 7    # G#3
SA8 = SA + 12  # C#4

DURATION_SEC = 60     # 60s loop (will loop in video)
BPM = 64              # slow, devotional
TOTAL_BEATS = DURATION_SEC * BPM / 60


def render(midi_path: Path, mp3_path: Path):
    wav = mp3_path.with_suffix(".wav")
    subprocess.run([
        "fluidsynth", "-ni", "-F", str(wav), "-r", "44100", "-g", "0.55",
        SOUNDFONT, str(midi_path),
    ], check=True, capture_output=True)
    subprocess.run([
        "ffmpeg", "-y", "-i", str(wav),
        "-af", "loudnorm=I=-18:TP=-2:LRA=11",
        "-c:a", "libmp3lame", "-b:a", "160k", str(mp3_path),
    ], check=True, capture_output=True)
    wav.unlink()


def option1_mandir_aarti():
    """Tanpura drone + slow temple bells + sparse sitar plucks. Sacred + still."""
    m = MIDIFile(3)
    for t in range(3): m.addTempo(t, 0, BPM)
    # Sitar slow notes (program 104)
    m.addProgramChange(0, 0, 0, 104)
    pattern = [SA + 12, SA + 15, SA + 19, SA + 12, SA + 7, SA + 12]
    t = 0
    while t < TOTAL_BEATS:
        for i, n in enumerate(pattern):
            m.addNote(0, 0, n, t + i * 1.0, 0.9, 65)
        t += 6.0
    # Pad drone (88 = new age)
    m.addProgramChange(1, 1, 0, 88)
    t = 0
    while t < TOTAL_BEATS:
        m.addNote(1, 1, SA, t, 8.0, 55)
        m.addNote(1, 1, PA, t, 8.0, 48)
        t += 8.0
    # Temple bell (14 = tubular bells) every 4 beats
    m.addProgramChange(2, 2, 0, 14)
    t = 0
    while t < TOTAL_BEATS:
        m.addNote(2, 2, SA + 24, t, 2.0, 75)
        t += 8.0
    p = Path("/tmp/m_aarti.mid")
    with open(p, "wb") as f: m.writeFile(f)
    render(p, OUT_DIR / "1_mandir_aarti.mp3")


def option2_krishna_bansuri():
    """Bansuri-style flute melody + soft tabla + drone. Joyful, Krishna vibe."""
    m = MIDIFile(3)
    for t in range(3): m.addTempo(t, 0, BPM)
    # Flute (program 73)
    m.addProgramChange(0, 0, 0, 73)
    melody = [SA + 12, SA + 14, SA + 15, SA + 17, SA + 19, SA + 17, SA + 15, SA + 12,
              SA + 14, SA + 12, SA + 10, SA + 12]
    t = 0
    while t < TOTAL_BEATS:
        for i, n in enumerate(melody):
            m.addNote(0, 0, n, t + i * 0.5, 0.45, 80)
        t += 6.0
    # Drone (program 95 = halo pad)
    m.addProgramChange(1, 1, 0, 95)
    t = 0
    while t < TOTAL_BEATS:
        m.addNote(1, 1, SA, t, 6.0, 50)
        m.addNote(1, 1, PA, t, 6.0, 42)
        t += 6.0
    # Tabla — soft kick + hat (channel 9 = drums)
    t = 0
    while t < TOTAL_BEATS:
        m.addNote(2, 9, 36, t + 0.0, 0.25, 75)   # kick
        m.addNote(2, 9, 41, t + 1.0, 0.25, 60)   # low tom
        m.addNote(2, 9, 36, t + 2.0, 0.25, 75)
        m.addNote(2, 9, 38, t + 3.0, 0.25, 65)   # snare/clap
        t += 4.0
    p = Path("/tmp/m_bansuri.mid")
    with open(p, "wb") as f: m.writeFile(f)
    render(p, OUT_DIR / "2_krishna_bansuri.mp3")


def option3_shankh_naad():
    """Shankh-like long brass opening + drone + slow bell rings. Powerful, ritual."""
    m = MIDIFile(3)
    for t in range(3): m.addTempo(t, 0, BPM)
    # Brass (60 = French horn) sustained low — closest to shankh
    m.addProgramChange(0, 0, 0, 60)
    t = 0
    while t < TOTAL_BEATS:
        m.addNote(0, 0, SA - 12, t, 6.0, 80)      # low Sa
        m.addNote(0, 0, SA - 5, t + 6.0, 6.0, 75) # rise
        t += 12.0
    # Pad (89 = warm pad)
    m.addProgramChange(1, 1, 0, 89)
    t = 0
    while t < TOTAL_BEATS:
        m.addNote(1, 1, SA, t, 8.0, 50)
        m.addNote(1, 1, PA, t, 8.0, 45)
        t += 8.0
    # Bell rings on big beats
    m.addProgramChange(2, 2, 0, 14)
    t = 0
    while t < TOTAL_BEATS:
        m.addNote(2, 2, SA + 24, t, 3.0, 70)
        t += 12.0
    p = Path("/tmp/m_shankh.mid")
    with open(p, "wb") as f: m.writeFile(f)
    render(p, OUT_DIR / "3_shankh_naad.mp3")


def option4_bhakti_beat():
    """Sitar arpeggio + bell + tabla rhythm. Energetic devotional."""
    m = MIDIFile(3)
    for t in range(3): m.addTempo(t, 0, BPM)
    # Sitar (104)
    m.addProgramChange(0, 0, 0, 104)
    arp = [SA + 12, SA + 15, SA + 19, SA + 24, SA + 19, SA + 15]
    t = 0
    while t < TOTAL_BEATS:
        for i, n in enumerate(arp):
            m.addNote(0, 0, n, t + i * 0.5, 0.45, 70)
        t += 3.0
    # Tanpura drone (89)
    m.addProgramChange(1, 1, 0, 89)
    t = 0
    while t < TOTAL_BEATS:
        m.addNote(1, 1, SA, t, 4.0, 55)
        m.addNote(1, 1, PA, t, 4.0, 48)
        t += 4.0
    # Tabla
    t = 0
    while t < TOTAL_BEATS:
        m.addNote(2, 9, 36, t + 0.0, 0.2, 90)
        m.addNote(2, 9, 38, t + 1.0, 0.2, 70)
        m.addNote(2, 9, 36, t + 2.0, 0.2, 90)
        m.addNote(2, 9, 41, t + 2.5, 0.2, 60)
        m.addNote(2, 9, 38, t + 3.0, 0.2, 70)
        t += 4.0
    p = Path("/tmp/m_bhakti.mid")
    with open(p, "wb") as f: m.writeFile(f)
    render(p, OUT_DIR / "4_bhakti_beat.mp3")


if __name__ == "__main__":
    option1_mandir_aarti()
    option2_krishna_bansuri()
    option3_shankh_naad()
    option4_bhakti_beat()
    print("DONE — check data/music/options/")
