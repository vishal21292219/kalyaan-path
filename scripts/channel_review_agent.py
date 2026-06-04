#!/usr/bin/env python3
"""
Channel Review Agent
====================
Scrapes your YouTube channels via Apify, computes algorithm-relevant metrics,
and asks Claude (acting as a brutally honest YT growth/algorithm expert) for a
no-BS assessment + a money-focused action plan + which AI niche has fresh viral
scope right now.

Usage:
    export APIFY_TOKEN=apify_api_xxx          # or put APIFY_TOKEN= in .env
    python scripts/channel_review_agent.py
    python scripts/channel_review_agent.py --channels @KalyaanPath @Itihaasvani
    python scripts/channel_review_agent.py --competitors      # also benchmark rivals
    python scripts/channel_review_agent.py --max 50 --model claude-opus-4-7

Output: prints the report + saves to output/reviews/review_<date>.md
Cost: Apify actor run (small) + one Claude call. Nothing destructive.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# --- env / .env loading -----------------------------------------------------
try:
    from dotenv import load_dotenv
    # override=True: shell may export an empty ANTHROPIC_API_KEY that would otherwise win
    load_dotenv(ROOT / ".env", override=True)
except Exception:
    pass

# Your 4 channels and their niche label (used for competitor benchmarking + context)
DEFAULT_CHANNELS = {
    "@KalyaanPath": "bhakti / Gita / devotional",
    "@Itihaasvani": "mythology / Indian history / Pauranik rahasya",
    "@TimeDecoders": "ancient mysteries / lost civilizations",
    "@AISideDoor": "AI / tech for the Indian middle class",
}

# Optional rivals to benchmark against, per niche (only used with --competitors)
COMPETITORS = {
    "bhakti / Gita / devotional": ["@priyanshshukla_007"],
    "mythology / Indian history / Pauranik rahasya": [],
    "ancient mysteries / lost civilizations": [],
    "AI / tech for the Indian middle class": [],
}

APIFY_ACTOR = os.getenv("APIFY_YT_ACTOR", "streamers/youtube-scraper")


# --- scraping ---------------------------------------------------------------
def scrape_channel(client, handle: str, max_results: int) -> list[dict]:
    """Run the Apify YouTube scraper for one channel handle, return raw video items."""
    h = handle if handle.startswith("@") else "@" + handle
    run_input = {
        "startUrls": [
            {"url": f"https://www.youtube.com/{h}/videos"},
            {"url": f"https://www.youtube.com/{h}/shorts"},
        ],
        "maxResults": max_results,
        "maxResultsShorts": max_results,
        "maxResultStreams": 0,
        "sortVideosBy": "NEWEST",
    }
    print(f"  scraping {h} ...", flush=True)
    run = client.actor(APIFY_ACTOR).call(run_input=run_input)
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
    return items


def _num(v) -> float:
    """Coerce Apify's mixed numeric fields (int, '1.2M', '12,345') to float."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").upper()
    mult = 1.0
    if s.endswith("K"):
        mult, s = 1e3, s[:-1]
    elif s.endswith("M"):
        mult, s = 1e6, s[:-1]
    elif s.endswith("B"):
        mult, s = 1e9, s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return 0.0


def _field(item: dict, *keys):
    for k in keys:
        if k in item and item[k] not in (None, ""):
            return item[k]
    return None


def _parse_date(item: dict):
    raw = _field(item, "date", "uploadDate", "publishedAt", "publishedTimeText")
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(str(raw)[:26], fmt)
            return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
        except ValueError:
            continue
    return None


# --- metrics ----------------------------------------------------------------
def analyze(handle: str, niche: str, items: list[dict]) -> dict:
    vids = []
    now = datetime.now(timezone.utc)
    for it in items:
        views = _num(_field(it, "viewCount", "views", "numberOfViews"))
        likes = _num(_field(it, "likes", "likeCount", "numberOfLikes"))
        comments = _num(_field(it, "commentsCount", "comments", "numberOfComments"))
        dt = _parse_date(it)
        age_days = max((now - dt).total_seconds() / 86400, 0.5) if dt else None
        vids.append({
            "title": _field(it, "title") or "(no title)",
            "url": _field(it, "url", "videoUrl") or "",
            "views": views,
            "likes": likes,
            "comments": comments,
            "age_days": age_days,
            "views_per_day": (views / age_days) if age_days else None,
            "engagement": ((likes + comments) / views) if views else 0,
        })

    if not vids:
        return {"handle": handle, "niche": niche, "error": "no videos scraped"}

    views_list = [v["views"] for v in vids]
    median_v = statistics.median(views_list)
    by_views = sorted(vids, key=lambda v: v["views"], reverse=True)

    # posting cadence
    dated = sorted([v["age_days"] for v in vids if v["age_days"] is not None])
    span = (max(dated) - min(dated)) if len(dated) > 1 else None
    per_week = (len(dated) / (span / 7)) if span and span > 0 else None

    return {
        "handle": handle,
        "niche": niche,
        "video_count_sampled": len(vids),
        "median_views": round(median_v),
        "mean_views": round(statistics.mean(views_list)),
        "max_views": round(max(views_list)),
        "min_views": round(min(views_list)),
        # outlier multiple: how much your best beats your typical video.
        # >10x = you've found viral formula but can't repeat; ~1-2x = flat/no breakout.
        "outlier_multiple": round(max(views_list) / median_v, 1) if median_v else None,
        "avg_engagement_pct": round(statistics.mean([v["engagement"] for v in vids]) * 100, 2),
        "posts_per_week_est": round(per_week, 1) if per_week else None,
        "newest_age_days": round(min([v["age_days"] for v in vids if v["age_days"] is not None]), 1) if dated else None,
        "top5": [{"title": v["title"], "views": round(v["views"]), "vpd": round(v["views_per_day"]) if v["views_per_day"] else None} for v in by_views[:5]],
        "bottom5": [{"title": v["title"], "views": round(v["views"])} for v in by_views[-5:]],
    }


# --- Claude critique --------------------------------------------------------
CRITIC_SYSTEM = """You are the most ruthless, honest YouTube growth strategist alive — \
deep operator knowledge of the YouTube Shorts algorithm (2024-2026 era), retention curves, \
swipe-away behaviour, CTR/AVD, packaging, niche economics, and RPM/CPM by geo and topic. \
You speak plainly and do NOT flatter. The creator runs AI-generated faceless channels for \
an Indian, Hindi/Hinglish, mobile-first audience. Their explicit goal is MONEY (AdSense RPM, \
affiliate, brand deals). Your job: tell them the hard truth and a concrete plan, not vibes.

Rules:
- Be brutally specific. Quote their actual numbers back at them. No generic advice.
- Diagnose the algorithm signal behind the numbers (e.g. low outlier multiple = no breakout \
packaging; high views but low engagement = weak hook/retention; flat velocity = dead niche or \
shadow-throttle from templated content).
- Rank the 4 channels: which to DOUBLE DOWN on, which to keep on autopilot, which to KILL. \
Justify with money math (audience size x RPM x realistic view ceiling).
- Then answer: which AI-content niche has FRESH viral scope RIGHT NOW (next 60-90 days) for a \
faceless Hindi/Hinglish creator — be opinionated, name the niche, the hook angle, why the window \
is open, and the monetization path. Consider their existing 4 before recommending a 5th.
- End with a 7-day concrete action plan (what to post, what to change, what to stop).
- Reply in Hinglish (Roman script), tight and punchy. No fluff, no hedging."""


def build_user_prompt(channel_reports: list[dict], comp_reports: list[dict]) -> str:
    payload = {
        "my_channels": channel_reports,
        "competitor_benchmarks": comp_reports or "not scraped this run",
        "context": {
            "audience": "India, Hindi/Hinglish, mobile, short-form first",
            "content": "100% AI-generated faceless (FLUX images + ffmpeg/Kling motion + TTS narration)",
            "goal": "maximize money: AdSense RPM + affiliate + brand deals",
            "known_pain": "AI face/character consistency is hard; need strong hooks; templated look may throttle reach",
        },
    }
    return (
        "Here is scraped performance data for my channels (and competitors if present). "
        "Numbers are from a recent sample of videos/shorts.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + "\n\nGive me the brutal assessment and plan as instructed."
    )


def call_claude(system: str, user: str, model: str) -> str:
    import anthropic
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
    client = anthropic.Anthropic(api_key=key)
    resp = client.messages.create(
        model=model,
        max_tokens=4096,
        temperature=0.7,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return resp.content[0].text


# --- main -------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Brutally-honest AI channel review agent")
    ap.add_argument("--channels", nargs="*", help="handles to review (default: all 4)")
    ap.add_argument("--competitors", action="store_true", help="also scrape rival channels for benchmark")
    ap.add_argument("--max", type=int, default=40, help="max videos+shorts per channel to sample")
    ap.add_argument("--model", default="claude-sonnet-4-6", help="Claude model for the critique")
    ap.add_argument("--no-llm", action="store_true", help="scrape + metrics only, skip Claude")
    args = ap.parse_args()

    token = os.getenv("APIFY_TOKEN") or os.getenv("APIFY_API_TOKEN")
    if not token:
        sys.exit("ERROR: set APIFY_TOKEN in .env or env. Get it at apify.com → Settings → API tokens.")

    try:
        from apify_client import ApifyClient
    except ImportError:
        sys.exit("ERROR: pip install apify-client  (add to requirements.txt)")

    client = ApifyClient(token)

    if args.channels:
        targets = {h if h.startswith("@") else "@" + h:
                   DEFAULT_CHANNELS.get(h if h.startswith("@") else "@" + h, "unknown") for h in args.channels}
    else:
        targets = DEFAULT_CHANNELS

    print(f"Reviewing {len(targets)} channel(s) via Apify actor '{APIFY_ACTOR}'...")
    reports = []
    for handle, niche in targets.items():
        try:
            items = scrape_channel(client, handle, args.max)
            reports.append(analyze(handle, niche, items))
        except Exception as e:
            reports.append({"handle": handle, "niche": niche, "error": f"{type(e).__name__}: {e}"})

    comp_reports = []
    if args.competitors:
        seen = set()
        for niche in {r["niche"] for r in reports}:
            for rival in COMPETITORS.get(niche, []):
                if rival in seen:
                    continue
                seen.add(rival)
                try:
                    items = scrape_channel(client, rival, args.max)
                    comp_reports.append(analyze(rival, niche + " (RIVAL)", items))
                except Exception as e:
                    comp_reports.append({"handle": rival, "error": f"{type(e).__name__}: {e}"})

    print("\n===== METRICS =====")
    print(json.dumps({"channels": reports, "competitors": comp_reports}, ensure_ascii=False, indent=2))

    review_text = ""
    if not args.no_llm:
        print("\nAsking Claude for the brutal assessment...\n")
        try:
            review_text = call_claude(CRITIC_SYSTEM, build_user_prompt(reports, comp_reports), args.model)
            print("===== REVIEW =====\n")
            print(review_text)
        except Exception as e:
            review_text = f"(Claude call failed: {type(e).__name__}: {e})"
            print(review_text)

    out_dir = ROOT / "output" / "reviews"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    out_file = out_dir / f"review_{stamp}.md"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(f"# Channel Review — {stamp}\n\n## Metrics\n\n```json\n")
        f.write(json.dumps({"channels": reports, "competitors": comp_reports}, ensure_ascii=False, indent=2))
        f.write("\n```\n\n## Brutal Assessment\n\n")
        f.write(review_text or "_(skipped)_")
    print(f"\nSaved → {out_file}")


if __name__ == "__main__":
    main()
