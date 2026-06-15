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

def trigger(url,caption):
    r=requests.post(WEBHOOK,json={"video_url":url,"caption":caption},timeout=120)
    print("WEBHOOK:",r.status_code,r.text[:200])

def main(video,caption):
    url=cloudinary_upload(video)
    trigger(url,caption)
    print("DONE — Make will create the reel on @lakeereinstories")

if __name__=="__main__":
    main(sys.argv[1], sys.argv[2])
