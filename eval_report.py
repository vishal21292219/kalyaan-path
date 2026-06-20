#!/usr/bin/env python3
"""Weekly EVAL REPORT → Telegram.

Per YouTube channel (and FB page if APIFY_TOKEN is set):
  - subscribers + views (this week's growth vs last snapshot — rising?)
  - # uploads this week
  - was the upload schedule right (publish hours vs each channel's optimal slots)
  - duplicate videos detected (same/near title)
  - top + flop video of the week
  - Claude action items per channel
Saves a weekly snapshot (data/state/eval_snapshot.json) to compute next week's deltas.

Env: YT_*_TOKEN_JSON + YT_*_CLIENT_SECRET_JSON, ANTHROPIC_API_KEY,
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, (optional) APIFY_TOKEN.
"""
import os
import re
import json
import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).resolve().parent
SNAP = ROOT / "data/state/eval_snapshot.json"

# channel → YT token/secret env, YT handle (Apify fallback), FB page id, optimal slots (UTC)
CHANNELS = {
    "KalyaanPath":   {"tok": "YT_TOKEN_JSON",          "cs": "YT_CLIENT_SECRET_JSON",          "yt": "@KalyaanPath",    "fb": "1169999016195266", "slots": ["01:30"]},
    "TimeDecoders":  {"tok": "YT_ANCIENT_TOKEN_JSON",  "cs": "YT_ANCIENT_CLIENT_SECRET_JSON",  "yt": "@TimeDecoders",   "fb": "1249630111558028", "slots": ["18:00", "00:00"]},
    "Itihaasvani":   {"tok": "YT_ITIHAAS_TOKEN_JSON",  "cs": "YT_ITIHAAS_CLIENT_SECRET_JSON",  "yt": "@Itihaasvani",    "fb": "1063760053496823", "slots": ["03:00", "14:30"]},
    "GodsOfTheMind": {"tok": "YT_GODMIND_TOKEN_JSON",  "cs": "YT_GODMIND_CLIENT_SECRET_JSON",  "yt": "@GodsOfTheMind",  "fb": "1113214471881336", "slots": ["17:00", "23:00", "01:00"]},
    "MoneyNeurons":  {"tok": "YT_MONEURONS_TOKEN_JSON","cs": "YT_MONEURONS_CLIENT_SECRET_JSON","yt": "@moneurons",      "fb": "61590740474028",  "slots": ["17:00", "22:00", "01:00"]},
    "Lakeerein":     {"tok": "YT_LAKEEREIN_TOKEN_JSON","cs": "YT_LAKEEREIN_CLIENT_SECRET_JSON","yt": "@LakeereinStories","fb": "1143850345480290","slots": ["15:00"]},
}
APIFY = os.getenv("APIFY_TOKEN")


def _apify(actor, payload, timeout=300):
    """Run an Apify actor synchronously and return its dataset items (or [])."""
    if not APIFY:
        return []
    try:
        r = requests.post(
            f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items",
            params={"token": APIFY, "timeout": timeout}, json=payload, timeout=timeout + 30)
        if r.status_code in (200, 201):
            return r.json()
        print(f"[eval] apify {actor} HTTP {r.status_code}: {r.text[:150]}")
    except Exception as e:
        print(f"[eval] apify {actor} err: {e}")
    return []


def yt_apify(handle):
    """Public YT channel scrape (no OAuth) → same shape as yt_channel."""
    items = _apify("streamers~youtube-scraper", {
        "startUrls": [{"url": f"https://www.youtube.com/{handle}/videos"}],
        "maxResults": 20, "maxResultsShorts": 20, "maxResultStreams": 0, "sortVideosBy": "NEWEST"})
    vids, subs, ctitle = [], None, handle
    for it in items:
        subs = subs or it.get("numberOfSubscribers") or it.get("channelSubscriberCount")
        ctitle = it.get("channelName") or ctitle
        d = it.get("date") or it.get("publishedAt") or ""
        vids.append({"title": it.get("title", ""), "publishedAt": d,
                     "views": int(it.get("viewCount") or 0), "likes": 0, "comments": 0})
    return {"title": ctitle, "subs": int(subs) if subs else None,
            "views": None, "videoCount": None, "videos": vids, "src": "apify"}


def fb_apify(page_id):
    """Public FB page posts scrape → recent {title, views, time}."""
    items = _apify("apify~facebook-posts-scraper",
                   {"startUrls": [{"url": f"https://www.facebook.com/{page_id}"}], "resultsLimit": 12})
    posts = []
    for it in items:
        posts.append({"title": (it.get("text") or "")[:45], "time": it.get("time", ""),
                      "views": int(it.get("viewsCount") or 0)})
    return posts


def fb_analyze(posts):
    n = _now(); wk = n - datetime.timedelta(days=7)
    recent = []
    for p in posts:
        try:
            t = datetime.datetime.fromisoformat(str(p["time"]).replace("Z", "+00:00"))
        except Exception:
            continue
        if t >= wk:
            recent.append(p)
    seen, dups = {}, []
    for p in posts[:15]:
        k = _norm(p["title"])
        if k and k in seen:
            dups.append(p["title"][:30])
        elif k:
            seen[k] = 1
    rv = sorted(recent, key=lambda x: x["views"], reverse=True)
    return {"posts_7d": len(recent), "top": (rv[0]["views"] if rv else 0), "dups": dups}


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _refresh(tok_env, cs_env):
    tok = json.loads(os.environ[tok_env])
    cs = json.loads(os.environ[cs_env])
    cs = cs.get("installed") or cs.get("web") or cs
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": cs["client_id"], "client_secret": cs["client_secret"],
        "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"}, timeout=60)
    return r.json()["access_token"]


def _norm(title):
    t = (title or "").lower()
    t = re.sub(r"#\w+", "", t)
    t = "".join(c for c in t if c.isalnum() or c == " ")
    return re.sub(r"\s+", " ", t).strip()


def yt_channel(name, cfg):
    at = _refresh(cfg["tok"], cfg["cs"])
    H = {"Authorization": f"Bearer {at}"}
    chr_ = requests.get("https://www.googleapis.com/youtube/v3/channels",
                        params={"part": "snippet,statistics,contentDetails", "mine": "true"},
                        headers=H, timeout=60).json()
    if not chr_.get("items"):
        raise RuntimeError(f"channels.list empty: {json.dumps(chr_)[:200]}")
    ch = chr_["items"][0]
    st = ch["statistics"]
    up = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    pl = requests.get("https://www.googleapis.com/youtube/v3/playlistItems",
                      params={"part": "contentDetails", "playlistId": up, "maxResults": 20},
                      headers=H, timeout=60).json()
    ids = [x["contentDetails"]["videoId"] for x in pl.get("items", [])]
    vids = []
    if ids:
        vr = requests.get("https://www.googleapis.com/youtube/v3/videos",
                          params={"part": "snippet,statistics,contentDetails", "id": ",".join(ids)},
                          headers=H, timeout=60).json()
        for v in vr.get("items", []):
            vids.append({
                "title": v["snippet"]["title"],
                "publishedAt": v["snippet"]["publishedAt"],
                "views": int(v["statistics"].get("viewCount", 0)),
                "likes": int(v["statistics"].get("likeCount", 0)),
                "comments": int(v["statistics"].get("commentCount", 0)),
            })
    return {
        "title": ch["snippet"]["title"],
        "subs": int(st.get("subscriberCount", 0)),
        "views": int(st.get("viewCount", 0)),
        "videoCount": int(st.get("videoCount", 0)),
        "videos": vids,
    }


def analyze(name, data, prev, cfg):
    """Build a per-channel metrics block (deltas, uploads, schedule, dups, top/flop)."""
    n = _now()
    wk = n - datetime.timedelta(days=7)
    recent = []
    for v in data["videos"]:
        try:
            pub = datetime.datetime.fromisoformat(v["publishedAt"].replace("Z", "+00:00"))
        except Exception:
            continue
        v["_pub"] = pub
        if pub >= wk:
            recent.append(v)
    # deltas vs last snapshot (None-safe — Apify-scraped channels may lack subs/views)
    def _delta(cur, key):
        if cur is None or not prev or prev.get(key) is None:
            return None
        return cur - prev[key]
    d_subs = _delta(data.get("subs"), "subs")
    d_views = _delta(data.get("views"), "views")
    d_vids = _delta(data.get("videoCount"), "videoCount")
    # schedule check: publish hour vs nearest optimal slot (±60 min)
    slots = [int(s[:2]) * 60 + int(s[3:]) for s in cfg["slots"]]
    off_sched = []
    for v in recent:
        mins = v["_pub"].hour * 60 + v["_pub"].minute
        nearest = min(abs(mins - s) for s in slots) if slots else 0
        nearest = min(nearest, 1440 - nearest)
        if nearest > 60:
            off_sched.append((v["title"][:32], v["_pub"].strftime("%a %H:%MZ")))
    # duplicate detection (recent + a bit older window of 20)
    seen, dups = {}, []
    for v in data["videos"][:20]:
        k = _norm(v["title"])
        if not k:
            continue
        if k in seen:
            dups.append(v["title"][:40])
        else:
            seen[k] = 1
    # top / flop among recent
    rv = sorted(recent, key=lambda x: x["views"], reverse=True)
    top = rv[0] if rv else None
    flop = rv[-1] if len(rv) > 1 else None
    return {
        "title": data["title"], "subs": data["subs"], "views": data["views"],
        "videoCount": data["videoCount"], "d_subs": d_subs, "d_views": d_views, "d_vids": d_vids,
        "uploads_7d": len(recent), "off_schedule": off_sched, "duplicates": dups,
        "top": (top["title"][:40], top["views"]) if top else None,
        "flop": (flop["title"][:40], flop["views"]) if flop else None,
        "recent_titles": [v["title"][:50] for v in recent],
    }


def claude_reco(blocks):
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return {}
    compact = {k: {x: v[x] for x in ("subs", "d_subs", "d_views", "uploads_7d",
              "off_schedule", "duplicates", "top", "flop")} for k, v in blocks.items()}
    sys = ("You are a faceless-content growth analyst. For EACH channel below, give "
           "2-3 SHORT, specific, prioritized action items (max ~12 words each) based on "
           "its metrics — schedule fixes, dup issues, frequency, what's working/not. "
           "Be blunt and practical. Return ONLY JSON: {\"<channel>\": [\"item1\", \"item2\"]}.")
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-opus-4-8", "max_tokens": 1500, "system": sys,
                  "messages": [{"role": "user", "content": json.dumps(compact, default=str)}]}, timeout=120)
        resp = r.json()
        if "content" not in resp:
            print("[eval] claude error resp:", json.dumps(resp)[:300])
            return {}
        txt = resp["content"][0]["text"]
        m = re.search(r"\{.*\}", txt, re.S)
        return json.loads(m.group(0)) if m else {}
    except Exception as e:
        print("[eval] claude failed:", e)
        return {}


def tg_send(text):
    tok = os.getenv("TELEGRAM_BOT_TOKEN"); chat = os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        print("[eval] no telegram creds"); print(text); return
    # 1) Full report as a .txt document — ALWAYS opens regardless of length/format.
    try:
        rd = requests.post(f"https://api.telegram.org/bot{tok}/sendDocument",
                           data={"chat_id": chat, "caption": "📊 Weekly Eval Report (full — open file)"},
                           files={"document": ("eval_report.txt", text.encode("utf-8"))}, timeout=60)
        print(f"[eval] tg document: {rd.status_code} ok={rd.json().get('ok')}")
    except Exception as e:
        print("[eval] tg document failed:", e)
    # 2) Inline copy, chunked small (2500) + response-checked so failures are visible.
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 2500:
            chunks.append(cur); cur = ""
        cur += line + "\n"
    if cur:
        chunks.append(cur)
    for i, c in enumerate(chunks):
        try:
            r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                              data={"chat_id": chat, "text": c, "disable_web_page_preview": True}, timeout=60)
            if not r.json().get("ok"):
                print(f"[eval] tg chunk {i} FAILED: {r.status_code} {r.text[:160]}")
        except Exception as e:
            print(f"[eval] tg chunk {i} error: {e}")


def discord_send(text):
    """Deliver the report to Discord (Telegram replacement — banned in India).
    Full report as a .txt attachment + chunked inline (Discord 2000-char cap)."""
    hook = (os.getenv("DISCORD_WEBHOOK") or "").strip()
    if not hook:
        print("[eval] no DISCORD_WEBHOOK"); return
    try:
        requests.post(hook, data={"content": "📊 **Weekly Eval Report** (full — open file)"},
                      files={"file": ("eval_report.txt", text.encode("utf-8"))}, timeout=60)
    except Exception as e:
        print("[eval] discord file failed:", e)
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 1800:
            chunks.append(cur); cur = ""
        cur += line + "\n"
    if cur:
        chunks.append(cur)
    for i, c in enumerate(chunks):
        try:
            r = requests.post(hook, json={"content": c}, timeout=60)
            if r.status_code not in (200, 204):
                print(f"[eval] discord chunk {i} FAILED: {r.status_code} {r.text[:160]}")
        except Exception as e:
            print(f"[eval] discord chunk {i} error: {e}")


def main():
    prev_all = {}
    if SNAP.exists():
        try:
            prev_all = json.loads(SNAP.read_text())
        except Exception:
            prev_all = {}
    prev_chan = prev_all.get("channels", {})
    last_date = prev_all.get("date", "—")

    blocks, new_snap = {}, {}
    for name, cfg in CHANNELS.items():
        try:
            try:
                data = yt_channel(name, cfg)
                data["src"] = "oauth"
            except Exception as e:
                if APIFY:
                    print(f"[eval] {name} OAuth failed ({str(e)[:60]}); falling back to Apify")
                    data = yt_apify(cfg["yt"])
                else:
                    raise
            b = analyze(name, data, prev_chan.get(name, {}), cfg)
            b["src"] = data.get("src", "oauth")
            if APIFY:
                try:
                    b["fb"] = fb_analyze(fb_apify(cfg["fb"]))
                except Exception as e:
                    print(f"[eval] {name} FB scrape failed: {e}")
            blocks[name] = b
            new_snap[name] = {"subs": data.get("subs"), "views": data.get("views"), "videoCount": data.get("videoCount")}
        except Exception as e:
            print(f"[eval] {name} failed: {type(e).__name__}: {e}")
            blocks[name] = {"error": str(e)}

    reco = claude_reco({k: v for k, v in blocks.items() if "error" not in v})

    # ---- format report ----
    today = _now().strftime("%d %b %Y")
    L = [f"📊 WEEKLY EVAL REPORT — {today}", f"(vs snapshot: {last_date})", ""]
    def arrow(d):
        if d is None: return "(baseline)"
        return f"▲ +{d}" if d > 0 else (f"▼ {d}" if d < 0 else "= 0")
    for name, b in blocks.items():
        L.append(f"🔸 {name}")
        if "error" in b:
            L.append(f"  ⚠️ data error: {b['error'][:80]}"); L.append(""); continue
        src_tag = " (Apify)" if b.get("src") == "apify" else ""
        subs_str = b["subs"] if b["subs"] is not None else "n/a"
        L.append(f"  👥 Subs: {subs_str}  ({arrow(b['d_subs'])}/wk){src_tag}")
        if b["views"] is not None:
            L.append(f"  👁 Views: {b['views']}  ({arrow(b['d_views'])}/wk)")
        up = f"  🎬 YT uploads (7d): {b['uploads_7d']}"
        if b["videoCount"] is not None:
            up += f"   total: {b['videoCount']}"
        L.append(up)
        if b["top"]:
            L.append(f"  🏆 Top: {b['top'][1]} — {b['top'][0]}")
        if b["flop"] and b["uploads_7d"] > 1:
            L.append(f"  📉 Flop: {b['flop'][1]} — {b['flop'][0]}")
        if b["duplicates"]:
            L.append(f"  🔁 YT DUPLICATES: {', '.join(b['duplicates'][:3])}")
        if b["off_schedule"]:
            L.append(f"  ⏰ Off-schedule: {len(b['off_schedule'])} (e.g. {b['off_schedule'][0][1]})")
        else:
            L.append("  ⏰ Schedule: on-time ✅")
        fb = b.get("fb")
        if fb:
            fl = f"  📘 FB (7d): {fb['posts_7d']} posts, top {fb['top']} views"
            if fb["dups"]:
                fl += f" | 🔁 {len(fb['dups'])} dup"
            L.append(fl)
        for item in reco.get(name, []):
            L.append(f"  → {item}")
        L.append("")
    if not os.getenv("APIFY_TOKEN"):
        L.append("ℹ️ FB/IG metrics off — add APIFY_TOKEN secret to enable.")

    report = "\n".join(L)
    discord_send(report)   # primary (Telegram banned in India)
    tg_send(report)        # legacy — no-ops if Telegram creds unset

    # save snapshot
    SNAP.parent.mkdir(parents=True, exist_ok=True)
    SNAP.write_text(json.dumps({"date": today, "channels": new_snap}, indent=1))
    print("[eval] report sent + snapshot saved")


if __name__ == "__main__":
    main()
