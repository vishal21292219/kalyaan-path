"""Phrase-caption windows must never overlap (2026-10-25 darshan render showed
"Vishnu gave his Sudarshana Chakra." and "Indra gave his thunderbolt." on screen
together: each phrase started 0.05s early but the previous one ended only 0.02s
before the next word, and very short phrases were stretched to 0.4s)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.assembler import _phrase_windows  # noqa: E402

PHRASES = [
    {"start": 10.73, "end": 13.13},   # Vishnu gave his Sudarshana Chakra.
    {"start": 13.51, "end": 15.14},   # Indra gave his thunderbolt.
    {"start": 15.46, "end": 15.60},   # a one-word phrase
    {"start": 15.71, "end": 18.87},
]


def test_windows_never_overlap():
    w = _phrase_windows(PHRASES)
    for (s0, e0), (s1, e1) in zip(w, w[1:]):
        assert e0 <= s1, f"{e0} > {s1}"
        assert s0 < e0


def test_caption_persists_through_pauses():
    w = _phrase_windows(PHRASES)
    assert w[0][1] >= 13.4          # stays up through the 0.38s pause
    assert w[-1][1] >= 18.87 + 0.5  # last one lingers after the final word


def test_starts_slightly_before_the_word():
    w = _phrase_windows(PHRASES)
    assert abs(w[1][0] - 13.46) < 1e-6


def test_short_phrase_keeps_a_readable_minimum_when_there_is_room():
    w = _phrase_windows([{"start": 1.0, "end": 1.1}, {"start": 3.0, "end": 4.0}])
    assert w[0][1] - w[0][0] >= 0.4
