"""Each image must be on screen while ITS body line is narrated.

2026-10-25 darshan render: "Shiva gave his trident … Indra gave his
thunderbolt" played over a Vishnu frame. GoM voices on ElevenLabs, which writes
no sentences.json, so image timing fell back to an equal split and the ramp
opener then replaced it with a fixed 1.5s, 5.6s, 9.6s … sequence that ignores
the narration. The words.json sidecar (exact word timings) was always there.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.assembler import _line_synced_durations  # noqa: E402
from pipeline.frame_check import FORM_REQUIRED  # noqa: E402


def _words(texts_and_starts):
    return [{"text": t, "start": s, "end": s + 0.3} for t, s in texts_and_starts]


SCRIPT = {"hook": "Every god gave — Durga.", "body": ["Shiva gave.", "Vishnu gave much.", "She rose."],
          "cta": "Comment it."}
#            hook: Every god gave Durga (the dash is spoken as no word)
BOUNDS = _words([("Every", 0.0), ("god", 0.4), ("gave", 0.8), ("—", 1.0), ("Durga.", 1.2),
                 ("Shiva", 2.0), ("gave.", 2.5),
                 ("Vishnu", 4.0), ("gave", 4.5), ("much.", 5.0),
                 ("She", 7.0), ("rose.", 7.5),
                 ("Comment", 8.5), ("it.", 9.0)])


def test_each_image_starts_with_its_line():
    d = _line_synced_durations(SCRIPT, BOUNDS, 3, 10.0)
    starts = [sum(d[:i]) for i in range(3)]
    assert starts == pytest.approx([0.0, 4.0, 7.0], abs=0.06)


def test_durations_fill_the_whole_narration():
    assert sum(_line_synced_durations(SCRIPT, BOUNDS, 3, 10.0)) == pytest.approx(10.0)


def test_first_image_covers_the_hook():
    d = _line_synced_durations(SCRIPT, BOUNDS, 3, 10.0)
    assert d[0] == pytest.approx(4.0, abs=0.06)   # hook + body[0]


def test_word_count_mismatch_falls_back():
    assert _line_synced_durations(SCRIPT, BOUNDS[:-3], 3, 10.0) is None


def test_image_count_mismatch_falls_back():
    assert _line_synced_durations(SCRIPT, BOUNDS, 4, 10.0) is None


def test_no_boundaries_falls_back():
    assert _line_synced_durations(SCRIPT, [], 3, 10.0) is None


@pytest.mark.parametrize("base", [
    "20261025_every-god-gave-durga-a-weapon",
    "20261025_krishna-told-arjuna-why-you-should-not-fear-death",
])
def test_real_render_assets_sync(base):
    s = ROOT / f"output/scripts/{base}.json"
    w = ROOT / f"output/audio/{base}.words.json"
    if not (s.exists() and w.exists()):
        pytest.skip("render assets not on this machine")
    script, words = json.loads(s.read_text()), json.loads(w.read_text())
    n = len(script["body"]) + (1 if script.get("hook_image") else 0)
    d = _line_synced_durations(script, words, n, words[-1]["end"] + 0.5)
    assert d is not None and len(d) == n and min(d) >= 0.5


def test_vision_gate_checks_vishnu_has_four_arms():
    assert "four" in FORM_REQUIRED["vishnu"].lower()


def test_assemble_wiring_has_no_silent_name_error():
    """The wiring sits in a try/except that falls back silently; a missing
    import there would turn line sync off without any test failing. Compile
    the block's names against the module instead."""
    import ast
    src = (ROOT / "pipeline/assembler.py").read_text()
    tree = ast.parse(src)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "assemble")
    seg = ast.get_source_segment(src, fn)
    block = seg[seg.index("line_synced = None"):seg.index("if line_synced:")]
    assert "import json as _json" in block and "_json.loads" in block
