#!/usr/bin/env python3
"""Self-healing watchdog.

Runs on its own cron (.github/workflows/health-check.yml), OFFSET from the other
crons, so GitHub skipping a poster/gen cron can't strand reels for long. Every run:

  1. AUTO-FIX: runs the poster (post_pending_reels.py) → any due-but-stuck reel
     gets posted immediately (the #1 recurring failure: GitHub skips a poster
     cron and reels sit in the queue).
  2. AUDIT: counts what's delivered today, what's still overdue in the queue
     (AFTER the poster ran), and which workflow runs FAILED in the last 8h
     (GitHub API).
  3. REPORT: one clean Discord line — 🟢 all good / 🟡 fixed-or-pending / 🔴
     failures — so a status check returns a verdict, not a pile of "X failed".

Never raises into CI — always exits 0 so the watchdog itself can't go red.
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_SLOTS = 9  # 3 active channels (godmind/ancient/moneurons) × 3 drops


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(s: str):
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _run_poster() -> None:
    """Auto-fix: fire any due reel stuck in the queue. Idempotent (ledger dedup +
    per-page gap guard), so running it here on top of the poster cron is safe."""
    try:
        subprocess.run([sys.executable, "post_pending_reels.py"], cwd=str(ROOT), timeout=600)
    except Exception as e:
        print(f"[health] poster run failed: {type(e).__name__}: {e}")


def _queue_overdue() -> tuple[int, int]:
    """(total pending, overdue) — overdue = due >5min ago but still queued AFTER
    the poster ran (i.e. it genuinely couldn't post → a real FB/Make problem)."""
    try:
        recs = json.loads((ROOT / "data/state/pending_reels.json").read_text() or "[]")
    except Exception:
        return 0, 0
    cut = (_now() - datetime.timedelta(minutes=5)).isoformat()
    overdue = sum(1 for r in recs if str(r.get("post_at", "")) < cut)
    return len(recs), overdue


def _delivered_today() -> int:
    try:
        pl = json.loads((ROOT / "data/state/published_log.json").read_text())
        v = pl.get(_now().date().isoformat(), {})
        return len(v) if isinstance(v, dict) else 0
    except Exception:
        return 0


def _recent_failures(hours: int = 8) -> list[str]:
    repo = os.getenv("GITHUB_REPOSITORY")
    tok = os.getenv("GITHUB_TOKEN")
    if not (repo and tok):
        return []
    try:
        r = requests.get(
            f"https://api.github.com/repos/{repo}/actions/runs",
            headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"},
            params={"per_page": 40}, timeout=30,
        )
        cut = _now() - datetime.timedelta(hours=hours)
        out = []
        for run in r.json().get("workflow_runs", []):
            if run.get("conclusion") != "failure":
                continue
            # ignore the watchdog itself so it never reports on itself
            if "Health" in (run.get("name") or ""):
                continue
            t = _parse(run.get("created_at"))
            if t and t >= cut:
                out.append(run.get("name") or "?")
        return out
    except Exception as e:
        print(f"[health] gh api failed: {e}")
        return []


def _discord(msg: str) -> None:
    dw = os.getenv("DISCORD_WEBHOOK")
    if not dw:
        return
    try:
        requests.post(dw, json={"content": msg}, timeout=20)
    except Exception as e:
        print(f"[health] discord failed: {e}")


def main() -> int:
    _run_poster()  # 1. auto-fix stuck queue FIRST

    total, overdue = _queue_overdue()
    delivered = _delivered_today()
    fails = _recent_failures()

    # status: red on failures, yellow if a reel is genuinely stuck after posting,
    # green otherwise.
    if fails:
        status = "🔴"
    elif overdue > 0:
        status = "🟡"
    else:
        status = "🟢"

    lines = [
        f"{status} *Pipeline health* — {_now().strftime('%m-%d %H:%M')}Z",
        f"• Delivered today: {delivered}/{EXPECTED_SLOTS}",
        f"• Queue: {total} pending" + (f" ({overdue} STUCK ⚠️)" if overdue else " (none overdue)"),
    ]
    if fails:
        c = Counter(fails)
        lines.append("• ❌ Failed runs (8h): " + ", ".join(f"{n}× {k}" for k, n in c.items()))
        lines.append("  (catch-up/retry will re-attempt; check if it repeats)")
    else:
        lines.append("• Workflows: all green ✓")
    if overdue and not fails:
        lines.append("• ⚠️ A reel couldn't post even after the poster ran — likely an FB/Make token issue, take a look.")

    msg = "\n".join(lines)
    print(msg)
    _discord(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
