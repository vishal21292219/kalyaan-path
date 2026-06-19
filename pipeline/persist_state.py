#!/usr/bin/env python3
"""Robustly persist data/state/*.json to origin/main — the ONE state-committer used
by every workflow (poster, generation, catch-up, retry).

WHY: state lived in ad-hoc `git add data/state/*.json` commits on a busy branch. Those
commits kept LOSING the git-push race, so dedup state never reached origin:
  - posted_reels_log.json lost  → poster re-fired posted reels (45× + repeat FB dup)
  - published_log.json lost      → catch-up/retry regenerated done slots → duplicate YT uploads
  - viral_history lost           → same topic re-picked

FIX: MONOTONIC files (the dedup guarantees — ledger, slot markers, topic history) are
UNION-merged with origin on every attempt so an entry is NEVER lost, then pushed with many
retries → they reliably land. MUTABLE files (queue, retry_queue — which legitimately remove
entries) are pushed best-effort; the poster's url+slot-id dedup makes a stale queue harmless.

Usage: python pipeline/persist_state.py   (from repo root)
"""
import glob, json, os, subprocess, time

STATE_DIR = "data/state"
# Files that must never lose entries (dedup truth). Everything else = best-effort.
def _is_monotonic(path):
    b = os.path.basename(path)
    return b in ("posted_reels_log.json", "published_log.json") or "history" in b


def sh(*a):
    return subprocess.run(a, capture_output=True, text=True)


def _jload(s):
    try:
        return json.loads(s) if s and s.strip() else None
    except Exception:
        return None


def _deep_union(remote, local):
    """Combine so nothing from EITHER side is lost; local wins on leaf conflicts."""
    if isinstance(remote, dict) and isinstance(local, dict):
        out = dict(remote)
        for k, v in local.items():
            out[k] = _deep_union(remote[k], v) if k in remote else v
        return out
    if isinstance(remote, list) and isinstance(local, list):
        seen, out = set(), []
        for it in remote + local:
            key = it.get("title") if isinstance(it, dict) and it.get("title") else json.dumps(it, sort_keys=True, ensure_ascii=False)
            if key not in seen:
                seen.add(key); out.append(it)
        return out
    return local if local is not None else remote


def _merge_monotonic_into_local():
    """For each monotonic file, rewrite local = origin ∪ local (never drop an entry)."""
    for path in glob.glob(f"{STATE_DIR}/*.json"):
        if not _is_monotonic(path):
            continue
        remote = _jload(sh("git", "show", f"origin/main:{path}").stdout)
        local = _jload(open(path).read()) if os.path.exists(path) else None
        if remote is None:
            continue
        merged = _deep_union(remote, local if local is not None else remote)
        json.dump(merged, open(path, "w"), ensure_ascii=False, indent=1)


def main():
    sh("git", "config", "user.email", "actions@github.com")
    sh("git", "config", "user.name", "github-actions[bot]")
    for attempt in range(1, 16):
        sh("git", "fetch", "origin", "main")
        _merge_monotonic_into_local()          # re-union every attempt → entries never lost
        sh("git", "add", STATE_DIR)
        if sh("git", "diff", "--cached", "--quiet").returncode == 0:
            print("[persist] no state changes")
            return
        sh("git", "commit", "-m", "auto: state [skip ci]")
        if (sh("git", "pull", "--rebase", "--autostash", "origin", "main").returncode == 0
                and sh("git", "push").returncode == 0):
            print(f"[persist] state pushed (try {attempt})")
            return
        sh("git", "rebase", "--abort")
        print(f"[persist] push race — retry {attempt}/15")
        time.sleep(4)
    print("::error::[persist] state push FAILED after 15 tries")


if __name__ == "__main__":
    main()
