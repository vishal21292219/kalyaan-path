"""A line already ending in ? or ! must not get a period glued on (2026-10-30:
the CTA caption read "which fear is yours?." because _build_text appended '.')."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.tts import _build_text  # noqa: E402


def test_question_cta_keeps_its_question_mark_only():
    t = _build_text({"hook": "You are not alone.", "body": ["He brings what you lack"],
                     "cta": "Which fear is yours?"})
    assert t == "You are not alone. He brings what you lack. Which fear is yours?"


def test_mid_question_and_exclamation_are_not_followed_by_a_period():
    t = _build_text({"hook": "Why do you fear?", "body": ["Arise!"], "cta": "Comment it"})
    assert "?." not in t and "!." not in t and t.endswith("Comment it.")


# 2026-10-30, user picked voice "B": more expressive settings + a pause between
# lines, sent to ElevenLabs as <break> tags. The tags come back in the character
# alignment and must never become caption "words" (line sync counts words).
from pipeline.tts import _words_from_char_alignment  # noqa: E402


def test_pause_tags_between_lines_only_when_asked():
    s = {"hook": "You are not alone.", "body": ["He keeps it"], "cta": "Which one?"}
    assert "<break" not in _build_text(s)
    t = _build_text(s, pause=0.6)
    assert t == 'You are not alone. <break time="0.6s" /> He keeps it. <break time="0.6s" /> Which one?'


def test_break_tags_are_dropped_from_word_timings():
    text = 'You are alone. <break time="0.6s" /> He keeps it.'
    n = len(text)
    a = {"characters": list(text), "character_start_times_seconds": [i * 0.05 for i in range(n)],
         "character_end_times_seconds": [i * 0.05 + 0.04 for i in range(n)]}
    assert [w["text"] for w in _words_from_char_alignment(a)] == ["You", "are", "alone.", "He", "keeps", "it."]
