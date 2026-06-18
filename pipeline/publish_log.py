"""Per-day 'did this slot publish?' marker — the source of truth for the
catch-up safety net (run_catchup.py).

A slot is keyed by niche_kind_s{seed}. A run writes its marker ONLY after the
video was actually delivered on its PRIMARY channel (YouTube upload succeeded for
publish-mode, or Telegram drop sent for telegram-mode). Bonus channels (FB/IG
reels) do NOT mark the slot done — their reliability is handled by the decoupled
reel-poster + its posted-ledger. The catch-up workflow reads this to decide what
still needs to run.

State file: data/state/published_log.json
  { "YYYY-MM-DD": { "ancient_trending_s1": "2026-06-18T15:40:00+00:00", ... } }
The value is the UTC ISO timestamp of delivery (legacy `true` is still accepted
and treated as "delivered at that day's midnight UTC"). Storing the real time
lets the catch-up sweep reason ACROSS the UTC day boundary — a slot generated at
23:00 UTC and recovered at 02:00 the next day is matched to the right cycle
instead of looking "missed" just because the calendar date rolled over.
Old days are pruned so the file stays small.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
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
    data.setdefault(today, {})[slot_key(niche, kind, seed)] = (
        datetime.now(timezone.utc).isoformat()
    )
    LOG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False))


def was_published_today(niche: str, kind: str, seed: int = 0) -> bool:
    data = _load()
    return bool(data.get(date.today().isoformat(), {}).get(slot_key(niche, kind, seed)))


def _coerce_ts(day: str, val) -> datetime | None:
    """Turn a stored marker value into a UTC datetime. Accepts ISO timestamps
    (new format) and legacy `true` (→ that day's midnight UTC)."""
    if not val:
        return None
    if val is True:
        # Legacy boolean marker (pre-timestamp). Treat as delivered at END of that
        # UTC day so it satisfies last_published >= occurrence for ANY of that
        # day's slots — avoids a one-time spurious re-gen during the transition.
        try:
            return datetime.fromisoformat(day).replace(
                hour=23, minute=59, second=59, tzinfo=timezone.utc)
        except Exception:
            return None
    try:
        ts = datetime.fromisoformat(str(val))
    except Exception:
        return None
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts


def last_published(niche: str, kind: str, seed: int = 0) -> datetime | None:
    """Most recent UTC delivery time for this slot across all retained days,
    or None if never delivered. Used by the catch-up sweep so it can match a
    recovery window even when it crosses the UTC midnight boundary."""
    key = slot_key(niche, kind, seed)
    best: datetime | None = None
    for day, slots in _load().items():
        ts = _coerce_ts(day, (slots or {}).get(key))
        if ts is not None and (best is None or ts > best):
            best = ts
    return best
