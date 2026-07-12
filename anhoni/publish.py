#!/usr/bin/env python3
"""ANHONI publisher — post final_<slug> to YouTube + Instagram + Facebook.
  python publish.py <slug>
YouTube: public Short (Anhoni title/desc/tags from story_<slug>.json) via the
re-authed lakeerein token. IG+FB: Cloudinary + Make webhook (one scenario -> both).
Reuses creds from bhakti-reels (.env + lakeerein/ token). Isolated; never raises
on IG/FB failure (YT is primary)."""
import os, sys, json, time, hashlib, requests
from pathlib import Path

OUT = Path(__file__).parent
LK = OUT.parent / "lakeerein"
ENV = OUT.parent / ".env"; E = dict(os.environ)
if ENV.exists():
    for l in ENV.read_text().splitlines():
        if "=" in l and not l.strip().startswith("#"):
            k, v = l.split("=", 1); E.setdefault(k.strip(), v.strip())

def publish_yt(spec, mp4):
    cs = json.load(open(LK / "yt_client_secret.json"))["installed"]
    tok = json.load(open(LK / "yt_token_lakeerein.json"))
    at = requests.post("https://oauth2.googleapis.com/token", data={"client_id": cs["client_id"], "client_secret": cs["client_secret"],
        "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"}, timeout=60).json()["access_token"]
    H = {"Authorization": f"Bearer {at}"}
    tags = spec.get("hashtags", ["anhoni"])[:15]
    desc = spec.get("caption", "") + "\n\n#shorts " + " ".join("#" + t.replace(" ", "") for t in tags)
    meta = {"snippet": {"title": spec["title"], "description": desc, "tags": tags, "categoryId": "24"},
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}}
    init = requests.post("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        headers={**H, "Content-Type": "application/json; charset=UTF-8"}, data=json.dumps(meta).encode("utf-8"), timeout=60)
    up = init.headers.get("Location")
    if not up: print("YT INIT FAIL", init.status_code, init.text[:200]); return None
    data = Path(mp4).read_bytes()
    res = requests.put(up, headers={**H, "Content-Type": "video/mp4", "Content-Length": str(len(data))}, data=data, timeout=900).json()
    if "id" in res:
        link = "https://youtube.com/shorts/" + res["id"]; print("YT PUBLISHED:", link); return link
    print("YT UPLOAD FAIL", res); return None

def publish_ig_fb(spec, mp4):
    try:
        CLOUD, K, S = E["CLOUDINARY_CLOUD_NAME"], E["CLOUDINARY_API_KEY"], E["CLOUDINARY_API_SECRET"]
        WEBHOOK = E["LAKEEREIN_IG_WEBHOOK"]
        ts = str(int(time.time())); folder = "anhoni"
        sig = hashlib.sha1((f"folder={folder}&timestamp={ts}" + S).encode()).hexdigest()
        with open(mp4, "rb") as f:
            r = requests.post(f"https://api.cloudinary.com/v1_1/{CLOUD}/video/upload",
                data={"api_key": K, "timestamp": ts, "folder": folder, "signature": sig},
                files={"file": (Path(mp4).name, f, "video/mp4")}, timeout=300)
        if r.status_code != 200: print("CLOUDINARY ERR", r.status_code, r.text[:200]); return
        url = r.json()["secure_url"]; print("CLOUDINARY:", url)
        cap = spec.get("caption", "") + "\n\n" + " ".join("#" + t.replace(" ", "") for t in spec.get("hashtags", ["anhoni"]))
        w = requests.post(WEBHOOK, json={"video_url": url, "caption": cap}, timeout=120)
        print("WEBHOOK (IG+FB):", w.status_code)
    except Exception as e:
        print("IG/FB skipped:", e)

def main(slug):
    spec = json.loads((OUT / f"story_{slug}.json").read_text())
    mp4 = OUT / "out" / slug / "final.mp4"
    print("== YouTube =="); yt = publish_yt(spec, mp4)
    print("== Instagram + Facebook =="); publish_ig_fb(spec, mp4)
    print("\nDONE — YT:", yt)
    return yt

if __name__ == "__main__":
    main(sys.argv[1])
