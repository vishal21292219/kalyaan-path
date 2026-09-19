"""Picks today's topic. Rotates daily, prefers upcoming festivals."""
from __future__ import annotations

import hashlib
import json
import random
import re
from datetime import date, datetime, timedelta, timezone
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


# Festival deity → mantra-pool deity aliases (so e.g. Rath Yatra rides Krishna
# mantras, Navratri rides Durga). Festival-timing is a proven reach booster:
# YouTube search + algorithm both spike a deity's content around its festival.
_FEST_DEITY_ALIAS = {
    "jagannath": ["krishna", "vishnu"],
    "vyasa": ["krishna", "gayatri", "vishnu"],
    "rama": ["ram", "hanuman"], "ram": ["ram", "hanuman"],
    "durga": ["durga", "devi", "kali"], "devi": ["durga", "devi", "kali"],
    "lakshmi": ["lakshmi", "vishnu"],
    "ganesha": ["ganesh"], "ganesh": ["ganesh"],
    "krishna": ["krishna", "vishnu"],
    "shiva": ["shiva"], "hanuman": ["hanuman", "ram"],
    "vishnu": ["vishnu", "krishna", "ram"],
}


def active_festival(window_days: int = 5) -> dict | None:
    """Return the nearest festival dict within `window_days` (incl. today), else
    None. Uses the bhakti festivals_calendar (month/approx_day)."""
    try:
        topics = load_topics()
    except Exception:
        return None
    today = date.today()
    best = None
    for fest in topics.get("festivals_calendar", []):
        try:
            f_date = date(today.year, fest["month"], fest["approx_day"])
        except (ValueError, KeyError, TypeError):
            continue
        delta = (f_date - today).days
        if 0 <= delta <= window_days and (best is None or delta < best[0]):
            best = (delta, fest)
    return best[1] if best else None


def _festival_mantra_filter(pool: list[dict], fest: dict) -> list[dict]:
    """Subset of mantras matching the festival's deity (via alias map), else []."""
    deity = (fest.get("deity") or "").strip().lower()
    if not deity:
        return []
    cands = set([deity] + _FEST_DEITY_ALIAS.get(deity, []))
    out = []
    for m in pool:
        md = (m.get("deity") or "").lower()
        tags = {str(t).lower() for t in (m.get("tags") or [])}
        if md in cands or (cands & tags):
            out.append(m)
    return out


def pick_mantra(seed_offset: int = 0) -> dict:
    """Pick a mantra-rahasya topic for KalyaanPath morning slot.
    Rotates deterministically by date+seed; avoids titles used in last 14 days.
    If a festival is within 5 days, biases to that deity's mantra (reach boost).
    Replaces sequential Gita shloka format (pivoted 2026-05-28 after <200-view data)."""
    mantra_file = ROOT / "data/topics_mantra.json"
    if not mantra_file.exists():
        raise FileNotFoundError(f"Mantra topics missing: {mantra_file}")
    pool = list(json.loads(mantra_file.read_text())["mantras"])
    # Merge the FRESH researched viral bhakti pool (mantras + deity stories) so
    # KalyaanPath rides currently-trending + festival-timed topics, not just the
    # static list — kills repetition.
    vf = ROOT / "data/viral_topics_bhakti.json"
    if vf.exists():
        vd = json.loads(vf.read_text())
        seen = {m["title"] for m in pool}
        for m in (vd.get("mantras", []) + vd.get("deity_stories", [])):
            if m.get("title") and m["title"] not in seen:
                pool.append(m); seen.add(m["title"])

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

    # Festival timing: if a festival is near, prefer its deity's mantras.
    fest = active_festival(window_days=5)
    if fest:
        fest_subset = _festival_mantra_filter(available, fest)
        if fest_subset:
            print(f"[mantra] festival '{fest.get('name')}' near → biasing to deity '{fest.get('deity')}' ({len(fest_subset)} mantras)")
            available = fest_subset

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


def _series_state_path():
    return ROOT / "data/state/series_progress.json"


def pick_series(seed_offset: int = 0) -> dict:
    """Sequential SERIES episode for the active niche (e.g. Itihaasvani).
    Advances ONE episode per day (idempotent within a day so a pregen peek and
    the real run agree). Finishes one series before the next, then loops.
    Series = return viewers → watch-time → algorithm boost. Falls back to
    trending if no series file exists for the niche."""
    cfg = load_config()
    niche = cfg.get("niche", "itihaas")
    series_file = ROOT / f"data/series_{niche}.json"
    if not series_file.exists():
        return pick_trending(seed_offset=seed_offset)
    series_list = json.loads(series_file.read_text())["series"]
    flat = [(s, i, ep) for s in series_list for i, ep in enumerate(s["episodes"])]
    if not flat:
        return pick_trending(seed_offset=seed_offset)
    total = len(flat)

    sp = _series_state_path()
    sp.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(sp.read_text()) if sp.exists() else {}
    today = date.today().isoformat()
    cursor = int(state.get("cursor", 0))
    if state.get("last_date") != today:
        if "last_date" in state:           # not the very first run → advance
            cursor = (cursor + 1) % total
        state["cursor"] = cursor
        state["last_date"] = today
        sp.write_text(json.dumps(state, indent=2, ensure_ascii=False))

    s, ep_idx, ep = flat[cursor % total]
    return {
        "kind": "series",
        "series_name": s["name"],
        "series_id": s["id"],
        "episode_number": ep_idx + 1,
        "episode_total": len(s["episodes"]),
        "english_tail": s.get("english_tail", ""),
        "title": ep["title"],
        "angle": ep.get("angle", ""),
        "footage": bool(ep.get("footage", s.get("footage", False))),
        "wiki": ep.get("wiki") or ep["title"].replace(" ", "_"),
        "tags": ["series", s["id"], "mythology"],
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


def _viral_state_path(niche: str):
    return ROOT / f"data/state/viral_history_{niche}.json"


# ── TOPIC RESERVATION (2026-09-19 audit) ─────────────────────────────────────
# pick_viral used to append to history at PICK time and persist_state.py commits
# state with `if: always()` — so a run that died in the script writer still ate
# its topic permanently. Measured: GoM picked 22 topics 10-19 Sep and published
# 10 videos; 12 topics were burned with nothing shipped, nine of them entries of
# the brand-new "Gods Inside You" launch series.
#
# Fix: a pick writes a PENDING reservation. run.py confirms it only after the
# upload succeeds. An unconfirmed reservation EXPIRES after RESERVE_HOURS and the
# topic returns to the pool. The reservation still blocks a concurrent run (the
# primary + catch-up collision) for the whole window, so this does not reopen the
# duplicate-upload hole it was originally guarding.
#
# 2h is deliberate: long enough to cover a full generation (~45 min) so a
# concurrent run can never grab the same topic, short enough that a DEAD run's
# topic is back in the pool before the next catch-up sweep — so catch-up re-picks
# the SAME topic and the "Gods Inside You" seq order is preserved rather than
# skipping a number.
RESERVE_HOURS = 2

# Words too common across a niche's pool to signal "same topic". Without this,
# "The Real Meaning of Shiva" and "The Real Meaning of Kali" look identical.
_DUP_STOP = {
    "the", "a", "an", "of", "and", "to", "in", "is", "it", "its", "you", "your",
    "that", "this", "for", "with", "no", "on", "was", "were", "are", "be", "from",
    "at", "as", "why", "how", "what", "who", "did", "does", "real", "meaning",
    "inside", "hidden", "secret", "truth", "ancient", "mystery", "mysteries",
    "shorts", "never", "still", "found", "years", "year", "old",
    # GoM's series titles share a fixed emotional frame ("You Are Not Afraid of
    # X", "The Part of You That …"), so these carry no topic signal — without
    # them, "You Are Not Afraid of Kali" and "…of Yama's Mirror" collide on the
    # frame alone and the picker would refuse a legitimately different deity.
    "not", "one", "has", "have", "can", "cant", "will", "just", "like", "into",
    "about", "every", "part", "thing", "things", "when", "then",
}


def _dup_tokens(title: str) -> set:
    t = re.sub(r"#\w+", " ", (title or "").lower())
    t = re.split(r"[—:|·]", t)[0]                     # topic segment, drop subtitle
    t = re.sub(r"[^a-z0-9\s]+", " ", t)
    return {w for w in t.split() if len(w) > 2 and w not in _DUP_STOP}


def _too_similar(title: str, others, threshold: float = 0.6) -> bool:
    """True if `title` shares >= threshold of its distinctive words with any of
    `others` — i.e. it is a rephrasing of something already aired."""
    a = _dup_tokens(title)
    if len(a) < 2:
        return False
    for o in others:
        b = _dup_tokens(o)
        if len(b) < 2:
            continue
        shared = a & b
        # Two distinct shared content words minimum. A single shared word is a
        # coincidence ("afraid", "stone"); it is not the same topic.
        if len(shared) < 2:
            continue
        if len(shared) / min(len(a), len(b)) >= threshold:
            return True
    return False


def _safe_day(s):
    try:
        return date.fromisoformat(str(s))
    except Exception:
        return None


def _is_blocking(entry: dict, now: datetime | None = None) -> bool:
    """True if this history entry should still hide its topic from the picker.

    Confirmed entries (published, or any legacy entry with no `pending` key) always
    block. A pending reservation blocks only until it expires."""
    if not entry.get("pending"):
        return True                       # published, or legacy pre-reservation entry
    try:
        at = datetime.fromisoformat(str(entry.get("at")))
    except Exception:
        return False                      # malformed reservation → don't let it block
    now = now or datetime.now(timezone.utc)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return (now - at) < timedelta(hours=RESERVE_HOURS)


def has_active_reservation(niche: str) -> str | None:
    """Title of an UNEXPIRED pending reservation for this niche, else None.

    This is the in-flight signal catch-up needs. Before it, the 15:30 UTC sweep
    fired while the (cron-lagged) primary run was still generating — neither had
    written its published_log marker yet, so both picked a topic and only one
    shipped. Fails OPEN (returns None) so it can never block a real recovery."""
    try:
        sp = _viral_state_path(niche)
        if not sp.exists():
            return None
        for h in reversed(json.loads(sp.read_text()).get("history", [])):
            if h.get("pending") and _is_blocking(h):
                return h.get("title")
    except Exception as e:
        print(f"[topic] reservation check skipped ({type(e).__name__}: {e})")
    return None


def confirm_topic(niche: str, title: str) -> None:
    """Promote this topic's newest PENDING reservation to confirmed. Called by
    run.py only after the video actually reached its primary channel. Never
    raises — a bookkeeping failure must not fail a successful upload."""
    try:
        sp = _viral_state_path(niche)
        if not sp.exists() or not title:
            return
        state = json.loads(sp.read_text())
        for h in reversed(state.get("history", [])):
            if h.get("title") == title and h.get("pending"):
                h.pop("pending", None)
                h.pop("at", None)
                sp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
                print(f"[topic] confirmed '{title}' — reservation committed")
                return
    except Exception as e:
        print(f"[topic] confirm_topic skipped ({type(e).__name__}: {e})")


def pick_viral(seed_offset: int = 0) -> dict:
    """Pick from the FRESH researched viral-topic pool (data/viral_topics_{niche}.json),
    avoiding anything used in the last 30 days. This is what kills the 'same videos
    on repeat' problem — a big rotating pool of specific, currently-trending topics
    instead of a tiny static deity list. Returns None if no viral file for the niche."""
    from .utils import load_config
    niche = load_config().get("niche", "itihaas")
    vf = ROOT / f"data/viral_topics_{niche}.json"
    if not vf.exists():
        return None
    data = json.loads(vf.read_text())
    pool = list(data.get("topics", []))
    if not pool:
        return None

    sp = _viral_state_path(niche)
    sp.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads(sp.read_text()) if sp.exists() else {"history": []}
    cutoff = date.today() - timedelta(days=30)
    recent_entries = [h for h in state["history"]
                      if _safe_day(h.get("date")) and _safe_day(h["date"]) >= cutoff
                      and _is_blocking(h)]
    recent = {h["title"] for h in recent_entries}
    avail = [t for t in pool if t["title"] not in recent]

    # NEAR-DUPLICATE GUARD (2026-09-19 audit). Exact-title dedup could never catch
    # the real repeats, because the POOL itself holds rephrasings of one subject.
    # Measured cost on shipped video pairs — the repeat loses ~10x:
    #   "The Demon Every God Kills Is Inside You" 1018 → "Every Hindu God Kills
    #    the Same Demon" 93 | Ravana's 10 Heads 963 → 320 | Voynich 646 → 34 |
    #   Menkaure 359 → 40 | "Something Is Dragging Our Galaxy" 70 → 19 (same day).
    # Drop any candidate that shares >=60% of its distinctive words with a topic
    # aired in the window. Guarded + never allowed to empty the pool.
    try:
        near = [t for t in avail if not _too_similar(t.get("title", ""), recent)]
        if near:
            dropped = len(avail) - len(near)
            if dropped:
                print(f"[topic] near-dup guard dropped {dropped} rephrasing(s) of recent topics")
            avail = near
    except Exception as e:
        print(f"[topic] near-dup guard skipped ({type(e).__name__}: {e})")

    # Also drop topics ALREADY published all-time. A published video lives on YouTube
    # forever, so run.py's live-YouTube dedup would skip it — but pick_viral's 30-day
    # window let a >30-day-old published topic re-enter `avail` and get picked (lowest
    # seq) then skipped EVERY run = a dead slot, no upload. Align the picker with the
    # permanent published ledger so only genuinely-fresh (never-published) topics are
    # eligible. Guarded + falls back to the un-filtered list so we never pick nothing.
    try:
        from .publish_log import _norm_title, TITLE_LOG_PATH
        published = set(json.loads(TITLE_LOG_PATH.read_text())) if TITLE_LOG_PATH.exists() else set()
        never_pub = [t for t in avail if _norm_title(t.get("title", "")) not in published]
        if never_pub:
            avail = never_pub
    except Exception:
        pass

    rng = random.Random(_seed_for_today(seed_offset))
    # STRICT planned sequence (launch ramp): if any available topic carries an
    # integer 'seq', air the LOWEST-seq one first — a deterministic order instead
    # of weighted random. Multi-slot days resolve naturally: each run appends to
    # history, so the next run's lowest *unused* seq advances (seq1→seq2→seq3…).
    # A failed/un-posted slot stays unused → it's simply picked next (order kept).
    # Once the planned seq topics are exhausted (or none defined), it falls back
    # to the weighted random pick below. Other niches (no 'seq') are unaffected.
    seq_avail = [t for t in avail if isinstance(t.get("seq"), int)]
    if seq_avail:
        chosen = min(seq_avail, key=lambda t: t["seq"])
    elif avail:
        # Weighted pick. DATA-DRIVEN (Itihaasvani analytics): mythology FIGURE
        # topics (warriors/gods/legends — non-footage) crush monument/footage
        # ones for this audience (350-550 views vs 13-140). So figures get 3x
        # the default weight; monuments (footage) still rotate in occasionally.
        # Any topic can override with an explicit "weight" field.
        weights = [t.get("weight", 1 if t.get("footage") else 3) for t in avail]
        chosen = rng.choices(avail, weights=weights, k=1)[0]
    else:
        # Pool exhausted (every topic used within 30 days). Instead of a random
        # pick from the full pool (which can repeat yesterday's → duplicate
        # uploads), choose the LEAST-recently-used topic so spacing is maximal.
        last_used: dict[str, str] = {}
        for h in state["history"]:
            last_used[h["title"]] = h["date"]  # later entries win → most recent date
        chosen = min(pool, key=lambda t: last_used.get(t["title"], "0000-00-00"))
    # PENDING reservation — confirmed by run.py via confirm_topic() only after the
    # video actually reaches its primary channel. Expires after RESERVE_HOURS so a
    # failed run gives the topic back instead of burning it (see RESERVE_HOURS).
    state["history"].append({
        "title": chosen["title"],
        "date": date.today().isoformat(),
        "pending": True,
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    state["history"] = state["history"][-500:]
    sp.write_text(json.dumps(state, indent=2, ensure_ascii=False))
    print(f"[topic] reserved '{chosen['title']}' (pending, expires in {RESERVE_HOURS}h)")

    return {
        "kind": "viral",
        "title": chosen["title"],
        "hook": chosen.get("hook", ""),
        "angle": chosen.get("hook", ""),
        "query": chosen.get("query", ""),
        "footage": bool(chosen.get("footage", False)),
        "wiki": chosen["title"].split(":")[0].replace(" ", "_"),
        "tags": ["viral", "trending"],
    }


def pick_trending(seed_offset: int = 0) -> dict:
    """Pick today's content: nearby festival > FRESH viral pool > legacy deity.
    Pass seed_offset to vary the pick on the same day (multi-drop schedule).
    """
    topics = load_topics()
    today = date.today()
    # Festival in next 5 days wins — but ONLY for the FIRST drop of the day
    # (seed_offset <= 1). Otherwise every drop in a multi-drop niche returns the
    # SAME festival → duplicate videos (e.g. 2x "Summer Solstice Stonehenge").
    # Later drops (seed 2, 3) fall through to the fresh viral pool instead.
    if seed_offset <= 1:
        for fest in topics.get("festivals_calendar", []):
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
    # FRESH viral pool (researched, 30-day recency) — the anti-repetition engine.
    viral = pick_viral(seed_offset)
    if viral:
        return viral

    # Legacy fallback: weighted random deity from the static pool.
    pool = topics.get("trending_deities", topics.get("deities", []))
    if not pool:
        return {"kind": "deity", "title": "Lord Shiva", "wiki": "Shiva", "tags": ["shiva"]}
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
