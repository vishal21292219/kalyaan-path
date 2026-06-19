#!/usr/bin/env python3
"""Robustly persist the reel-poster's state to origin/main.

WHY: the dedup ledger (posted_reels_log.json) lived in a single git commit bundled
with the queue, and on a busy branch that commit's push kept LOSING the git race →
the "already posted" record never reached origin → the poster re-fired the same reel
(caused 45× and a repeat duplicate FB post).

FIX: persist in two phases.
  Phase 1 (CRITICAL): the LEDGER. Union-merge origin's ledger into local (so an entry
    is NEVER lost), commit it ALONE, push with many retries. Because only the poster
    writes this file (gen/catch-up no longer touch it) and posters are serialized, the
    union-merge means the push lands cleanly — the dedup guarantee always reaches origin.
  Phase 2 (best-effort): the QUEUE. Even if this loses the race, the ledger already
    blocks any re-post, so a stale queue record is harmless (poster SKIPs + drops it).

Run from repo root after post_pending_reels.py.
"""
import json, os, subprocess, time

LEDGER = "data/state/posted_reels_log.json"
QUEUE = "data/state/pending_reels.json"


def sh(*args):
    return subprocess.run(args, capture_output=True, text=True)


def _jload(s):
    try:
        return json.loads(s) if s.strip() else {}
    except Exception:
        return {}


def _push_one(path, label, tries, merge_ledger=False):
    for i in range(1, tries + 1):
        sh("git", "fetch", "origin", "main")
        if merge_ledger:
            # union: origin ∪ local — never drop a posted-url entry
            remote = sh("git", "show", "origin/main:" + path).stdout
            local = open(path).read() if os.path.exists(path) else "{}"
            merged = _jload(remote)
            merged.update(_jload(local))
            json.dump(merged, open(path, "w"), ensure_ascii=False, indent=1)
        sh("git", "add", path)
        if sh("git", "diff", "--cached", "--quiet").returncode == 0:
            print(f"[{label}] no changes")
            return True
        sh("git", "commit", "-m", f"auto: {label} [skip ci]")
        if (sh("git", "pull", "--rebase", "--autostash", "origin", "main").returncode == 0
                and sh("git", "push").returncode == 0):
            print(f"[{label}] pushed (try {i})")
            return True
        sh("git", "rebase", "--abort")
        print(f"[{label}] push race — retry {i}/{tries}")
        time.sleep(4)
    print(f"::error::[{label}] push FAILED after {tries} tries")
    return False


def main():
    sh("git", "config", "user.email", "actions@github.com")
    sh("git", "config", "user.name", "github-actions[bot]")
    # Phase 1: ledger MUST land (dedup guarantee).
    _push_one(LEDGER, "posted-ledger", tries=15, merge_ledger=True)
    # Phase 2: queue, best-effort.
    _push_one(QUEUE, "reel-queue", tries=6)


if __name__ == "__main__":
    main()
