"""Hook image + smooth crossfades (user feedback 2026-10-26).

"starting me jo ek hi photo zoom in zoom out kr rhe wo bilkool abrupt sa lg
rha" — the sync-safe "cuts" opener punched into the same picture three times.
The fix the user asked for: give the HOOK its own picture, and crossfade every
change. Plus: in the Durga reel the goddess was cut off at the frame edge.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import script_writer as sw  # noqa: E402
from pipeline.assembler import _effective_opener, _line_synced_durations, _xfade_plan  # noqa: E402
from pipeline.utils import dedupe_script_narration, load_config  # noqa: E402


def _w(pairs):
    return [{"text": t, "start": s, "end": s + 0.3} for t, s in pairs]


SCRIPT = {"hook": "Every god gave Durga.", "body": ["Shiva gave.", "Vishnu gave much.", "She rose."],
          "cta": "Comment it.", "hook_image": True}
BOUNDS = _w([("Every", 0.0), ("god", 0.4), ("gave", 0.8), ("Durga.", 1.2),
             ("Shiva", 2.0), ("gave.", 2.5), ("Vishnu", 4.0), ("gave", 4.5), ("much.", 5.0),
             ("She", 7.0), ("rose.", 7.5), ("Comment", 8.5), ("it.", 9.0)])


# ── line sync with a hook picture ────────────────────────────────────────────

def test_hook_image_covers_only_the_hook():
    d = _line_synced_durations(SCRIPT, BOUNDS, 4, 10.0)
    starts = [round(sum(d[:i]), 2) for i in range(4)]
    assert starts == [0.0, 2.0, 4.0, 7.0]
    assert sum(d) == pytest.approx(10.0)


def test_hook_image_flag_with_wrong_count_falls_back():
    assert _line_synced_durations(SCRIPT, BOUNDS, 3, 10.0) is None


# ── crossfade plan keeps every picture on its line ───────────────────────────

def test_xfade_plan_keeps_starts_and_total():
    durs = [2.0, 2.0, 3.0, 3.0]
    lens, offsets, fade = _xfade_plan(durs, 0.45)
    assert offsets == pytest.approx([2.0, 4.0, 7.0])          # next picture starts on its line
    assert lens[:-1] == pytest.approx([d + fade for d in durs[:-1]])
    assert lens[-1] == pytest.approx(3.0)
    total = offsets[-1] + lens[-1]
    assert total == pytest.approx(sum(durs))                  # narration length unchanged


def test_xfade_plan_shrinks_fade_for_short_scenes():
    lens, offsets, fade = _xfade_plan([0.6, 2.0], 0.45)
    assert fade <= 0.3


def test_xfade_plan_single_scene():
    assert _xfade_plan([5.0], 0.45) == ([5.0], [], 0.0)


# ── opener ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("cfg_opener,synced,hook,expected", [
    ("ramp", True, True, "none"),     # hook picture = the new frame inside 3s; no punch-ins
    ("ramp", True, False, "none"),    # never the abrupt punch-ins on a synced reel
    ("ramp", False, False, "ramp"),   # no sync available -> unchanged legacy behaviour
    ("cuts", False, False, "cuts"),   # explicitly configured -> unchanged
    ("images", False, False, "images"),
    ("", True, False, ""),
])
def test_effective_opener(cfg_opener, synced, hook, expected):
    assert _effective_opener(cfg_opener, synced, hook) == expected


# ── script: hook_visual becomes picture 0 ────────────────────────────────────

def _fake(hook_visual=True):
    s = {"title": "Every God Gave Durga Their Weapon 🔱", "hook": "Every god gave Durga their weapon.",
         "hook_roman": "Every god gave Durga their weapon.",
         "body": ["Shiva gave Durga his trident.", "Vishnu gave her his chakra.",
                  "Indra gave his thunderbolt.", "Agni gave his spear.", "She rose."],
         "cta": "Which weapon guards you? Comment it.", "cta_roman": "Which weapon guards you? Comment it.",
         "fb_comment": "x", "character_bible": [], "description": "Durga.", "hashtags": ["#Durga"],
         "visuals": ["Shiva handing his trident to Durga", "Vishnu presenting the chakra to Durga",
                     "Indra offering the vajra to Durga", "Agni offering a spear to Durga",
                     "Durga rising with all weapons"]}
    s["body_roman"] = list(s["body"])
    if hook_visual:
        s["hook_visual"] = "Durga in full glory on her lion, all the gods behind her"
    return s


@pytest.fixture
def gom():
    return load_config("godmind")


def test_write_script_prepends_hook_visual(gom, monkeypatch):
    monkeypatch.setattr(sw, "load_config", lambda *a, **k: gom)
    monkeypatch.setattr(sw, "_claude", lambda *a, **k: json.dumps(_fake()))
    monkeypatch.setenv("REEL_FORMAT_INDEX", "2")
    s = sw.write_script({"title": "Durga weapons", "kind": "viral"}, "ctx")
    assert s["hook_image"] is True
    assert s["visuals"][0].startswith("Durga in full glory")
    assert len(s["visuals"]) == len(s["body"]) + 1


def test_write_script_without_hook_visual_is_unchanged(gom, monkeypatch):
    monkeypatch.setattr(sw, "load_config", lambda *a, **k: gom)
    monkeypatch.setattr(sw, "_claude", lambda *a, **k: json.dumps(_fake(hook_visual=False)))
    monkeypatch.setenv("REEL_FORMAT_INDEX", "2")
    s = sw.write_script({"title": "Durga weapons", "kind": "viral"}, "ctx")
    assert not s.get("hook_image")
    assert len(s["visuals"]) == len(s["body"])


def test_format_prompt_asks_for_hook_visual(monkeypatch):
    monkeypatch.setenv("REEL_FORMAT_INDEX", "0")
    p = sw._build_user_prompt({"title": "x", "kind": "viral"}, "ctx", 6, "godmind")
    assert "hook_visual" in p


def test_other_niche_prompt_has_no_hook_visual(monkeypatch):
    monkeypatch.setenv("REEL_FORMAT_INDEX", "0")
    assert "hook_visual" not in sw._build_user_prompt({"title": "x", "kind": "viral"}, "ctx", 6, "ancient")


def test_hook_visual_missing_the_hook_god_is_rejected(gom):
    fmt = next(f for f in gom["llm"]["formats"] if f["key"] == "darshan")
    s = _fake()
    s["hook_visual"] = "a golden lotus in the cosmos"
    assert "hook_visual" in sw._format_violation(s, fmt)


# ── dedupe keeps the hook picture in step ────────────────────────────────────

def test_dedupe_with_hook_image_keeps_visuals_in_step():
    s = {"hook": "Every god gave Durga a weapon.", "hook_image": True,
         "body": ["Every god gave Durga a weapon.", "Shiva gave his trident.", "She rose."],
         "visuals": ["HOOK", "dup", "shiva", "rose"]}
    dedupe_script_narration(s)
    assert s["body"] == ["Shiva gave his trident.", "She rose."]
    assert s["visuals"] == ["HOOK", "shiva", "rose"]


# ── config ───────────────────────────────────────────────────────────────────

def test_config_turns_on_hook_image_and_crossfade(gom):
    assert gom["video"]["hook_image"] is True
    assert 0.2 <= float(gom["video"]["crossfade"]) <= 0.6


def test_config_keeps_both_figures_inside_the_frame(gom):
    assert "fully inside the frame" in gom["llm"]["image_style_guidance"]


def test_other_niches_have_no_crossfade():
    for n in ("ancient", "moneurons"):
        assert not load_config(n).get("video", {}).get("crossfade")
