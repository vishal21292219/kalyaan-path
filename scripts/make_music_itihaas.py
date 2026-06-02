"""Royalty-free INDIAN-flavoured beds for Itihaasvani (synthesized → no copyright).
Distinct from TimeDecoders (which is Western orchestral). Indian instruments:
tanpura/sitar drone, shehnai, sarangi-ish strings, tabla (congas), bansuri.

Built with an ARC (sparse intro → building → climax ~40-45s → settle) so it
tracks a ~50-60s reel instead of feeling like a flat loop.

Outputs (mood-matched by pick_drone):
- data/music_itihaas/suspense_bed.mp3  → mystery/dread (default)
- data/music_itihaas/upbeat_bed.mp3    → wonder/achievement/glory

Run:  SOUNDFONT=/tmp/gm.sf2 python scripts/make_music_itihaas.py
"""
import os
import subprocess
from pathlib import Path

from midiutil import MIDIFile

ROOT = Path(__file__).resolve().parent.parent
SOUNDFONT = os.environ.get("SOUNDFONT", "/tmp/gm.sf2")
MUSIC_DIR = ROOT / "data" / "music_itihaas"
DURATION = 120

# GM programs
SITAR, SHEHNAI, FIDDLE, BANSURI, STRINGS = 104, 111, 110, 75, 49


def _arc_vel(t, beats, base, peak):
    """Velocity envelope: rise to a climax ~38% through, then ease — gives the
    track a build instead of a flat loop (climax lands ~45s of a 120s render,
    i.e. ~ the reveal zone of a short reel)."""
    frac = t / beats
    if frac < 0.38:
        v = base + (peak - base) * (frac / 0.38)
    else:
        v = peak - (peak - base) * 0.4 * ((frac - 0.38) / 0.62)
    return int(max(1, min(127, v)))


def _render(midi, out_mp3, af, gain="0.85"):
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
    """Dark Indian dread — tanpura drone + mournful shehnai + sarangi + slow
    tabla building. Raga-Bhairavi-ish minor (Sa=D)."""
    Sa, Pa, ga, ma, dha, SaH = 50, 57, 53, 55, 58, 62  # D, A, F(komal ga), G, Bb(komal dha), D'
    BPM = 70
    beats = DURATION * (BPM / 60)
    m = MIDIFile(5, deinterleave=False)
    for t in range(5):
        m.addTempo(t, 0, BPM)
    # Track 0: tanpura/sitar drone Sa+Pa (whole piece, soft)
    m.addProgramChange(0, 0, 0, SITAR)
    t = 0.0
    while t < beats:
        m.addNote(0, 0, Sa - 12, t, 4.0, 34)
        m.addNote(0, 0, Pa - 12, t, 4.0, 28)
        t += 4.0
    # Track 1: sarangi-ish sustained body (strings), enters ~6 beats
    m.addProgramChange(1, 1, 0, FIDDLE)
    t = 6.0
    while t < beats:
        m.addNote(1, 1, Sa, t, 6.0, _arc_vel(t, beats, 22, 46))
        t += 8.0
    # Track 2: mournful shehnai melody (the Indian suspense voice), enters ~16
    m.addProgramChange(2, 2, 0, SHEHNAI)
    phrase = [(Sa, 2), (ga, 1), (ma, 1), (ga, 2), (Sa, 2), (dha - 12, 2),
              (Sa, 1), (ma, 1), (Pa, 3)]
    t = 16.0
    while t < beats:
        for note, dur in phrase:
            if t >= beats:
                break
            m.addNote(2, 2, note, t, dur * 0.9, _arc_vel(t, beats, 30, 64))
            t += dur
        t += 4.0  # breath between phrases
    # Track 3: tabla (congas on ch9) — slow, density rises with the arc
    t = 12.0
    while t < beats:
        vel = _arc_vel(t, beats, 40, 90)
        m.addNote(3, 9, 64, t, 0.3, vel)            # low conga = dha
        m.addNote(3, 9, 63, t + 1.5, 0.3, vel - 12)  # hi conga = tin
        if t / beats > 0.3:                          # extra hits once built
            m.addNote(3, 9, 64, t + 2.5, 0.3, vel - 8)
        t += 4.0
    # Track 4: deep contrabass dread booms, sparse
    m.addProgramChange(4, 4, 0, 43)
    t = 8.0
    while t < beats:
        m.addNote(4, 4, Sa - 24, t, 1.4, _arc_vel(t, beats, 45, 75))
        t += 8.0
    _render(m, MUSIC_DIR / "suspense_bed.mp3",
            "lowpass=f=8500,loudnorm=I=-18:TP=-2:LRA=11,"
            "acompressor=threshold=0.3:ratio=3:attack=20:release=400")


def build_upbeat():
    """Energetic Indian epic — sitar hook + dhol/tabla drive + shehnai &
    bansuri + bright strings. D-major-ish, 'wonder/achievement'."""
    D3, Fs3, A3, D4, Fs4, A4, D5 = 50, 54, 57, 62, 66, 69, 74
    BPM = 98
    beats = DURATION * (BPM / 60)
    m = MIDIFile(6, deinterleave=False)
    for t in range(6):
        m.addTempo(t, 0, BPM)
    # Track 0: sitar arpeggio hook
    m.addProgramChange(0, 0, 0, SITAR)
    arp = [D4, Fs4, A4, D5, A4, Fs4]
    t = 0.0
    while t < beats:
        for i, n in enumerate(arp):
            m.addNote(0, 0, n, t + i * 0.5, 0.45, _arc_vel(t, beats, 55, 80))
        t += 3.0
    # Track 1: bright strings stabs (D major)
    m.addProgramChange(1, 1, 0, 48)
    t = 0.0
    while t < beats:
        for n in (D3, Fs3, A3):
            m.addNote(1, 1, n, t, 0.9, _arc_vel(t, beats, 40, 64))
            m.addNote(1, 1, n, t + 2.0, 0.9, _arc_vel(t, beats, 36, 58))
        t += 4.0
    # Track 2: shehnai lead melody, enters ~8
    m.addProgramChange(2, 2, 0, SHEHNAI)
    mel = [(A4, 2), (D5, 2), (Fs4, 1), (A4, 1), (D5, 4)]
    t = 8.0
    while t < beats:
        for note, dur in mel:
            if t >= beats:
                break
            m.addNote(2, 2, note, t, dur * 0.9, _arc_vel(t, beats, 40, 70))
            t += dur
        t += 2.0
    # Track 3: bansuri counter (sparse, high)
    m.addProgramChange(3, 3, 0, BANSURI)
    t = 24.0
    while t < beats:
        m.addNote(3, 3, D5, t, 2.0, _arc_vel(t, beats, 30, 55))
        t += 16.0
    # Track 4: bass groove
    m.addProgramChange(4, 4, 0, 33)
    t = 0.0
    while t < beats:
        m.addNote(4, 4, 38, t, 0.5, 80)
        m.addNote(4, 4, 38, t + 1.5, 0.5, 64)
        m.addNote(4, 4, 45, t + 2.5, 0.5, 72)
        t += 4.0
    # Track 5: DHOL/TABLA drive (ch9) — kick + conga + hats, density rises
    t = 0.0
    while t < beats:
        vel = _arc_vel(t, beats, 70, 110)
        m.addNote(5, 9, 36, t, 0.3, vel)             # dhol low
        m.addNote(5, 9, 64, t + 1.0, 0.3, vel - 18)   # conga
        m.addNote(5, 9, 36, t + 2.0, 0.3, vel - 6)
        m.addNote(5, 9, 63, t + 3.0, 0.3, vel - 18)
        for h in range(8):
            m.addNote(5, 9, 42, t + h * 0.5, 0.2, 48)
        t += 4.0
    _render(m, MUSIC_DIR / "upbeat_bed.mp3",
            "loudnorm=I=-16:TP=-1.5:LRA=10,"
            "acompressor=threshold=0.35:ratio=2.5:attack=15:release=250")


if __name__ == "__main__":
    build_suspense()
    build_upbeat()
