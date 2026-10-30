"""End card for the choice question (2026-10-30, user: "end me kuch accha sa
end kro — jo question pooch rhe ho usko acche se bnao").

The spoken CTA "A, or B — which X is yours?" becomes an on-screen card: the
question large, the options numbered, "Comment 1 or 2" — answering with a
digit is the cheapest comment there is. It gets its own picture when the
script carries one (cta_image), and the running captions stop while it shows.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import assembler as A  # noqa: E402


def test_two_option_cta_becomes_a_card():
    c = A.end_card_from_cta("Losing what you have, or never getting it — which fear is yours?")
    assert c == {"question": "Which fear is yours?",
                 "options": ["Losing what I have", "Never getting it"],
                 "prompt": "Type your number below."}


def test_three_option_cta():
    c = A.end_card_from_cta("Anger, desire or attachment — which one rules you right now? Comment it.")
    assert c["options"] == ["Anger", "Desire", "Attachment"]
    assert c["question"] == "Which one rules you right now?"
    assert c["prompt"] == "Type your number below."


def test_cta_without_choices_gets_no_card():
    assert A.end_card_from_cta("Follow for more.") is None
    assert A.end_card_from_cta("Which fear is yours?") is None


def _words(texts, step=0.5):
    return [{"text": w, "start": i * step, "end": i * step + 0.4} for i, w in enumerate(texts)]


S = {"hook": "You are not alone.", "body": ["He brings", "He keeps"],
     "cta": "Losing it, or never getting it — which?", "hook_image": True}
WORDS = _words("You are not alone. He brings He keeps Losing it, or never getting it — which?".split())


def test_cta_start_is_the_first_cta_word():
    # hook 4 words + body 2 + 2 = 8 words before the CTA → 8 * 0.5
    assert A._cta_start(S, WORDS) == 4.0


def test_cta_gets_its_own_picture_when_the_script_has_one():
    s = dict(S, cta_image=True)
    d = A._line_synced_durations(s, WORDS, n_images=4, total_duration=10.0)
    assert d is not None and len(d) == 4
    assert abs(sum(d[:3]) - 4.0) < 1e-6 and abs(d[3] - 6.0) < 1e-6


def test_without_cta_image_timing_is_unchanged():
    d = A._line_synced_durations(S, WORDS, n_images=3, total_duration=10.0)
    assert d is not None and len(d) == 3 and abs(sum(d) - 10.0) < 1e-6


def test_captions_stop_where_the_card_starts():
    ph = [{"text": "a", "start": 1.0, "end": 2.0}, {"text": "b", "start": 4.2, "end": 5.0}]
    assert [p["text"] for p in A._before_card(ph, 4.0)] == ["a"]
    assert A._before_card(ph, None) == ph


def test_card_png_renders(tmp_path):
    c = A.end_card_from_cta("Losing what you have, or never getting it — which fear is yours?")
    out = A._render_end_card_png(c, 1080, tmp_path / "card.png", citation="Bhagavad Gita 9.22")
    from PIL import Image
    im = Image.open(out)
    assert im.size[0] == 1080 and im.size[1] > 300 and im.mode == "RGBA"


def test_cta_words_never_join_a_running_caption():
    # 2026-10-30 render: "already holds it. Losing what you" sat on top of the card.
    w = [{"text": "holds", "start": 3.0, "end": 3.3}, {"text": "it.", "start": 3.3, "end": 3.6},
         {"text": "Losing", "start": 4.0, "end": 4.3}]
    assert [x["text"] for x in A._words_before_card(w, 4.0)] == ["holds", "it."]
    assert A._words_before_card(w, None) == w


def test_last_caption_window_ends_at_the_card():
    assert A._clip_to_card([(1.0, 2.0), (3.0, 4.9)], 4.0) == [(1.0, 2.0), (3.0, 4.0)]
    assert A._clip_to_card([(1.0, 2.0)], None) == [(1.0, 2.0)]


# 2026-10-30, user picked design "3": Krishna's question as a quote, options in
# the viewer's own voice ("I"), one quiet line each, "Type your number below."
def test_options_are_turned_into_the_viewers_own_voice():
    c = A.end_card_from_cta("Losing what you have, or never getting it — which fear is yours?")
    assert c["options"] == ["Losing what I have", "Never getting it"]
    assert c["prompt"] == "Type your number below."


def test_script_supplied_card_wins_over_the_parsed_cta():
    s = {"cta": "A, or B — which?", "end_card": {"question": "Tell me — which fear do you carry?",
                                                  "options": ["Losing what I have", "Never getting what I need"]}}
    c = A.end_card_for(s)
    assert c["question"] == "Tell me — which fear do you carry?" and len(c["options"]) == 2
    assert c["prompt"] == "Type your number below."


def test_writer_asks_for_the_card_and_its_picture():
    src = (ROOT / "pipeline/script_writer.py").read_text()
    assert '\\"end_card\\"' in src and '\\"cta_visual\\"' in src


def test_cta_visual_becomes_the_last_picture():
    from pipeline import script_writer as sw
    s = {"visuals": ["h", "a", "b"], "cta_visual": "Krishna portrait, face in the top third"}
    sw._attach_cta_visual(s, {"video": {"end_card": True}})
    assert s["visuals"][-1].startswith("Krishna portrait") and s["cta_image"] is True
    s2 = {"visuals": ["h"], "cta_visual": "x"}
    sw._attach_cta_visual(s2, {"video": {}})
    assert s2["visuals"] == ["h"] and not s2.get("cta_image")
