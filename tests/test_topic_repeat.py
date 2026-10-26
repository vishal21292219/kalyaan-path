"""A topic that has aired never airs again (2026-10-26).

pick_viral only hid topics used in the last 30 days, the published ledger was
pruned and keyed on the full title, and an exhausted pool re-aired the
least-recently-used topic — so the pipeline re-uploaded old topics, which is
what YouTube penalised. Now: aired once = gone for good (same topic segment or a
rephrasing), and an empty fresh pool skips the slot instead of repeating.
"""
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline import publish_log, topic_generator as tg, topic_refill  # noqa: E402


@pytest.fixture
def env(tmp_path, monkeypatch):
    (tmp_path / "data/state").mkdir(parents=True)
    monkeypatch.setattr(tg, "ROOT", tmp_path)
    monkeypatch.setattr(topic_refill, "ROOT", tmp_path)
    monkeypatch.setattr(publish_log, "TITLE_LOG_PATH", tmp_path / "data/state/published_titles.json")
    import pipeline.utils as u
    monkeypatch.setattr(u, "load_config", lambda *a, **k: {"niche": "godmind"})

    def setup(pool, history=(), ledger=None):
        (tmp_path / "data/viral_topics_godmind.json").write_text(
            json.dumps({"topics": [{"title": t} for t in pool]}))
        (tmp_path / "data/state/viral_history_godmind.json").write_text(
            json.dumps({"history": list(history)}))
        if ledger is not None:
            publish_log.TITLE_LOG_PATH.write_text(json.dumps(ledger))
    return setup


def _old(title, days=45):
    return {"title": title, "date": (date.today() - timedelta(days=days)).isoformat()}


def test_topic_aired_45_days_ago_is_not_picked_again(env):
    env(["Yama's Mirror — Why You Fear Death", "Hanuman Forgot His Strength"],
        [_old("Yama's Mirror — Why You Fear Death")])
    assert tg.pick_viral()["title"] == "Hanuman Forgot His Strength"


def test_same_topic_with_a_new_subtitle_is_blocked(env):
    env(["Why Krishna Stole Butter — The Hidden Psychology", "Kaal Bhairav, Lord of Kashi"],
        [_old("Why Krishna Stole Butter — The Psychology Behind", 200)])
    assert tg.pick_viral()["title"] == "Kaal Bhairav, Lord of Kashi"


def test_published_ledger_blocks_even_without_history(env):
    env(["The Overthinking Mind", "Durga's Nine Forms"], [],
        ledger={"the overthinking mind": "2026-01-01"})
    assert tg.pick_viral()["title"] == "Durga's Nine Forms"


def test_exhausted_pool_skips_instead_of_repeating(env):
    env(["The Overthinking Mind"], [_old("The Overthinking Mind", 90)])
    with pytest.raises(tg.TopicPoolExhausted):
        tg.pick_viral()


def test_expired_pending_reservation_does_not_block(env):
    stale = {"title": "Durga's Nine Forms", "date": date.today().isoformat(),
             "pending": True, "at": "2020-01-01T00:00:00+00:00"}
    env(["Durga's Nine Forms"], [stale])
    assert tg.pick_viral()["title"] == "Durga's Nine Forms"


def test_ledger_is_never_pruned(monkeypatch, tmp_path):
    monkeypatch.setattr(publish_log, "TITLE_LOG_PATH", tmp_path / "t.json")
    publish_log.TITLE_LOG_PATH.write_text(json.dumps({"old topic": "2024-01-01"}))
    publish_log.mark_title_published("New Topic — Subtitle")
    data = json.loads(publish_log.TITLE_LOG_PATH.read_text())
    assert "old topic" in data and "new topic" in data


def test_published_check_matches_topic_segment_and_has_no_expiry(monkeypatch, tmp_path):
    monkeypatch.setattr(publish_log, "TITLE_LOG_PATH", tmp_path / "t.json")
    publish_log.TITLE_LOG_PATH.write_text(json.dumps({"why krishna stole butter": "2025-01-01"}))
    assert publish_log.title_published_recently("Why Krishna Stole Butter — A New Angle")
    assert publish_log.topic_ever_published("Why Krishna Stole Butter: Again")


def test_refill_counts_fresh_as_never_aired(env):
    env(["A", "B", "C"], [_old("A", 90)], ledger={"b": "2025-01-01"})
    assert topic_refill._fresh_count([{"title": t} for t in ("A", "B", "C")], "godmind") == 1


def test_run_skips_the_slot_when_the_pool_is_exhausted():
    src = (ROOT / "run.py").read_text()
    assert "TopicPoolExhausted" in src
