#!/usr/bin/env python3
"""Auto-replenish a niche's viral-topic pool when it runs low.

So the pipeline NEVER has to repeat topics for lack of fresh ones, and nobody has
to manually top up the pools. Runs on its own cron (.github/workflows/topic-
refill.yml). For each niche:
  1. Count topics NOT used in the last 30 days (the "fresh" pool pick_viral draws
     from).
  2. If fresh < MIN_FRESH, ask the LLM (same provider chain as the script writer:
     Claude → Gemini) to generate brand-new on-brand topics (title + pain-first
     hook) that don't duplicate any existing title.
  3. Append the unique ones and save. The commit is done by the workflow.

Cheap: the LLM is only called when a pool is actually low; otherwise it's a no-op
count. Safe: each niche is independent + guarded, and it never raises into CI.
"""
from __future__ import annotations

import json
import os
import re
import traceback
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

from .utils import ROOT, load_config

load_dotenv()

MIN_FRESH = 30       # below this many unused-in-30d topics → refill
TARGET_FRESH = 60    # top the fresh pool back up to ~this
MAX_POOL = 400       # safety cap on total pool size
MAX_PER_RUN = 40     # cap LLM output per niche per run


def _vf(niche: str) -> Path:
    return ROOT / f"data/viral_topics_{niche}.json"


def _safe_date(s):
    try:
        return date.fromisoformat(str(s))
    except Exception:
        return None


def _fresh_count(pool: list, niche: str) -> int:
    sp = ROOT / f"data/state/viral_history_{niche}.json"
    hist = json.loads(sp.read_text()).get("history", []) if sp.exists() else []
    cut = date.today() - timedelta(days=30)
    recent = {h["title"] for h in hist
              if (_safe_date(h.get("date")) and _safe_date(h["date"]) >= cut)}
    return sum(1 for t in pool if t.get("title") not in recent)


def _parse(txt: str) -> list:
    """Extract a JSON array of {title, hook} from an LLM response (tolerant of
    markdown fences / preamble)."""
    if not txt:
        return []
    t = txt.strip()
    i, j = t.find("["), t.rfind("]")
    if i < 0 or j <= i:
        return []
    try:
        arr = json.loads(t[i:j + 1])
    except Exception:
        return []
    out = []
    for it in arr if isinstance(arr, list) else []:
        if isinstance(it, dict) and it.get("title") and it.get("hook"):
            out.append({"title": str(it["title"]).strip(),
                        "hook": str(it["hook"]).strip()})
    return out


def _generate(niche: str, n: int, existing: set) -> list:
    cfg = load_config(niche)
    llm = cfg.get("llm", {})
    brand = (cfg.get("branding", {}) or {}).get("channel_handle", niche)
    system = (
        f"{llm.get('persona', '')}\n\n"
        f"You generate NEW viral short-form VIDEO TOPICS (not full scripts) for the "
        f"channel {brand}. {llm.get('topic_guidance', '')}"
    ).strip()
    avoid = "\n".join(f"- {t}" for t in sorted(existing))
    user = (
        f"Generate {n} brand-new topics as a JSON array. Each item must be exactly:\n"
        '{"title": "<short scroll-stopping title>", "hook": "<one pain-first, '
        "second-person opening line that names the viewer's feeling, then pivots to "
        'the subject>"}\n\n'
        "Rules: hooks are pain-first and in this channel's voice; every title must be "
        "genuinely DISTINCT from ALL of these existing titles (do NOT rephrase them):\n"
        f"{avoid}\n\nReturn ONLY the JSON array — no preamble, no markdown."
    )
    from .script_writer import _claude, _gemini
    txt = None
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            txt = _claude(system, user, llm.get("model") or "claude-sonnet-4-6")
        except Exception as e:
            print(f"[refill] {niche}: claude failed ({e}); falling back to gemini")
    if not txt:
        txt = _gemini(system, user, llm.get("fallback_model") or "gemini-flash-latest")
    return _parse(txt)


def refill(niche: str) -> int:
    vf = _vf(niche)
    if not vf.exists():
        print(f"[refill] {niche}: no pool file — skip")
        return 0
    data = json.loads(vf.read_text())
    pool = data.get("topics", [])
    fresh = _fresh_count(pool, niche)
    print(f"[refill] {niche}: {len(pool)} topics, {fresh} fresh (min {MIN_FRESH})")
    if fresh >= MIN_FRESH or len(pool) >= MAX_POOL:
        print(f"[refill] {niche}: healthy — no refill needed")
        return 0
    have = {t.get("title", "").lower() for t in pool}
    want = min(TARGET_FRESH - fresh + 5, MAX_PER_RUN)
    gen = _generate(niche, want, {t.get("title", "") for t in pool})
    added = 0
    for t in gen:
        if t["title"].lower() not in have and len(t["hook"]) >= 20:
            pool.append({"title": t["title"], "hook": t["hook"]})
            have.add(t["title"].lower())
            added += 1
    data["topics"] = pool
    vf.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"[refill] {niche}: +{added} new topics → {len(pool)} total")
    return added


def main(niches=None) -> int:
    niches = niches or ["godmind", "ancient", "moneurons"]
    total = 0
    for n in niches:
        try:
            total += refill(n)
        except Exception as e:
            traceback.print_exc()
            print(f"[refill] {n}: FAILED ({e})")
    print(f"[refill] done — {total} topics added across {len(niches)} niche(s)")
    return total


if __name__ == "__main__":
    import sys
    main(sys.argv[1:] or None)
