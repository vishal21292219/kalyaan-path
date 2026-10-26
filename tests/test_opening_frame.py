"""Opening frame = FB thumbnail (2026-10-26: "Thumbnails, opening screen hooks
sab top notch hona chaiye"). The viral formula from the audit: a deity fills the
first frame with 2–4 bold words on top; authority named on screen; a choice to
self-sort; verse reels under ~15s. Earlier hook card (removed 2026-06-23) sat on
the deity's face and repeated the spoken hook — so this one is short, sits in
the top band the hook picture leaves open, and is NOT the spoken line."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import assembler as asm  # noqa: E402
from pipeline import script_writer as sw  # noqa: E402
from pipeline.utils import load_config  # noqa: E402


@pytest.fixture
def gom():
    return load_config("godmind")


def _fmt(gom, key):
    return next(f for f in gom["llm"]["formats"] if f["key"] == key)


def _s(hook, body, cta="Which one are you? Comment it.", **kw):
    d = {"hook": hook, "body": body, "cta": cta, "description": hook}
    d.update(kw)
    return d


# ── cover text ───────────────────────────────────────────────────────────────

def test_prompt_asks_for_cover_text_and_open_top_band(monkeypatch):
    monkeypatch.setenv("REEL_FORMAT_INDEX", "2")
    p = sw._build_user_prompt({"title": "x", "kind": "viral"}, "ctx", 6, "godmind")
    assert "cover_text" in p and "top third" in p


def test_cover_text_too_long_is_rejected(gom):
    s = _s("Every god gave Durga their weapon.", ["Shiva gave his trident.", "She rose.", "Maa."],
           cover_text="EVERY GOD GAVE HER A WEAPON")
    assert "cover_text" in sw._format_violation(s, _fmt(gom, "darshan"))


def test_cover_text_that_repeats_the_hook_is_rejected(gom):
    s = _s("Never born.", ["Bhagavad Gita 2.20: the soul is never born.", "It never dies.", "You are that."],
           cover_text="NEVER BORN", description="Bhagavad Gita 2.20")
    assert "cover_text" in sw._format_violation(s, _fmt(gom, "verse"))


def test_good_cover_text_passes(gom):
    s = _s("Every god gave Durga their weapon.", ["Shiva gave Durga his trident.",
           "Vishnu gave her his chakra.", "She rose."], cover_text="EVERY GOD. *ONE* GODDESS.")
    assert sw._format_violation(s, _fmt(gom, "darshan")) is None


def test_cover_words_marks_the_keyword():
    assert asm._cover_words("NEVER *BORN*") == [("NEVER", False), ("BORN", True)]
    assert asm._cover_words("you are THAT") == [("YOU", False), ("ARE", False), ("THAT", False)]


def test_cover_png_fits_the_top_band(tmp_path):
    from PIL import Image
    out = asm._render_cover_png("EVERY GOD. *ONE* GODDESS.", 1080, tmp_path / "c.png")
    w, h = Image.open(out).size
    assert w <= 1080 and h <= 1920 * 0.25


def test_cover_window_is_the_hook_picture():
    assert asm._cover_window({"hook_image": True}, [3.2, 4.0]) == (0.0, 3.2)
    assert asm._cover_window({}, [6.0, 4.0]) == (0.0, 2.5)


def _capture(monkeypatch):
    calls = []
    monkeypatch.setattr(asm, "_run", lambda cmd, cwd=None: calls.append(" ".join(map(str, cmd))))
    return calls


def test_brand_pass_draws_cover_and_citation(monkeypatch, tmp_path, gom):
    calls = _capture(monkeypatch)
    script = {"cover_text": "NEVER *BORN*", "citation": "Bhagavad Gita 2.20", "hook_image": True}
    asm._apply_brand_overlays(tmp_path / "in.mp4", tmp_path, "", gom, script, 1080, 1920, 15.0,
                              cover_end=3.0)
    joined = "\n".join(calls)
    assert "cover.png" in joined and "between(t\\,0.000\\,3.000)" in joined
    assert "citation.png" in joined and "between(t\\,12.000\\,15.000)" in joined


def test_brand_pass_without_cover_or_citation_is_unchanged(monkeypatch, tmp_path, gom):
    calls = _capture(monkeypatch)
    asm._apply_brand_overlays(tmp_path / "in.mp4", tmp_path, "", gom, {}, 1080, 1920, 15.0)
    joined = "\n".join(calls)
    assert "cover.png" not in joined and "citation.png" not in joined


# ── authority on screen: write_script records the verse it cited ────────────

def _verse_fake():
    body = ["Bhagavad Gita 2.20: the soul is never born.", "It does not die when the body dies.",
            "You are the one who wears the body."]
    return {"title": "The Gita Says You Never Die 🕉️", "hook": "Stop fearing death.",
            "hook_roman": "Stop fearing death.", "body": body, "body_roman": list(body),
            "cta": "Body or soul — which are you? Comment it.",
            "cta_roman": "Body or soul — which are you? Comment it.", "fb_comment": "x",
            "visuals": ["Krishna on the chariot teaching Arjuna", "a golden flame rising from armour",
                        "Krishna's hand over Arjuna's heart"],
            "character_bible": [{"name": "Krishna", "aliases": [], "look": "blue youthful god"}],
            "description": "Bhagavad Gita 2.20 🕉️", "hashtags": ["#Gita"],
            "hook_visual": "Krishna as charioteer, face lower half, open sky above",
            "cover_text": "YOU NEVER *DIED*"}


def test_write_script_records_citation_and_sarathi_ref(gom, monkeypatch):
    monkeypatch.setattr(sw, "load_config", lambda *a, **k: gom)
    monkeypatch.setattr(sw, "_claude", lambda *a, **k: json.dumps(_verse_fake()))
    monkeypatch.setenv("REEL_FORMAT_INDEX", "1")
    s = sw.write_script({"title": "Soul never dies", "kind": "viral"}, "ctx")
    assert s["citation"] == "Bhagavad Gita 2.20"
    assert s["character_bible"][0]["ref"] == "krishna_sarathi"


# ── self-sort in every format, no generic mood opener ───────────────────────

def test_verse_cta_without_a_choice_is_rejected(gom):
    s = _s("No one ever told you the truth about death.",
           ["Bhagavad Gita 2.20: the soul is never born.", "It never dies.", "It changes bodies."],
           cta="What are you really afraid of? Tell us below.", description="Bhagavad Gita 2.20")
    assert "choice" in sw._format_violation(s, _fmt(gom, "verse"))


@pytest.mark.parametrize("hook", ["You feel stuck and you don't know why.",
                                  "You are surrounded by noise, pressure and chaos.",
                                  "You have the power to move mountains — but you forgot."])
def test_generic_mood_openers_are_rejected(gom, hook):
    s = _s(hook, ["Shiva sat still.", "Durga rose.", "Kali danced."], cta="Shiva or Kali? Comment it.")
    assert "generic" in sw._format_violation(s, _fmt(gom, "darshan"))


def test_contradiction_you_opener_still_allowed(gom):
    s = _s("You are not one person — you are three forces at war.",
           ["Tamas pulls you down.", "Rajas drives you on.", "Sattva sees both."],
           cta="Tamas, Rajas or Sattva — which ran your day? Comment it.")
    assert sw._format_violation(s, _fmt(gom, "typology")) is None


# ── verse under ~15-20s: 3 lines + the hook picture ──────────────────────────

def test_verse_is_three_lines_and_short(gom):
    v = _fmt(gom, "verse")
    assert int(v["body_lines"]) == 3 and int(v["max_words"]) <= 40
    assert "exactly 3 lines" in v["brief"]


# ── image_gen picks the per-format reference ────────────────────────────────

def test_pinned_ref_name_prefers_existing_variant(tmp_path, monkeypatch):
    from pipeline import image_gen as ig
    refs = tmp_path / "assets/refs"
    refs.mkdir(parents=True)
    (refs / "krishna.jpg").write_bytes(b"x")
    monkeypatch.setattr(ig, "ROOT", tmp_path)
    assert ig._pinned_ref({"name": "Krishna", "ref": "krishna_sarathi"}).name == "krishna.jpg"
    (refs / "krishna_sarathi.jpg").write_bytes(b"x")
    assert ig._pinned_ref({"name": "Krishna", "ref": "krishna_sarathi"}).name == "krishna_sarathi.jpg"
    assert ig._pinned_ref({"name": "Shiva"}).name == "shiva.jpg"
