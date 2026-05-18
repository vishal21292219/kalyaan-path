"""Picks today's topic. Rotates daily, prefers upcoming festivals."""
from __future__ import annotations

import hashlib
import json
import random
from datetime import date, timedelta
from pathlib import Path

from .utils import ROOT, load_topics

STATE_DIR = ROOT / "data" / "state"
SHLOKA_STATE = STATE_DIR / "shloka_progress.json"


def _seed_for_today() -> int:
    return int(hashlib.md5(date.today().isoformat().encode()).hexdigest(), 16) % (2**32)


def pick_topic(force: str | None = None) -> dict:
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
    rng = random.Random(_seed_for_today())
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


def pick_shloka_episode() -> dict:
    """Pick next Gita shloka in sequence and advance state."""
    topics = load_topics()
    episodes = topics["gita_episodes"]
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if SHLOKA_STATE.exists():
        state = json.loads(SHLOKA_STATE.read_text())
    else:
        state = {"next_index": 0, "history": []}
    idx = state["next_index"] % len(episodes)
    ep = episodes[idx]
    ep_num = len(state["history"]) + 1
    title = f"Bhagavad Gita Shloka {ep_num} | {ep['ref']} | {ep['theme']}"
    state["next_index"] = idx + 1
    state["history"].append({"ep": ep_num, "ref": ep["ref"], "date": date.today().isoformat()})
    SHLOKA_STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
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


def pick_trending() -> dict:
    """Pick today's trending: nearby festival > weighted random deity."""
    topics = load_topics()
    today = date.today()
    # festival in next 5 days wins
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
    # weighted random deity from trending pool
    pool = topics.get("trending_deities", topics["deities"])
    rng = random.Random(_seed_for_today())
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
