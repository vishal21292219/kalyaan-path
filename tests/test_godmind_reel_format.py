"""GoM short-reel format (2026-10-25 FB audit).

The audit found: follows track views (r=0.91), 59% of viewers leave inside 3s,
the median watch is 14s on a ~76s reel, 70/82 hooks were the same 2nd-person
"You…" line, and the real followers are 35-54 Hindu diaspora, not the 18-40
Western seeker the persona was written for. These tests pin the fix:
short reels, three rotating formats, a short spoken CTA, and the real audience.
Every other niche must behave exactly as before.

Run:  .venv/bin/python -m pytest tests -q
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import script_writer as sw  # noqa: E402
from pipeline.utils import load_config  # noqa: E402

NICHES = sorted(p.stem for p in (ROOT / "configs").glob("*.yaml"))
OTHER_NICHES = [n for n in NICHES if n != "godmind"]
FORMAT_KEYS = ["typology", "verse", "darshan"]


@pytest.fixture
def gom():
    return load_config("godmind")


# ── config ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("niche", NICHES)
def test_every_config_still_loads(niche):
    cfg = load_config(niche)
    assert isinstance(cfg, dict) and cfg["niche"]


def test_persona_targets_the_real_audience(gom):
    persona = gom["llm"]["persona"]
    assert "18-40" not in persona
    assert "diaspora" in persona.lower()
    assert "35" in persona


def test_persona_no_longer_mandates_a_you_hook(gom):
    persona = gom["llm"]["persona"]
    assert "hook = open on the VIEWER'S inner pain/feeling in 2nd person" not in persona
    assert 'Line 1: A pain-first hook in 2nd person ("you…")' not in gom["llm"]["content_spec"]


def test_three_formats_defined_in_order(gom):
    formats = gom["llm"]["formats"]
    assert [f["key"] for f in formats] == FORMAT_KEYS
    for f in formats:
        assert len(f["brief"].split()) >= 30, f"{f['key']} brief is too thin"


def test_verse_format_forbids_invented_citations(gom):
    verse = next(f for f in gom["llm"]["formats"] if f["key"] == "verse")
    assert "only cite" in verse["brief"].lower()


def test_reel_length_is_short(gom):
    llm = gom["llm"]
    assert llm.get("length_spec", "").strip()
    assert int(llm["body_word_cap"]) <= 80
    assert int(llm["cta_word_cap"]) <= 16
    assert int(gom["images"]["num_per_reel"]) <= 7


# ── format rotation ──────────────────────────────────────────────────────────

def test_format_rotates_by_batch_index(gom, monkeypatch):
    keys = []
    for i in range(6):
        monkeypatch.setenv("REEL_FORMAT_INDEX", str(i))
        keys.append(sw.pick_format(gom, {"title": "anything"})["key"])
    assert keys == FORMAT_KEYS * 2


def test_format_without_index_is_stable_per_title(gom, monkeypatch):
    monkeypatch.delenv("REEL_FORMAT_INDEX", raising=False)
    a = sw.pick_format(gom, {"title": "Why Shiva drank the poison"})
    b = sw.pick_format(gom, {"title": "Why Shiva drank the poison"})
    assert a["key"] == b["key"] and a["key"] in FORMAT_KEYS


def test_bad_index_falls_back_instead_of_crashing(gom, monkeypatch):
    monkeypatch.setenv("REEL_FORMAT_INDEX", "not-a-number")
    assert sw.pick_format(gom, {"title": "x"})["key"] in FORMAT_KEYS


@pytest.mark.parametrize("niche", OTHER_NICHES)
def test_other_niches_get_no_format(niche, monkeypatch):
    monkeypatch.setenv("REEL_FORMAT_INDEX", "1")
    assert sw.pick_format(load_config(niche), {"title": "x"}) is None


# ── prompts ──────────────────────────────────────────────────────────────────

TOPIC = {"title": "The God Who Was Left Unfinished", "kind": "viral",
         "hook": "You keep waiting to feel complete before you let yourself rest."}


def test_user_prompt_carries_the_format_for_godmind(monkeypatch):
    monkeypatch.setenv("REEL_FORMAT_INDEX", "1")
    prompt = sw._build_user_prompt(TOPIC, "ctx", 6, "godmind")
    assert "FORMAT FOR THIS REEL: VERSE" in prompt
    # The topic's own "You…" hook is now an angle, not a forced opening line.
    assert "Open body[0] on this exact dramatic point" not in prompt
    assert TOPIC["hook"] in prompt


@pytest.mark.parametrize("niche", OTHER_NICHES)
def test_user_prompt_unchanged_for_other_niches(niche, monkeypatch):
    monkeypatch.setenv("REEL_FORMAT_INDEX", "1")
    prompt = sw._build_user_prompt(TOPIC, "ctx", 6, niche)
    assert "FORMAT FOR THIS REEL" not in prompt
    assert "Open body[0] on this exact dramatic point" in prompt


def test_system_prompt_has_short_length_override(gom):
    system = sw._build_system_prompt(gom, 6)
    assert "LENGTH OVERRIDE" in system
    assert gom["llm"]["length_spec"].strip()[:40] in system


# ── spoken CTA ───────────────────────────────────────────────────────────────

def test_trim_cta_keeps_whole_sentences_under_cap():
    cta = ("Which one runs you right now: Tamas, Rajas or Sattva? Comment it. "
           "That's one god inside you named, and there are many more parts of you "
           "still waiting to be met, so follow Gods of the Mind.")
    out = sw._trim_cta(cta, 14)
    assert out == "Which one runs you right now: Tamas, Rajas or Sattva? Comment it."
    assert len(out.split()) <= 14


def test_trim_cta_keeps_first_sentence_even_if_long():
    cta = "One single very long sentence that runs well past the cap without any stop at all"
    assert sw._trim_cta(cta, 5) == cta


def test_trim_cta_leaves_short_cta_alone():
    assert sw._trim_cta("Shiva or Vishnu? Comment it.", 14) == "Shiva or Vishnu? Comment it."


# ── write_script end to end, LLM mocked (no network, no spend) ───────────────

def _fake_script(n_lines=12, words=10):
    body = [" ".join(["word"] * (words - 1)) + f" line{i}." for i in range(n_lines)]
    return {
        "title": "Krishna Named Four Kinds of Devotees 🕉️",
        "hook": "Krishna said four kinds of people come to God.",
        "hook_roman": "Krishna said four kinds of people come to God.",
        "body": body, "body_roman": list(body),
        "cta": ("Which of the four are you right now? Comment it. That's one god "
                "inside you, and many more are waiting, so follow Gods of the Mind."),
        "cta_roman": ("Which of the four are you right now? Comment it. That's one god "
                      "inside you, and many more are waiting, so follow Gods of the Mind."),
        "fb_comment": "x", "visuals": [f"Krishna scene {i}" for i in range(n_lines)],
        "character_bible": [], "description": "Krishna said four kinds.", "hashtags": ["#Krishna"],
    }


def test_write_script_godmind_is_short_and_synced(gom, monkeypatch):
    monkeypatch.setattr(sw, "load_config", lambda *a, **k: gom)
    monkeypatch.setattr(sw, "_claude", lambda *a, **k: json.dumps(_fake_script()))
    monkeypatch.setenv("REEL_FORMAT_INDEX", "0")
    s = sw.write_script({"title": "Four kinds of devotees", "kind": "viral"}, "ctx")
    body_words = sum(len(l.split()) for l in s["body"])
    assert body_words <= int(gom["llm"]["body_word_cap"])
    assert len(s["visuals"]) == len(s["body"]) == len(s["body_roman"])
    assert len(s["cta"].split()) <= int(gom["llm"]["cta_word_cap"])
    assert s["cta_roman"] == s["cta"]
    spoken = len(s["hook"].split()) + body_words + len(s["cta"].split())
    assert spoken / 2.3 <= 40, f"~{spoken / 2.3:.0f}s spoken — not a short reel"


def test_write_script_other_niche_cta_untouched(monkeypatch):
    cfg = load_config("ancient")
    monkeypatch.setattr(sw, "load_config", lambda *a, **k: cfg)
    fake = _fake_script(n_lines=8)
    monkeypatch.setattr(sw, "_claude", lambda *a, **k: json.dumps(fake))
    monkeypatch.setattr(sw, "_gemini", lambda *a, **k: json.dumps(fake))
    s = sw.write_script({"title": "Göbekli Tepe", "kind": "viral"}, "ctx")
    assert s["cta"] == fake["cta"]


# ── batch wiring ─────────────────────────────────────────────────────────────

def test_batch_reels_passes_format_index():
    spec = importlib.util.spec_from_file_location("batch_reels", ROOT / "scripts/batch_reels.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    env = mod.reel_env(4, "2026-10-28T19:00:00Z")
    assert env["REEL_FORMAT_INDEX"] == "4"
    assert env["ACTIVE_NICHE"] == "godmind"
    assert env["PUBLISH_AT_ISO"] == "2026-10-28T19:00:00Z"


# ── format validator (added after the first live run, 2026-10-25) ────────────
# Live Claude output for the three formats: the VERSE reel cited "the Devi
# Bhagavata" (not a Gita/Upanishad verse) in 82 words, and the DARSHAN reel
# opened on a psychology line with no deity. These pin the validator.

def _fmt(gom, key):
    return next(f for f in gom["llm"]["formats"] if f["key"] == key)


def _s(hook, body, cta="Which one are you? Comment it.", desc=""):
    return {"hook": hook, "body": body, "cta": cta, "description": desc or hook}


def test_each_format_has_a_word_budget(gom):
    for f in gom["llm"]["formats"]:
        assert 20 <= int(f["max_words"]) <= 80, f["key"]


def test_verse_without_gita_or_upanishad_citation_is_rejected(gom):
    bad = _s("Kali is not the goddess of destruction.",
             ["The Devi Bhagavata says she cuts away what cannot flower.",
              "You are being cleared."])
    assert "citation" in sw._format_violation(bad, _fmt(gom, "verse"))


def test_verse_with_real_citation_passes(gom):
    ok = _s("No one ever told you the truth about death.",
            ["The Bhagavad Gita 2.20 says the soul is never born.",
             "It never dies. It only changes bodies,",
             "the way you change clothes."],
            cta="Body or soul — which are you? Tell us below.")
    assert sw._format_violation(ok, _fmt(gom, "verse")) is None


def test_verse_citation_in_description_counts(gom):
    ok = _s("God is not sitting in the sky, waiting to judge you.",
            ["The Upanishads said it in three words.", "Tat tvam asi.",
             "You are That."],
            desc="God is not in the sky. — Chandogya Upanishad 6.8.7")
    assert sw._format_violation(ok, _fmt(gom, "verse")) is None


def test_darshan_hook_must_name_a_famous_deity(gom):
    bad = _s("Everyone thinks you're calm because nothing touches you.",
             ["Krishna stood inside the battle.", "And he smiled."])
    assert "deity" in sw._format_violation(bad, _fmt(gom, "darshan"))
    ok = _s("Every god gave Durga a weapon.",
            ["Shiva gave the trident.", "Vishnu gave the discus.", "She needed all of them."])
    assert sw._format_violation(ok, _fmt(gom, "darshan")) is None


def test_over_budget_is_rejected(gom):
    verse = _fmt(gom, "verse")
    long_body = ["The Bhagavad Gita 2.47 says act without clinging to the fruit of action."] * 8
    assert "words" in sw._format_violation(_s("Stop chasing results.", long_body), verse)


def test_typology_needs_a_choice_in_the_cta(gom):
    bad = _s("You don't have one mind. You have three.",
             ["Tamas sleeps.", "Rajas runs.", "Sattva sees."], cta="Follow for more.")
    assert "choice" in sw._format_violation(bad, _fmt(gom, "typology"))


def test_write_script_regenerates_on_format_violation(gom, monkeypatch):
    bad = _fake_script(n_lines=3, words=8)
    bad["hook"] = bad["hook_roman"] = "Kali is not the goddess of destruction."
    bad["body"] = bad["body_roman"] = ["The Devi Bhagavata says she clears the way.",
                                       "You are not broken.", "You are being cleared."]
    bad["description"] = bad["hook"]
    good = json.loads(json.dumps(bad))
    good["body"] = good["body_roman"] = ["The Bhagavad Gita 2.20 says the soul never dies.",
                                         "It only changes bodies.", "You are the one inside."]
    good["visuals"] = ["Krishna 1", "Krishna 2", "Krishna 3"]
    good["cta"] = good["cta_roman"] = "Body or soul — which are you? Comment it."
    calls = []

    def fake_claude(system, user, model):
        calls.append(user)
        return json.dumps(bad if len(calls) == 1 else good)

    monkeypatch.setattr(sw, "load_config", lambda *a, **k: gom)
    monkeypatch.setattr(sw, "_claude", fake_claude)
    monkeypatch.setenv("REEL_FORMAT_INDEX", "1")  # verse
    s = sw.write_script({"title": "Death", "kind": "viral"}, "ctx")
    assert len(calls) == 2
    assert "REJECTED" in calls[1] and "citation" in calls[1]
    assert "Gita 2.20" in s["body"][0] and len(s["body"]) == 3


def test_write_script_ships_after_two_failed_regenerations(gom, monkeypatch):
    bad = _fake_script(n_lines=3, words=8)
    bad["body"] = bad["body_roman"] = ["The Devi Bhagavata says so.", "Two.", "Three."]
    bad["visuals"] = ["a", "b", "c"]
    calls = []
    monkeypatch.setattr(sw, "load_config", lambda *a, **k: gom)
    monkeypatch.setattr(sw, "_claude", lambda s, u, m: calls.append(u) or json.dumps(bad))
    monkeypatch.setenv("REEL_FORMAT_INDEX", "1")
    s = sw.write_script({"title": "Death", "kind": "viral"}, "ctx")  # must not raise
    assert len(calls) == 3 and s["body"]


@pytest.mark.parametrize("niche", OTHER_NICHES)
def test_other_niches_have_no_format_check(niche, monkeypatch):
    monkeypatch.setenv("REEL_FORMAT_INDEX", "1")
    assert sw.pick_format(load_config(niche), {"title": "x"}) is None


# ── verified-verse allowlist (2nd live run: "Gita 18.44 says act with total
#    excellence" — 18.44 is about the duties of vaishyas and shudras) ──────────

def test_verse_format_carries_a_verified_verse_list(gom):
    verses = _fmt(gom, "verse")["verses"]
    assert len(verses) >= 20
    refs = {v["ref"] for v in verses}
    assert {"Bhagavad Gita 2.20", "Bhagavad Gita 2.47", "Chandogya Upanishad 6.8.7"} <= refs
    for v in verses:
        assert len(v["meaning"].split()) >= 6, v["ref"]


def test_verse_citing_a_number_outside_the_list_is_rejected(gom):
    bad = _s("Stop calling it overachieving.",
             ["Bhagavad Gita 18.44 says act with total excellence.", "That is your nature."])
    assert "citation" in sw._format_violation(bad, _fmt(gom, "verse"))


def test_verse_naming_the_gita_without_a_number_is_rejected(gom):
    bad = _s("Stop calling it overachieving.",
             ["The Gita says act with excellence.", "That is your nature."])
    assert "citation" in sw._format_violation(bad, _fmt(gom, "verse"))


def test_user_prompt_lists_the_verified_verses_for_verse_format(monkeypatch):
    monkeypatch.setenv("REEL_FORMAT_INDEX", "1")
    prompt = sw._build_user_prompt(TOPIC, "ctx", 6, "godmind")
    assert "Bhagavad Gita 2.20" in prompt and "Chandogya Upanishad 6.8.7" in prompt


def test_user_prompt_has_no_verse_list_for_other_formats(monkeypatch):
    monkeypatch.setenv("REEL_FORMAT_INDEX", "0")
    assert "Chandogya Upanishad 6.8.7 —" not in sw._build_user_prompt(TOPIC, "ctx", 6, "godmind")


def test_darshan_accepts_indra(gom):
    ok = _s("Indra, king of heaven, feared a sitting sage more than any army.",
            ["He sent storms.", "He sent temptation.", "The sage did not move."])
    assert sw._format_violation(ok, _fmt(gom, "darshan")) is None


# ── render run fixes (verse render 2026-10-25: 2 body lines = 2 images = first
#    cut at 7.85s, ramp opener skipped; a "Gita 2:20"-style citation misread) ──

def test_verse_asks_for_three_body_lines(gom):
    assert "exactly 3 lines" in _fmt(gom, "verse")["brief"]


def test_verse_with_two_body_lines_is_rejected(gom):
    two = _s("Stop fearing death.",
             ["Bhagavad Gita 2.20: the soul is never born and never dies.",
              "You are the one who wears the body."])
    assert "lines" in sw._format_violation(two, _fmt(gom, "verse"))


def test_verse_with_three_body_lines_passes(gom):
    four = _s("Stop fearing death.",
              ["Bhagavad Gita 2.20: the soul is never born.",
               "It never dies. It only changes bodies.",
               "You are the one who wears the body."],
              cta="Body or soul? Comment it.")
    assert sw._format_violation(four, _fmt(gom, "verse")) is None


@pytest.mark.parametrize("written", [
    "Bhagavad Gita 2:20", "Gita 2.20", "Bhagavad Gita (2.20)", "Bhagavad Gita, 2.20",
    "Bhagavad Gita chapter 2, verse 20", "Gita Chapter 2 Verse 20",
])
def test_citation_spellings_normalise(written):
    assert ("gita", "2.20") in sw._citations(written)


# ── debug run 2026-10-25: "gita 220" came from the hashtag #Gita220 in the
#    description, and 4 short body lines naturally land at ~55 words ─────────

def test_hashtags_are_not_citations():
    assert sw._citations("Bhagavad Gita 2.20 #Gita220 #BhagavadGita220 #SanatanDharma") == {("gita", "2.20")}


def test_verse_with_hashtag_number_passes(gom):
    ok = _s("You have never actually died.",
            ["Bhagavad Gita 2.20: the soul is never born.",
             "It is not killed when the body is killed.",
             "Your fear is of something that cannot happen."],
            cta="Body or soul? Comment it.",
            desc="Bhagavad Gita 2.20 🕉️\n#GodsOfTheMind #Gita220 #SoulNeverDies")
    assert sw._format_violation(ok, _fmt(gom, "verse")) is None


def test_verse_budget_fits_three_short_lines(gom):
    three_lines = _s("You have never actually died, not even once.",
            ["Bhagavad Gita 2.20: the soul is never born.",
             "It is not killed when the body is killed.",
             "Your fear is of something that cannot happen."],
            cta="Body or soul — which are you? Comment it.")
    assert sw._format_violation(three_lines, _fmt(gom, "verse")) is None


def test_verse_over_budget_is_rejected(gom):
    long = _s("You have never actually died, not even once, in all your lives.",
              ["Bhagavad Gita 2.20: the soul is never born and it never dies at all.",
               "It is not killed when the body is killed on any battlefield anywhere.",
               "Your whole fear of death is the fear of something that cannot happen."],
              cta="Do you feel like the body, or the one who wears it? Comment it.")
    assert "words" in sw._format_violation(long, _fmt(gom, "verse"))


# ── one god per line (Durga render: "Shiva gave his trident. Vishnu gave his
#    Sudarshana Chakra. Indra gave his thunderbolt." was ONE body line = ONE
#    image, so two of the three gods never appeared on screen) ────────────────

def test_darshan_line_naming_two_other_gods_is_rejected(gom):
    bad = _s("Every god gave Durga a weapon.",
             ["The demons could not be defeated.",
              "Shiva gave his trident. Vishnu gave his Sudarshana Chakra.",
              "She rose in eighteen arms."])
    assert "one god per line" in sw._format_violation(bad, _fmt(gom, "darshan"))


def test_darshan_line_with_main_deity_plus_one_god_passes(gom):
    ok = _s("Every god gave Durga a weapon.",
            ["The demons could not be defeated.",
             "Shiva gave Durga his trident.",
             "Vishnu gave her the Sudarshana Chakra.",
             "Indra gave his thunderbolt.",
             "She rose in eighteen arms."])
    assert sw._format_violation(ok, _fmt(gom, "darshan")) is None


def test_darshan_brief_states_one_god_per_line(gom):
    assert "one god per line" in _fmt(gom, "darshan")["brief"].lower()


# ── visuals in step with lines (Durga render 2: visuals[0] drew the HOOK's
#    Durga, so every picture landed one line late — Shiva on screen while
#    "Vishnu gave his Sudarshana Chakra" was spoken) ─────────────────────────

def _sv(body, visuals):
    s = _s("Every god gave Durga their weapon.", body, cta="Which weapon guards you? Comment it.")
    s["visuals"] = visuals
    return s


def test_visuals_one_line_late_are_rejected(gom):
    bad = _sv(["Shiva placed his trident in her hands.", "Vishnu gave her his chakra.",
               "Indra gave his thunderbolt.", "She rose."],
              ["Durga ten arms filling the frame", "Shiva extending his trident",
               "Vishnu presenting the chakra", "Indra bowing with the vajra"])
    assert "visual" in sw._format_violation(bad, _fmt(gom, "darshan"))


def test_visuals_in_step_pass(gom):
    ok = _sv(["Shiva placed his trident in her hands.", "Vishnu gave her his chakra.",
              "Indra gave his thunderbolt.", "She rose."],
             ["Shiva extending his trident to Durga", "Vishnu presenting the chakra to Durga",
              "Indra bowing with the vajra before Durga", "Durga rising in eighteen arms"])
    assert sw._format_violation(ok, _fmt(gom, "darshan")) is None


def test_lines_without_a_named_god_are_not_checked(gom):
    ok = _sv(["Bhagavad Gita 2.20: Krishna told Arjuna the soul is never born.",
              "It is not killed when the body is killed.", "You are the one who wears the body."],
             ["Krishna on the chariot teaching Arjuna", "a warrior's armour falling away, light rising",
              "Krishna's hand over Arjuna's heart"])
    ok["hook"] = "Stop fearing death."
    ok["description"] = "Bhagavad Gita 2.20"
    assert sw._format_violation(ok, _fmt(gom, "verse")) is None


def test_darshan_one_god_rule_counts_varuna_and_agni(gom):
    bad = _s("Every god gave Durga their weapon.",
             ["Shiva gave his trident.", "Vishnu gave his chakra.",
              "Indra gave his thunderbolt, Varuna his conch.", "She rose."])
    assert "one god per line" in sw._format_violation(bad, _fmt(gom, "darshan"))
