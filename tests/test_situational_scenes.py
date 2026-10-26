"""Story lines get their own situation, not the deity pasted in (2026-10-26).

User review: "tum har scene me bhagwaan ji ka image daal rhe ho, jaha situation
kuch or hai waha krishna bhagwaan murli ke sath dikh rhe hai, waha situational
image daalo". Root cause: _force_deity re-staged every scene without a deity
name around the lead deity (Arjuna's "the Gandiva slipped" became Krishna with a
flute), and the vision gate failed any frame no deity dominated, so even a
correct Arjuna frame was thrown away.

Kept from 2026-10-21: modern stock humans, silhouettes and empty landscapes are
still re-staged — the exemption is only for the script's own story characters.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import frame_check as fc  # noqa: E402
from pipeline import image_gen  # noqa: E402
from pipeline import script_writer  # noqa: E402

CFG = {"images": {"deity_blocks": {"krishna": "blue", "shiva": "ash", "yama": "buffalo"}}}
BIBLE = [{"name": "Arjuna", "aliases": ["Partha"], "look": "warrior"},
         {"name": "Krishna", "aliases": [], "look": "blue"}]
OK = {"facial_hair": False, "torso_covered": True, "is_child": False, "scene_match": 2,
      "form_ok": True, "garbled_text": False, "deity_undignified": False,
      "deity_dominant": False, "face_in_top_band": False}


def test_story_character_scene_is_not_restaged():
    v = ["Arjuna kneeling on the chariot floor, the Gandiva sliding from his hand"]
    assert image_gen._force_deity(v, CFG, story_names=image_gen._story_names(BIBLE, CFG)) == v


def test_alias_counts_as_the_story_character():
    v = ["Partha's hands trembling on the chariot rail"]
    assert image_gen._force_deity(v, CFG, story_names=image_gen._story_names(BIBLE, CFG)) == v


def test_relatable_scene_keeps_its_situation_and_gains_a_sacred_reference():
    # Follow-up the same day: "jaruri nhi hai ki image bhagwaan ji ki ho,
    # relatable and appropriate according to script koi bhi image daal skte ho
    # lekin bhagwan ke reference me". The line's own situation stays the subject;
    # the lead deity is present as a reference (symbol / murti / presence).
    v = ["Krishna on the chariot", "a man scrolling his phone alone in a dark room"]
    out = image_gen._force_deity(v, CFG, story_names=image_gen._story_names(BIBLE, CFG))
    assert out[0] == v[0]
    assert out[1].startswith(v[1])
    assert "krishna" in out[1].lower() and "dominant figure" not in out[1]


def test_hook_frame_still_shows_the_deity():
    # Frame 0 is the thumbnail: the deity stays the subject there.
    v = ["a man scrolling his phone alone in a dark room", "Krishna smiles"]
    out = image_gen._force_deity(v, CFG)
    assert "dominant figure" in out[0] and out[0].lower().startswith("krishna")


def test_hook_frame_index_needs_the_deity_others_do_not():
    assert image_gen._needs_deity(0, "a man alone", [], CFG) is True
    assert image_gen._needs_deity(3, "a man alone", [], CFG) is False
    assert image_gen._needs_deity(3, "Krishna smiles", [], CFG) is True


def test_deities_are_not_story_names():
    names = image_gen._story_names(BIBLE, CFG)
    assert "arjuna" in names and "partha" in names and "krishna" not in names


def test_story_frame_without_a_deity_passes_the_gate(monkeypatch):
    monkeypatch.setattr(fc, "inspect", lambda *a, **k: dict(OK))
    good, why = fc.check(Path("x.jpg"), "", "Arjuna drops his bow", require_deity=False)
    assert good, why


def test_deity_frame_still_needs_the_deity(monkeypatch):
    monkeypatch.setattr(fc, "inspect", lambda *a, **k: dict(OK))
    good, why = fc.check(Path("x.jpg"), "krishna", "Krishna speaks")
    assert not good and "dominates" in why[0]


def test_young_story_character_is_not_a_child_deity(monkeypatch):
    # Markandeya is sixteen; the "deity as a child" rule is about deities.
    monkeypatch.setattr(fc, "inspect", lambda *a, **k: {**OK, "is_child": True})
    assert fc.check(Path("x.jpg"), "", "Markandeya holds the linga", require_deity=False)[0]
    assert not fc.check(Path("x.jpg"), "krishna", "Krishna")[0]


def test_gita_scripts_get_the_charioteer_krishna_in_every_format():
    s = {"hook": "The greatest archer alive dropped his bow",
         "body": ["Arjuna saw his teachers at Kurukshetra"],
         "character_bible": [{"name": "Krishna"}, {"name": "Arjuna"}]}
    script_writer._gita_refs(s)
    assert s["character_bible"][0].get("ref") == "krishna_sarathi"
    assert "ref" not in s["character_bible"][1]


def test_non_gita_krishna_keeps_the_flute_ref():
    s = {"hook": "Krishna in Vrindavan", "body": ["the gopis heard the flute"],
         "character_bible": [{"name": "Krishna"}]}
    script_writer._gita_refs(s)
    assert "ref" not in s["character_bible"][0]


def test_writer_prompt_allows_story_frames_and_still_bans_stock():
    src = Path(script_writer.__file__).read_text()
    assert "EVERY visuals[] FRAME MUST SHOW THE DEITY" not in src
    assert "STORY LINE" in src and "stock-photo human" in src


# Same day, third message: "lekin reel me jab bhagwaan ki baat and unka koi msg
# ho to waha bhagwaan ki photo mandatory hai".
HAPPY = {"hook": "Krishna named three kinds of happiness — and one of them is slowly poisoning you.",
         "body": ["Sattvic joy feels hard at first — then becomes nectar.",
                  "The workout. The discipline. The thing you kept avoiding.",
                  "Rajasic joy feels sweet at first — then becomes poison.",
                  "The scroll. The craving. The pleasure that leaves you hollow."],
         "visuals": ["a golden sunrise over a mountain path",
                     "a young man lifting a heavy stone at dawn",
                     "a honey-dripping lotus with a dark shadow",
                     "a woman scrolling her phone in bed at night"]}


def test_teaching_lines_are_message_lines():
    assert script_writer._message_lines(HAPPY["body"]) == [0, 2]


def test_line_after_the_god_speaks_carries_his_message():
    body = ["Then Krishna spoke —", "arise, this weakness does not become you.", "Arjuna stood."]
    assert script_writer._message_lines(body) == [0, 1]


def test_message_lines_get_the_god_in_their_picture_others_keep_the_situation():
    s = {k: (list(v) if isinstance(v, list) else v) for k, v in HAPPY.items()}
    script_writer._enforce_deity_visuals(s)
    assert s["visuals"][0].lower().startswith("krishna") and "sunrise" in s["visuals"][0]
    assert s["visuals"][2].lower().startswith("krishna")
    assert s["visuals"][1] == HAPPY["visuals"][1]
    assert s["visuals"][3] == HAPPY["visuals"][3]


def test_arjuna_is_never_the_lead_god():
    s = {"hook": "Arjuna dropped his bow", "body": ["Arjuna said: I will not fight", "Arjuna wept"],
         "visuals": ["a bow on the floor", "a warrior kneeling"]}
    script_writer._enforce_deity_visuals(s)
    assert s["visuals"] == ["a bow on the floor", "a warrior kneeling"]


def test_gate_decides_on_the_original_line_not_the_added_sign():
    # The sign text names Krishna; deciding on it would fail every life frame.
    src = Path(image_gen.__file__).read_text()
    assert "_needs_deity(i, _orig[i]" in src
    out = image_gen._force_deity(["Krishna smiles", "a woman scrolling at night"], CFG)
    assert image_gen._deity_name(out[1], CFG) == "krishna"          # sign added
    assert image_gen._needs_deity(1, "a woman scrolling at night", [], CFG) is False


def test_writer_prompt_keeps_flaws_off_recognisable_deities():
    src = Path(script_writer.__file__).read_text()
    assert "FLAW LINE" in src and "UNNAMED mortal" in src
