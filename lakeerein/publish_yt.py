#!/usr/bin/env python3
"""Publish a Lakeerein video to YouTube (Shorts) from the new pipeline.
  python publish_yt.py <slug> [publishAt_ISO_UTC]
Reads title from story_<slug>.json, uploads final_<slug>.mp4 to the Lakeerein
channel. Public if no publishAt, else scheduled (private->auto-public). Isolated."""
import json, sys, requests
from pathlib import Path
OUT=Path(__file__).parent

TAGS=["nostalgia","bachpan","90s kids","childhood memories","emotional","hindi story","yaadein","relatable","lakeerein"]

def desc_from(story):
    lines=[s["line"] for s in story["scenes"]]
    body=f"{lines[0]}\n{lines[-1]}\n\nहर लकीर, एक कहानी। ❤️ Lakeerein\n\n#shorts #nostalgia #90skids #bachpan #childhoodmemories #emotional #hindistory #yaadein #relatable #lakeerein"
    return body

def publish_yt(slug, publish_at=None):
    story=json.loads((OUT/f"story_{slug}.json").read_text())
    mp4=OUT/f"final_{slug}.mp4"
    cs=json.load(open(OUT/"yt_client_secret.json"))["installed"]
    tok=json.load(open(OUT/"yt_token_lakeerein.json"))
    at=requests.post("https://oauth2.googleapis.com/token",data={"client_id":cs["client_id"],"client_secret":cs["client_secret"],"refresh_token":tok["refresh_token"],"grant_type":"refresh_token"},timeout=60).json()["access_token"]
    H={"Authorization":f"Bearer {at}"}
    status={"selfDeclaredMadeForKids":False}
    if publish_at: status.update({"privacyStatus":"private","publishAt":publish_at})
    else: status.update({"privacyStatus":"public"})
    meta={"snippet":{"title":story["title"],"description":desc_from(story),"tags":TAGS,"categoryId":"24"},"status":status}
    init=requests.post("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        headers={**H,"Content-Type":"application/json; charset=UTF-8"},data=json.dumps(meta).encode(),timeout=60)
    up=init.headers.get("Location")
    if not up: print("INIT FAIL",init.status_code,init.text[:200]); sys.exit(1)
    data=mp4.read_bytes()
    res=requests.put(up,headers={**H,"Content-Type":"video/mp4","Content-Length":str(len(data))},data=data,timeout=600).json()
    if "id" in res:
        link=f"https://youtube.com/shorts/{res['id']}"
        print(("SCHEDULED " if publish_at else "PUBLISHED ")+link)
        return link
    print("UPLOAD FAIL",res); sys.exit(1)

if __name__=="__main__":
    publish_yt(sys.argv[1], sys.argv[2] if len(sys.argv)>2 else None)
