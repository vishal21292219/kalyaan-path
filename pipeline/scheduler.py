"""Upload scheduler — pre-picks topics for future dates and persists them.

Source of truth: data/state/upload_schedule.json

Flow:
  1. Nightly pre-gen (run_pregen.py) calls schedule_for(niche, kind, date, seed)
     → returns deterministic topic + reserves it in schedule file
  2. Daytime publish run (run.py) calls get_scheduled(niche, kind, date, seed)
     → returns previously-reserved topic (or None if not pre-scheduled)
  3. After successful publish, mark_consumed() updates status

Daily slots tracked:
  bhakti.shloka  seed=0  (~07:00 IST)
  bhakti.trending seed=0 (~19:00 IST)
  ancient.trending seed=1 (~18:00 UTC EU prime)
  ancient.trending seed=2 (~23:00 UTC US prime)
  itihaas.trending seed=1 (~06:00 IST Telegram drop #1)
  itihaas.trending seed=2 (~06:15 IST Telegram drop #2)
"""
from __future__ import annotations

import hashlib
import json
import random
from datetime import date as date_t, datetime, timedelta
from pathlib import Path

from .utils import ROOT, load_topics

SCHEDULE_FILE = ROOT / "data" / "state" / "upload_schedule.json"
SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)

# Master list of recurring slots that pregen should fill
DAILY_SLOTS = [
    {"niche": "bhakti", "kind": "shloka",   "seed": 0, "label": "07:00 IST KalyaanPath shloka"},
    {"niche": "bhakti", "kind": "trending", "seed": 0, "label": "19:00 IST KalyaanPath trending"},
    # Itihaasvani: 3 slots delivered to Telegram night-before; user uploads next day at:
    {"niche": "itihaas","kind": "trending", "seed": 1, "label": "08:30 IST Itihaasvani drop #1 (morning)"},
    {"niche": "itihaas","kind": "trending", "seed": 2, "label": "13:00 IST Itihaasvani drop #2 (lunch)"},
    {"niche": "itihaas","kind": "trending", "seed": 3, "label": "22:30 IST Itihaasvani drop #3 (late-night prime)"},
    # NOTE: ancient/TimeDecoders slots removed — that channel is PARKED in
    # daily-reels.yml, so pregen-ing it only ever wasted/failed slots.
]


# ───────────────────────── state file helpers ─────────────────────────

def _load_schedule() -> dict:
    if SCHEDULE_FILE.exists():
        try:
            return json.loads(SCHEDULE_FILE.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def _save_schedule(sched: dict) -> None:
    SCHEDULE_FILE.write_text(json.dumps(sched, indent=2, ensure_ascii=False, default=str))


def _make_key(niche: str, kind: str, target_date: date_t, seed_offset: int) -> str:
    return f"{niche}_{kind}_{target_date.isoformat()}_s{seed_offset}"


# ───────────────────────── deterministic pickers (explicit date) ─────────────────────────

def _seed_for_date(target_date: date_t, offset: int = 0) -> int:
    key = f"{target_date.isoformat()}#{offset}"
    return int(hashlib.md5(key.encode()).hexdigest(), 16) % (2**32)


def _peek_festival(target_date: date_t, window_days: int = 3) -> dict | None:
    """Return festival happening within window_days of target_date, else None."""
    topics = load_topics()
    for fest in topics.get("festivals_calendar", []):
        try:
            f_date = date_t(target_date.year, fest["month"], fest["approx_day"])
        except ValueError:
            continue
        delta = (f_date - target_date).days
        if 0 <= delta <= window_days:
            return {
                "kind": "festival",
                "title": fest["name"],
                "wiki": fest["name"].replace(" ", "_"),
                "tags": ["festival", fest["name"].lower().replace(" ", "")],
            }
    return None


def _pick_trending_for(target_date: date_t, seed_offset: int = 0) -> dict:
    """Like topic_generator.pick_trending but for an explicit date."""
    fest = _peek_festival(target_date, window_days=5)
    if fest:
        return fest
    topics = load_topics()
    pool = topics.get("trending_deities", topics.get("deities", []))
    if not pool:
        return {"kind": "deity", "title": "Lord Krishna", "wiki": "Krishna", "tags": ["krishna"]}
    rng = random.Random(_seed_for_date(target_date, seed_offset))
    weights = [d.get("weight", 1) for d in pool]
    d = rng.choices(pool, weights=weights, k=1)[0]
    return {
        "kind": "deity",
        "title": d["name"],
        "wiki": d.get("wiki"),
        "tags": d.get("tags", []),
    }


def _pick_generic_for(target_date: date_t, seed_offset: int = 0) -> dict:
    """Like topic_generator.pick_topic but for an explicit date."""
    fest = _peek_festival(target_date, window_days=3)
    if fest:
        return fest
    topics = load_topics()
    rng = random.Random(_seed_for_date(target_date, seed_offset))
    bucket = rng.choice(["deity", "story", "shloka", "temple"])
    if bucket == "deity" and topics.get("deities"):
        d = rng.choice(topics["deities"])
        return {"kind": "deity", "title": d["name"], "wiki": d["wiki"], "tags": d.get("tags", [])}
    if bucket == "story" and topics.get("stories"):
        s = rng.choice(topics["stories"])
        return {"kind": "story", "title": s, "wiki": None, "tags": ["story", "mythology"]}
    if bucket == "shloka" and topics.get("shlokas"):
        s = rng.choice(topics["shlokas"])
        return {"kind": "shloka", "title": s, "wiki": None, "tags": ["shloka", "mantra"]}
    if topics.get("temples"):
        t = rng.choice(topics["temples"])
        return {"kind": "temple", "title": t, "wiki": t.split(",")[0].replace(" ", "_"), "tags": ["temple"]}
    return {"kind": "deity", "title": "Lord Shiva", "wiki": "Shiva", "tags": ["shiva"]}


def _peek_shloka_at_offset(days_ahead: int) -> dict:
    """Peek what shloka would be assigned N days ahead based on current state.
    Does NOT mutate the shloka_progress.json file (read-only peek).
    """
    from .utils import load_config
    topics = load_topics()
    episodes = topics.get("gita_episodes", [])
    if not episodes:
        return {"kind": "shloka_episode", "title": "Bhagavad Gita", "tags": ["gita"]}
    cfg = load_config()
    state_path = ROOT / cfg.get("paths", {}).get("shloka_progress", "data/state/shloka_progress.json")
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except json.JSONDecodeError:
            state = {"next_index": 0, "history": []}
    else:
        state = {"next_index": 0, "history": []}
    idx = (state.get("next_index", 0) + days_ahead) % len(episodes)
    ep = episodes[idx]
    ep_num = len(state.get("history", [])) + 1 + days_ahead
    return {
        "kind": "shloka_episode",
        "title": f"Bhagavad Gita Shloka {ep_num} | {ep['ref']} | {ep['theme']}",
        "episode_number": ep_num,
        "ref": ep["ref"],
        "verse": ep["verse"],
        "theme": ep["theme"],
        "wiki": None,
        "tags": ["gita", "shloka", f"gita{ep['ref'].replace('.', '_')}"],
    }


# ───────────────────────── public API ─────────────────────────

def schedule_for(niche: str, kind: str, target_date: date_t, seed_offset: int = 0,
                 days_ahead: int | None = None) -> dict:
    """Reserve (or fetch existing) topic for a future slot.

    Idempotent — calling twice for the same slot returns the same topic.
    """
    key = _make_key(niche, kind, target_date, seed_offset)
    sched = _load_schedule()
    if key in sched and sched[key].get("status") != "consumed":
        return sched[key]["topic"]

    # Pick topic based on kind
    if kind == "shloka":
        if days_ahead is None:
            days_ahead = (target_date - date_t.today()).days
        topic = _peek_shloka_at_offset(max(0, days_ahead))
    elif kind == "trending":
        topic = _pick_trending_for(target_date, seed_offset)
    else:
        topic = _pick_generic_for(target_date, seed_offset)

    sched[key] = {
        "topic": topic,
        "niche": niche,
        "kind": kind,
        "target_date": target_date.isoformat(),
        "seed_offset": seed_offset,
        "reserved_at": datetime.now().isoformat(timespec="seconds"),
        "status": "reserved",  # reserved → generated → consumed
        "pregen_dir": None,
    }
    _save_schedule(sched)
    return topic


def get_scheduled(niche: str, kind: str, target_date: date_t, seed_offset: int = 0) -> dict | None:
    """Return scheduled entry (topic + pregen_dir) if exists and not consumed.
    Returns None if not pre-scheduled (caller should fall back to realtime gen).
    """
    key = _make_key(niche, kind, target_date, seed_offset)
    sched = _load_schedule()
    entry = sched.get(key)
    if entry and entry.get("status") != "consumed":
        return entry
    return None


def update_status(niche: str, kind: str, target_date: date_t, seed_offset: int,
                  status: str, pregen_dir: str | None = None) -> None:
    """Update status (reserved → generated → consumed) and optional pregen_dir."""
    key = _make_key(niche, kind, target_date, seed_offset)
    sched = _load_schedule()
    if key not in sched:
        return
    sched[key]["status"] = status
    if pregen_dir is not None:
        sched[key]["pregen_dir"] = str(pregen_dir)
    sched[key]["last_updated"] = datetime.now().isoformat(timespec="seconds")
    _save_schedule(sched)


def mark_consumed(niche: str, kind: str, target_date: date_t, seed_offset: int = 0) -> None:
    update_status(niche, kind, target_date, seed_offset, "consumed")


def cleanup(older_than_days: int = 7) -> int:
    """Remove schedule entries older than N days + delete their pregen dirs."""
    import shutil
    sched = _load_schedule()
    cutoff = date_t.today() - timedelta(days=older_than_days)
    removed = 0
    for key in list(sched.keys()):
        try:
            entry_date = date_t.fromisoformat(sched[key]["target_date"])
        except (KeyError, ValueError):
            continue
        if entry_date < cutoff:
            pdir = sched[key].get("pregen_dir")
            if pdir:
                p = Path(pdir)
                if p.exists():
                    shutil.rmtree(p, ignore_errors=True)
            del sched[key]
            removed += 1
    _save_schedule(sched)
    return removed


def list_pending(days_ahead: int = 5) -> list[dict]:
    """For each daily slot, for each of next N days (INCLUDING today), return
    slots that need pregen. Includes today so the first nightly run covers
    today's slots too (otherwise today's daytime fires miss the cache)."""
    today = date_t.today()
    pending = []
    for offset in range(0, days_ahead + 1):  # today + N days ahead
        d = today + timedelta(days=offset)
        for slot in DAILY_SLOTS:
            key = _make_key(slot["niche"], slot["kind"], d, slot["seed"])
            entry = _load_schedule().get(key)
            status = entry["status"] if entry else "missing"
            if status in ("missing", "reserved"):  # not yet generated
                pending.append({**slot, "date": d, "status": status, "key": key})
    return pending


if __name__ == "__main__":
    # Debug: show next 5 days schedule
    import pprint
    pending = list_pending(5)
    print(f"Pending slots (next 5 days): {len(pending)}")
    pprint.pprint(pending)
