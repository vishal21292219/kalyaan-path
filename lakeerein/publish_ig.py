#!/usr/bin/env python3
"""Publish a Lakeerein video to Instagram via Cloudinary + Make webhook.
  python publish_ig.py <video.mp4> "<caption>"
1. Uploads mp4 to Cloudinary (signed) -> public direct URL.
2. POSTs {video_url, caption} to the Make webhook -> Make creates the IG Reel.
Standalone, isolated."""
import os, sys, time, hashlib
from pathlib import Path
import requests
OUT=Path(__file__).parent
ENV=Path.home()/"Documents/Vishal Projects/bhakti-reels/.env"
E=dict(os.environ)  # CI: secrets are in env; local: filled from .env below
if ENV.exists():
    for l in ENV.read_text().splitlines():
        if "=" in l and not l.strip().startswith("#"):
            k,v=l.split("=",1); E.setdefault(k.strip(),v.strip())
CLOUD=E["CLOUDINARY_CLOUD_NAME"]; KEY=E["CLOUDINARY_API_KEY"]; SEC=E["CLOUDINARY_API_SECRET"]
WEBHOOK=E["LAKEEREIN_IG_WEBHOOK"]

def cloudinary_upload(path):
    ts=str(int(time.time()))
    folder="lakeerein"
    to_sign=f"folder={folder}&timestamp={ts}"
    sig=hashlib.sha1((to_sign+SEC).encode()).hexdigest()
    with open(path,"rb") as f:
        r=requests.post(f"https://api.cloudinary.com/v1_1/{CLOUD}/video/upload",
            data={"api_key":KEY,"timestamp":ts,"folder":folder,"signature":sig},
            files={"file":(Path(path).name,f,"video/mp4")},timeout=300)
    if r.status_code!=200:
        print("CLOUDINARY ERR",r.status_code,r.text[:300]); sys.exit(1)
    url=r.json()["secure_url"]
    print("CLOUDINARY URL:",url)
    return url

def prune_old(prefix="lakeerein/",days=2):
    """Delete Cloudinary reels older than `days` (FB/IG already ingested). Non-fatal."""
    import datetime
    try:
        r=requests.get(f"https://api.cloudinary.com/v1_1/{CLOUD}/resources/video/upload",
            params={"prefix":prefix,"max_results":100},auth=(KEY,SEC),timeout=30)
        if r.status_code!=200: return
        cutoff=time.time()-days*86400; old=[]
        for res in r.json().get("resources",[]):
            try: t=datetime.datetime.fromisoformat(res.get("created_at","").replace("Z","+00:00")).timestamp()
            except: continue
            if t<cutoff: old.append(res["public_id"])
        if old:
            requests.delete(f"https://api.cloudinary.com/v1_1/{CLOUD}/resources/video/upload",
                params=[("public_ids[]",p) for p in old],auth=(KEY,SEC),timeout=60)
            print(f"pruned {len(old)} old Cloudinary reels")
    except Exception as e:
        print("prune skipped:",e)

def trigger(url,caption):
    r=requests.post(WEBHOOK,json={"video_url":url,"caption":caption},timeout=120)
    print("WEBHOOK:",r.status_code,r.text[:200])

def main(video,caption):
    prune_old()
    url=cloudinary_upload(video)
    trigger(url,caption)
    print("DONE — Make will create the reel on @lakeereinstories")

if __name__=="__main__":
    main(sys.argv[1], sys.argv[2])
