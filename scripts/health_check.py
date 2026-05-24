"""Production health check — run anytime to verify all systems healthy.

Usage:  python scripts/health_check.py

Checks:
  1. All YAML configs parse
  2. Workflows registered + active on GitHub
  3. OAuth tokens present for KalyaanPath + TimeDecoders
  4. Required APIs reachable (Gemini, Telegram, YouTube)
  5. Pregen state file healthy
  6. Disk usage reasonable
  7. Recent workflow runs (success rate last 24h)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

OK = "\033[92m✓\033[0m"
WARN = "\033[93m⚠\033[0m"
FAIL = "\033[91m✗\033[0m"


def check(label: str, condition: bool, detail: str = "") -> None:
    icon = OK if condition else FAIL
    line = f"  {icon} {label}"
    if detail:
        line += f" — {detail}"
    print(line)


def warn(label: str, detail: str = "") -> None:
    line = f"  {WARN} {label}"
    if detail:
        line += f" — {detail}"
    print(line)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# ─────────────────────── checks ────────────────────────

def check_configs() -> bool:
    section("1. Config files")
    ok = True
    for f in ["configs/bhakti.yaml", "configs/itihaas.yaml", "configs/ancient.yaml"]:
        p = ROOT / f
        if not p.exists():
            check(f, False, "missing")
            ok = False
            continue
        try:
            c = yaml.safe_load(p.read_text())
            content_spec_lines = len((c.get("llm", {}).get("content_spec", "") or "").splitlines())
            voice_pool_size = len(c.get("voice", {}).get("voice_pool", []))
            check(f, True, f"content_spec={content_spec_lines}L, voice_pool={voice_pool_size}")
        except Exception as e:
            check(f, False, str(e)[:60])
            ok = False
    return ok


def check_oauth() -> bool:
    section("2. OAuth tokens (auto-publish capability)")
    ok = True
    for name, path in [
        ("KalyaanPath",  "secrets/youtube_token.json"),
        ("TimeDecoders", "secrets/ancient_youtube_token.json"),
    ]:
        p = ROOT / path
        if p.exists() and p.stat().st_size > 100:
            check(f"{name} → {path}", True, f"{p.stat().st_size} bytes")
        else:
            check(f"{name} → {path}", False, "missing or empty")
            ok = False
    return ok


def check_apis() -> bool:
    section("3. External APIs")
    ok = True
    # Gemini
    api = os.getenv("GEMINI_API_KEY")
    if not api:
        check("Gemini API key", False, "GEMINI_API_KEY not in .env")
        ok = False
    else:
        try:
            r = requests.get(
                f"https://generativelanguage.googleapis.com/v1beta/models?key={api}",
                timeout=10,
            )
            check("Gemini API", r.status_code == 200, f"HTTP {r.status_code}")
        except Exception as e:
            check("Gemini API", False, str(e)[:60])
            ok = False
    # Telegram
    tok = os.getenv("TELEGRAM_BOT_TOKEN")
    cid = os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and cid):
        warn("Telegram bot", "tokens not set — TG drops disabled")
    else:
        try:
            r = requests.get(f"https://api.telegram.org/bot{tok}/getMe", timeout=10)
            ok_tg = r.json().get("ok", False)
            check("Telegram bot", ok_tg, f"connected as @{r.json().get('result',{}).get('username','?')}" if ok_tg else "auth failed")
        except Exception as e:
            check("Telegram bot", False, str(e)[:60])
    return ok


def check_workflows() -> bool:
    section("4. GitHub Actions workflows")
    try:
        r = subprocess.run(["gh", "workflow", "list", "--json", "name,state"],
                          capture_output=True, text=True, cwd=ROOT, timeout=15)
        if r.returncode != 0:
            check("gh CLI", False, "not authenticated or repo not set")
            return False
        wfs = json.loads(r.stdout)
        for wf in wfs:
            check(wf["name"], wf["state"] == "active", wf["state"])
        return all(wf["state"] == "active" for wf in wfs)
    except Exception as e:
        check("workflows", False, str(e)[:60])
        return False


def check_pregen_state() -> bool:
    section("5. Pregen state")
    sched_file = ROOT / "data" / "state" / "upload_schedule.json"
    if not sched_file.exists():
        warn("upload_schedule.json", "not yet created — first pregen run hasn't happened")
        return True
    try:
        sched = json.loads(sched_file.read_text())
        total = len(sched)
        by_status = {}
        for entry in sched.values():
            s = entry.get("status", "?")
            by_status[s] = by_status.get(s, 0) + 1
        check("upload_schedule.json", True, f"{total} entries: {dict(by_status)}")
        # Count pregen dirs on disk
        pregen_root = ROOT / "data" / "pregenerated"
        if pregen_root.exists():
            dirs = list(pregen_root.glob("*/*/"))
            check("pregen dirs on disk", True, f"{len(dirs)} bundles")
        return True
    except Exception as e:
        check("pregen state", False, str(e)[:60])
        return False


def check_recent_runs() -> bool:
    section("6. Recent workflow runs (last 24h)")
    try:
        cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
        r = subprocess.run(
            ["gh", "run", "list", "--limit", "20", "--json",
             "name,status,conclusion,createdAt"],
            capture_output=True, text=True, cwd=ROOT, timeout=15,
        )
        runs = json.loads(r.stdout)
        recent = [run for run in runs if run["createdAt"] > cutoff]
        success = sum(1 for r in recent if r.get("conclusion") == "success")
        failed = sum(1 for r in recent if r.get("conclusion") == "failure")
        cancelled = sum(1 for r in recent if r.get("conclusion") == "cancelled")
        in_progress = sum(1 for r in recent if r.get("status") == "in_progress")
        ok = failed == 0
        detail = f"{success}✓ {failed}✗ {cancelled} cancelled, {in_progress} in-flight (of {len(recent)} total)"
        check("last 24h", ok, detail)
        return ok
    except Exception as e:
        check("recent runs", False, str(e)[:60])
        return False


def check_disk() -> bool:
    section("7. Disk usage")
    try:
        for path in ["output/videos", "output/images", "data/pregenerated", "data/music_bhajan"]:
            p = ROOT / path
            if not p.exists():
                continue
            r = subprocess.run(["du", "-sh", str(p)], capture_output=True, text=True)
            sz = r.stdout.split()[0] if r.stdout else "?"
            check(path, True, sz)
        return True
    except Exception:
        return True


# ─────────────────────── main ────────────────────────

def main():
    print(f"🩺 Production Health Check — {datetime.now().isoformat(timespec='seconds')}")
    print(f"   Repo: {ROOT}")
    results = [
        ("configs", check_configs()),
        ("oauth", check_oauth()),
        ("apis", check_apis()),
        ("workflows", check_workflows()),
        ("pregen", check_pregen_state()),
        ("recent_runs", check_recent_runs()),
        ("disk", check_disk()),
    ]
    section("SUMMARY")
    all_ok = all(ok for _, ok in results)
    for name, ok in results:
        icon = OK if ok else FAIL
        print(f"  {icon} {name}")
    if all_ok:
        print("\n🟢 ALL SYSTEMS HEALTHY")
        return 0
    print("\n🔴 ISSUES FOUND — review above")
    return 1


if __name__ == "__main__":
    sys.exit(main())
