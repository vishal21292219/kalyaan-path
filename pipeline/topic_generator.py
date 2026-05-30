"""Picks today's topic. Rotates daily, prefers upcoming festivals."""
from __future__ import annotations

import hashlib
import json
import random
from datetime import date, timedelta
from pathlib import Path

from .utils import ROOT, load_config, load_topics


def _shloka_state_path() -> Path:
    cfg = load_config()
    rel = cfg.get("paths", {}).get("shloka_progress", "data/state/shloka_progress.json")
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _seed_for_today(offset: int = 0) -> int:
    """Date-based deterministic seed. Pass offset to get a DIFFERENT pick
    on the same day (e.g. for multiple runs/day on the same niche)."""
    key = f"{date.today().isoformat()}#{offset}"
    return int(hashlib.md5(key.encode()).hexdigest(), 16) % (2**32)


def pick_topic(force: str | None = None, seed_offset: int = 0) -> dict:
    topics = load_topics()

    if force and force != "auto":
        return {"kind": "custom", "title": force, "wiki": None, "tags": []}

    # 1. festival in next 3 days → highest priority
    today = date.today()
    for fest in topics["festivals_calendar"]:
        try:
            f_date = date(today.year, fest["month"], fest["approx_day"])
        except ValueError:
            continue
        delta = (f_date - today).days
        if 0 <= delta <= 3:
            return {
                "kind": "festival",
                "title": fest["name"],
                "wiki": fest["name"].replace(" ", "_"),
                "tags": ["festival", fest["name"].lower().replace(" ", "")],
            }

    # 2. rotate across categories by day-of-year mod
    rng = random.Random(_seed_for_today(seed_offset))
    bucket = rng.choice(["deity", "story", "shloka", "temple"])

    if bucket == "deity":
        d = rng.choice(topics["deities"])
        return {"kind": "deity", "title": d["name"], "wiki": d["wiki"], "tags": d["tags"]}
    if bucket == "story":
        s = rng.choice(topics["stories"])
        return {"kind": "story", "title": s, "wiki": None, "tags": ["story", "mythology"]}
    if bucket == "shloka":
        s = rng.choice(topics["shlokas"])
        return {"kind": "shloka", "title": s, "wiki": None, "tags": ["shloka", "mantra"]}
    t = rng.choice(topics["temples"])
    return {"kind": "temple", "title": t, "wiki": t.split(",")[0].replace(" ", "_"), "tags": ["temple"]}


def _mantra_state_path() -> Path:
    """State file tracking which mantra topics were used recently (avoid 14-day repeats)."""
    return ROOT / "data/state/mantra_history.json"


def pick_mantra(seed_offset: int = 0) -> dict:
    """Pick a mantra-rahasya topic for KalyaanPath morning slot.
    Rotates deterministically by date+seed; avoids titles used in last 14 days.
    Replaces sequential Gita shloka format (pivoted 2026-05-28 after <200-view data)."""
    mantra_file = ROOT / "data/topics_mantra.json"
    if not mantra_file.exists():
        raise FileNotFoundError(f"Mantra topics missing: {mantra_file}")
    pool = json.loads(mantra_file.read_text())["mantras"]

    # Filter out titles used in last 14 days
    state_path = _mantra_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    if state_path.exists():
        state = json.loads(state_path.read_text())
    else:
        state = {"history": []}
    cutoff = date.today() - timedelta(days=14)
    recent_titles = {
        h["title"] for h in state["history"]
        if date.fromisoformat(h["date"]) >= cutoff
    }
    available = [m for m in pool if m["title"] not in recent_titles]
    if not available:
        # Pool exhausted within 14-day window — fall back to full pool
        available = pool

    rng = random.Random(_seed_for_today(seed_offset))
    chosen = rng.choice(available)

    state["history"].append({"title": chosen["title"], "date": date.today().isoformat()})
    # Keep history bounded
    state["history"] = state["history"][-200:]
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))

    return {
        "kind": "mantra",
        "title": chosen["title"],
        "deity": chosen.get("deity", "general"),
        "mantra_text": chosen.get("mantra", ""),
        "hook": chosen.get("hook", ""),
        "wiki": None,
        "tags": chosen.get("tags", []),
    }


def pick_shloka_episode() -> dict:
    """Pick next Gita shloka in sequence and advance state."""
    topics = load_topics()
    episodes = topics["gita_episodes"]
    state_path = _shloka_state_path()
    if state_path.exists():
        state = json.loads(state_path.read_text())
    else:
        state = {"next_index": 0, "history": []}
    idx = state["next_index"] % len(episodes)
    ep = episodes[idx]
    ep_num = len(state["history"]) + 1
    title = f"Bhagavad Gita Shloka {ep_num} | {ep['ref']} | {ep['theme']}"
    state["next_index"] = idx + 1
    state["history"].append({"ep": ep_num, "ref": ep["ref"], "date": date.today().isoformat()})
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    return {
        "kind": "shloka_episode",
        "title": title,
        "episode_number": ep_num,
        "ref": ep["ref"],
        "verse": ep["verse"],
        "theme": ep["theme"],
        "wiki": None,
        "tags": ["gita", "shloka", f"gita{ep['ref'].replace('.', '_')}"],
    }


# Proven viral long-form title formats (data from Praveen Mohan, KrazzyKreations,
# Project Nightfall, Kaliyug Ke Divya Mantra channel analysis). Each one drives
# the "watch till end" psychology — number + curiosity + specific shocking promise.
_LONGFORM_TITLE_FORMATS = {
    "hindi": [
        "{topic} ke 10 anjane rahasya | Sach jo NCERT mein nahi padhaya gaya",
        "{topic} ki anuponchak kahani | Janma se mrityu tak",
        "{topic} ka asli sach | Vigyaan bhi jisse hairan hai",
        "{topic} ke baare mein 15 baatein jo aap nahi jaante",
        "{topic} ki poori kahani | Ek video mein sab kuch",
        "{topic} ke 7 rahasya | Jo guru log nahi batate",
        "{topic} aur uska chupa sach | Itihaas ki sabse badi reveal",
    ],
    "english": [
        "{topic}: 10 Hidden Mysteries Scientists Can't Explain",
        "The Complete Untold Story of {topic} | From Origin to End",
        "{topic}: 15 Facts That Defy Modern Science",
        "Why {topic} Shouldn't Exist — But It Does",
        "The Real Truth About {topic} | New Evidence Revealed",
        "{topic} Decoded: The Mystery That Changed Everything",
    ],
    "hinglish": [
        "{topic} ke 10 Rahasya | Hidden Sach Jo Hairan Kar De",
        "{topic} ki Poori Kahani Ek Video Mein",
        "{topic} ka ASLI Sach | Vigyaan Bhi Confused",
        "{topic} ke baare mein 15 Anjaani Baatein",
        "{topic} ka Untold History | Janma se Maut Tak",
    ],
}


def viralize_longform_title(base_topic: dict, language: str = "hindi") -> dict:
    """Wrap base topic in proven viral long-form title format. Idempotent —
    returns a NEW topic dict with `title` rewritten + `_original_title` preserved.
    Same topic + same day = same enhanced title (deterministic)."""
    formats = _LONGFORM_TITLE_FORMATS.get(language, _LONGFORM_TITLE_FORMATS["hindi"])
    rng = random.Random(_seed_for_today(0) ^ hash(base_topic.get("title", "")))
    fmt = rng.choice(formats)
    base_name = base_topic.get("title", "Topic")
    short_name = base_name.replace("Lord ", "").replace("Goddess ", "")
    enhanced = dict(base_topic)
    enhanced["_original_title"] = base_name
    enhanced["title"] = fmt.format(topic=short_name)
    enhanced["_longform_format"] = fmt
    return enhanced


def pick_trending(seed_offset: int = 0) -> dict:
    """Pick today's trending: nearby festival > weighted random deity.
    Pass seed_offset to vary the pick on the same day (multi-drop schedule).
    """
    topics = load_topics()
    today = date.today()
    # festival in next 5 days wins (festival overrides any offset — same fest all day)
    for fest in topics["festivals_calendar"]:
        try:
            f_date = date(today.year, fest["month"], fest["approx_day"])
        except ValueError:
            continue
        delta = (f_date - today).days
        if 0 <= delta <= 5:
            return {
                "kind": "festival",
                "title": fest["name"],
                "wiki": fest["name"].replace(" ", "_"),
                "tags": ["festival", fest["name"].lower().replace(" ", "")],
            }
    # weighted random deity from trending pool — different per offset
    pool = topics.get("trending_deities", topics["deities"])
    rng = random.Random(_seed_for_today(seed_offset))
    weights = [d.get("weight", 1) for d in pool]
    d = rng.choices(pool, weights=weights, k=1)[0]
    return {
        "kind": "deity",
        "title": d["name"],
        "wiki": d.get("wiki"),
        "tags": d.get("tags", []),
    }


if __name__ == "__main__":
    import sys
    kind = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if kind == "shloka":
        print(pick_shloka_episode())
    elif kind == "trending":
        print(pick_trending())
    else:
        print(pick_topic())
