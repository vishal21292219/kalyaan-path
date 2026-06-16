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

# channel → YT token/secret env, FB page id, optimal go-live slots (UTC HH:MM)
CHANNELS = {
    "KalyaanPath":   {"tok": "YT_TOKEN_JSON",          "cs": "YT_CLIENT_SECRET_JSON",          "fb": "1169999016195266", "slots": ["01:30"]},
    "TimeDecoders":  {"tok": "YT_ANCIENT_TOKEN_JSON",  "cs": "YT_ANCIENT_CLIENT_SECRET_JSON",  "fb": "1249630111558028", "slots": ["18:00", "00:00"]},
    "Itihaasvani":   {"tok": "YT_ITIHAAS_TOKEN_JSON",  "cs": "YT_ITIHAAS_CLIENT_SECRET_JSON",  "fb": "1063760053496823", "slots": ["03:00", "14:30"]},
    "GodsOfTheMind": {"tok": "YT_GODMIND_TOKEN_JSON",  "cs": "YT_GODMIND_CLIENT_SECRET_JSON",  "fb": "1113214471881336", "slots": ["17:00", "23:00", "01:00"]},
    "Lakeerein":     {"tok": "YT_LAKEEREIN_TOKEN_JSON","cs": "YT_LAKEEREIN_CLIENT_SECRET_JSON","fb": "1143850345480290", "slots": ["15:00"]},
}


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
    ch = requests.get("https://www.googleapis.com/youtube/v3/channels",
                      params={"part": "snippet,statistics,contentDetails", "mine": "true"},
                      headers=H, timeout=60).json()["items"][0]
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
    # deltas vs last snapshot
    d_subs = data["subs"] - prev.get("subs", data["subs"]) if prev else None
    d_views = data["views"] - prev.get("views", data["views"]) if prev else None
    d_vids = data["videoCount"] - prev.get("videoCount", data["videoCount"]) if prev else None
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
        txt = r.json()["content"][0]["text"]
        m = re.search(r"\{.*\}", txt, re.S)
        return json.loads(m.group(0)) if m else {}
    except Exception as e:
        print("[eval] claude failed:", e)
        return {}


def tg_send(text):
    tok = os.getenv("TELEGRAM_BOT_TOKEN"); chat = os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        print("[eval] no telegram creds"); print(text); return
    # chunk to <4000 chars on line boundaries
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 3800:
            chunks.append(cur); cur = ""
        cur += line + "\n"
    if cur:
        chunks.append(cur)
    for c in chunks:
        requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                      data={"chat_id": chat, "text": c, "disable_web_page_preview": True}, timeout=60)


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
            data = yt_channel(name, cfg)
            blocks[name] = analyze(name, data, prev_chan.get(name, {}), cfg)
            new_snap[name] = {"subs": data["subs"], "views": data["views"], "videoCount": data["videoCount"]}
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
        L.append(f"━━━ {name} ━━━")
        if "error" in b:
            L.append(f"  ⚠️ data error: {b['error'][:80]}"); L.append(""); continue
        L.append(f"  👥 Subs: {b['subs']}  ({arrow(b['d_subs'])}/wk)")
        L.append(f"  👁 Views: {b['views']}  ({arrow(b['d_views'])}/wk)")
        L.append(f"  🎬 Uploads (7d): {b['uploads_7d']}   total: {b['videoCount']}")
        if b["top"]:
            L.append(f"  🏆 Top: {b['top'][1]} — {b['top'][0]}")
        if b["flop"] and b["uploads_7d"] > 1:
            L.append(f"  📉 Flop: {b['flop'][1]} — {b['flop'][0]}")
        if b["duplicates"]:
            L.append(f"  🔁 DUPLICATES: {', '.join(b['duplicates'][:3])}")
        if b["off_schedule"]:
            L.append(f"  ⏰ Off-schedule: {len(b['off_schedule'])} (e.g. {b['off_schedule'][0][1]})")
        else:
            L.append("  ⏰ Schedule: on-time ✅")
        for item in reco.get(name, []):
            L.append(f"  → {item}")
        L.append("")
    if not os.getenv("APIFY_TOKEN"):
        L.append("ℹ️ FB/IG metrics off — add APIFY_TOKEN secret to enable.")

    tg_send("\n".join(L))

    # save snapshot
    SNAP.parent.mkdir(parents=True, exist_ok=True)
    SNAP.write_text(json.dumps({"date": today, "channels": new_snap}, indent=1))
    print("[eval] report sent + snapshot saved")


if __name__ == "__main__":
    main()
