"""Per-day 'did this slot publish?' marker — the source of truth for the
catch-up safety net (run_catchup.py).

A slot is keyed by niche_kind_s{seed}. A run writes its marker ONLY after the
video was actually delivered (YouTube upload succeeded, or Telegram drop sent).
The catch-up workflow reads this to decide what still needs to run today.

State file: data/state/published_log.json
  { "YYYY-MM-DD": { "ancient_trending_s1": true, "bhakti_mantra_s0": true } }
Old days are pruned so the file stays small.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from .utils import ROOT

LOG_PATH = ROOT / "data" / "state" / "published_log.json"
_KEEP_DAYS = 10


def slot_key(niche: str, kind: str, seed: int = 0) -> str:
    return f"{niche}_{kind}_s{seed}"


def _load() -> dict:
    if LOG_PATH.exists():
        try:
            return json.loads(LOG_PATH.read_text())
        except Exception:
            return {}
    return {}


def _prune(data: dict) -> dict:
    cutoff = (date.today() - timedelta(days=_KEEP_DAYS)).isoformat()
    return {d: v for d, v in data.items() if d >= cutoff}


def mark_published(niche: str, kind: str, seed: int = 0) -> None:
    """Record that today's slot was successfully delivered. Idempotent."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = _prune(_load())
    today = date.today().isoformat()
    data.setdefault(today, {})[slot_key(niche, kind, seed)] = True
    LOG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def was_published_today(niche: str, kind: str, seed: int = 0) -> bool:
    data = _load()
    return bool(data.get(date.today().isoformat(), {}).get(slot_key(niche, kind, seed)))
