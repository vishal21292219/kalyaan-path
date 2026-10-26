"""The cover title sits in the top band of the hook picture; a face there gets
covered ("chera pe hi letter aa rha", 2026-10-26). The vision gate now checks
the hook picture for a face in the top 30% and regenerates it if so."""
import inspect as _inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import frame_check as fc  # noqa: E402
from pipeline import image_gen  # noqa: E402

OK = {"facial_hair": False, "torso_covered": True, "is_child": False, "scene_match": 2,
      "form_ok": True, "garbled_text": False, "deity_undignified": False, "deity_dominant": True}


def test_prompt_asks_about_the_top_band():
    assert "TOP 30%" in fc._PROMPT and "face_in_top_band" in fc._PROMPT


def test_face_in_band_fails_only_when_asked(monkeypatch):
    monkeypatch.setattr(fc, "inspect", lambda *a, **k: {**OK, "face_in_top_band": True})
    good, why = fc.check(Path("x.jpg"), "krishna", "scene", title_band=True)
    assert not good and "title band" in why[0]
    good, _ = fc.check(Path("x.jpg"), "krishna", "scene")
    assert good


def test_clear_band_passes(monkeypatch):
    monkeypatch.setattr(fc, "inspect", lambda *a, **k: {**OK, "face_in_top_band": False})
    assert fc.check(Path("x.jpg"), "krishna", "scene", title_band=True)[0]


def test_generate_images_takes_the_flag():
    assert "title_band_first" in _inspect.signature(image_gen.generate_images).parameters


def test_run_passes_the_flag_for_hook_pictures():
    src = (ROOT / "run.py").read_text()
    assert src.count("title_band_first=bool(script.get(\"hook_image\"))") >= 2


def test_run_prepends_verified_brief_when_given():
    src = (ROOT / "run.py").read_text()
    assert 'os.environ.get("REEL_BRIEF_FILE")' in src
    assert "VERIFIED BRIEF" in src


def test_krishna_form_check_requires_two_hands_on_flute():
    q = fc.FORM_REQUIRED["krishna"].lower()
    assert "both" in q and "flute" in q and "no flute" in q
