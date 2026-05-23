"""Persistent retry queue for failed pipeline runs.

When Gemini (or any external API) fails after in-process retries, the run
records itself here. A separate hourly cron picks up pending entries and
retries them. Each entry has a max of 3 retry attempts before being marked
PERMANENTLY_FAILED and removed from the active queue.

Schema (data/state/retry_queue.json):
{
  "entries": [
    {
      "id": "20260523_atlantis-...",
      "niche": "ancient",
      "kind": "trending",
      "topic": "The Lost City of Atlantis...",
      "seed_offset": 0,
      "mode": "publish",          // or "telegram"
      "failed_reason": "Gemini 503",
      "attempts": 1,
      "first_failed_at": "2026-05-23T19:41:00Z",
      "last_attempted_at": "2026-05-23T20:48:55Z",
      "next_retry_at": "2026-05-23T21:48:55Z"
    }
  ]
}
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .utils import ROOT

MAX_ATTEMPTS = 3
RETRY_INTERVAL_HOURS = 1


def _state_path() -> Path:
    p = ROOT / "data" / "state" / "retry_queue.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load() -> dict:
    p = _state_path()
    if not p.exists():
        return {"entries": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"entries": []}


def _save(data: dict) -> None:
    _state_path().write_text(json.dumps(data, indent=2, ensure_ascii=False))


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def add_or_update(
    *,
    niche: str,
    kind: str,
    topic: str,
    seed_offset: int,
    mode: str,
    failed_reason: str,
) -> dict:
    """Record a failed run for retry. If same niche+topic+seed exists, increment attempts."""
    data = _load()
    entry_id = f"{niche}_{kind}_{seed_offset}_{topic[:80]}".replace(" ", "_")
    now = _now_utc()
    next_retry = (
        datetime.now(timezone.utc) + timedelta(hours=RETRY_INTERVAL_HOURS)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    for entry in data["entries"]:
        if entry["id"] == entry_id:
            entry["attempts"] = entry.get("attempts", 0) + 1
            entry["last_attempted_at"] = now
            entry["failed_reason"] = failed_reason
            entry["next_retry_at"] = next_retry
            if entry["attempts"] >= MAX_ATTEMPTS:
                entry["status"] = "PERMANENTLY_FAILED"
            _save(data)
            return entry

    # New entry
    entry = {
        "id": entry_id,
        "niche": niche,
        "kind": kind,
        "topic": topic,
        "seed_offset": seed_offset,
        "mode": mode,
        "failed_reason": failed_reason,
        "attempts": 1,
        "status": "PENDING",
        "first_failed_at": now,
        "last_attempted_at": now,
        "next_retry_at": next_retry,
    }
    data["entries"].append(entry)
    _save(data)
    return entry


def get_pending_due() -> list[dict]:
    """Return entries whose next_retry_at <= now AND attempts < MAX_ATTEMPTS."""
    data = _load()
    now = datetime.now(timezone.utc)
    pending = []
    for e in data["entries"]:
        if e.get("status") == "PERMANENTLY_FAILED":
            continue
        if e.get("attempts", 0) >= MAX_ATTEMPTS:
            continue
        try:
            nra = datetime.strptime(e["next_retry_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if nra <= now:
                pending.append(e)
        except Exception:
            pending.append(e)
    return pending


def remove(entry_id: str) -> None:
    """Remove an entry (called after successful retry)."""
    data = _load()
    data["entries"] = [e for e in data["entries"] if e["id"] != entry_id]
    _save(data)


def list_all() -> list[dict]:
    return _load().get("entries", [])
