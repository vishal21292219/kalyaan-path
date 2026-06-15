#!/usr/bin/env python3
"""Lakeerein AUTO video pipeline (improved). One topic -> premium unique video:
  1. Claude writes a premium emotional Hindi nostalgia script (strong hook, varied
     arc, per-scene visual prompt + emotion + stickman motion).
  2. fal flux-pro generates UNIQUE cinematic images per scene (no repeats ever).
  3. render_story.py animates locked stickman + Chem narration + music (no caption).
Usage: python make_video.py "<topic>" <slug>
Standalone, isolated."""
import os, sys, json, subprocess, re
from pathlib import Path
import requests
OUT=Path(__file__).parent
ENV=Path.home()/"Documents/Vishal Projects/bhakti-reels/.env"
if ENV.exists():  # local only; on CI secrets are already in os.environ
    for l in ENV.read_text().splitlines():
        if "=" in l and not l.strip().startswith("#"):
            k,v=l.split("=",1); os.environ.setdefault(k.strip(),v.strip())
import fal_client
ANTHROPIC=os.environ["ANTHROPIC_API_KEY"]

MOTIONS="crouch, book, bat, eat, jump, wave, lookup, tired, dream"
HY_S={"crouch":(1026,112),"bat":(953,80),"eat":(953,82),"tired":(951,88),"dream":(946,90)}
DEF=(935,82)  # book/wave/jump/lookup
MUSIC_ROTATE=["lk_music.mp3","music_rich.mp3"]

SYS=f"""You are a master short-form storyteller for an Indian Hinglish emotional-nostalgia
YouTube Shorts channel called Lakeerein (stickman animation). Write a 6-scene script
for ONE Short on the given topic.

HARD RULES:
- Language: warm conversational HINDI (Devanagari). NO emojis in spoken lines.
- Scene 1 MUST be a scroll-STOPPING hook — a surprising/specific/emotional first line
  that makes the viewer freeze in 2 seconds. Never start with a generic "yaad hai...".
- Build a real emotional arc; the LAST line must land an unexpected, heart-touching punch.
  Vary endings (don't always say "call kar lena" / "kaash").
- Each line short & punchy (max ~14 words), spoken in ~4-6s.
- Per scene give a CINEMATIC image prompt (English): a specific nostalgic Indian scene,
  photoreal, warm film grade, fine grain, NO people, NO text. Each scene's image MUST be
  visually DIFFERENT from the others.
- Pick emotion from: happy, excited, sad, wistful.
- Pick stickman motion from: {MOTIONS}.

Return ONLY strict JSON:
{{"title":"<Hinglish YT title with 1 emoji + #shorts>",
"scenes":[{{"line":"<hindi>","img_prompt":"<english cinematic, no people no text>","emo":"<>","motion":"<>"}}, ...6 ]}}"""

def claude_script(topic):
    r=requests.post("https://api.anthropic.com/v1/messages",
        headers={"x-api-key":ANTHROPIC,"anthropic-version":"2023-06-01","content-type":"application/json"},
        json={"model":"claude-opus-4-8","max_tokens":2000,"system":SYS,
              "messages":[{"role":"user","content":f"Topic: {topic}"}]},timeout=120)
    if r.status_code!=200: print("CLAUDE ERR",r.status_code,r.text[:300]); sys.exit(1)
    txt=r.json()["content"][0]["text"]
    m=re.search(r"\{.*\}",txt,re.S)
    return json.loads(m.group(0))

def gen_image(prompt,out):
    full=prompt.strip().rstrip(".")+", cinematic nostalgic photograph, warm film grade, kodak portra, fine film grain, shallow depth of field, no people, no text, vertical 9:16, emotional, beautiful"
    r=fal_client.subscribe("fal-ai/flux-pro/v1.1",arguments={"prompt":full,"image_size":"portrait_16_9","num_inference_steps":28,"guidance_scale":3.5,"num_images":1,"output_format":"jpeg"},with_logs=False)
    out.write_bytes(requests.get(r["images"][0]["url"],timeout=90).content)

def main(topic,slug):
    print("SCRIPT via Claude...")
    sc=claude_script(topic)
    print("  title:",sc["title"])
    scenes=[]
    for i,s in enumerate(sc["scenes"],1):
        img=f"{slug}_{i}"
        print(f"  IMG {i}: {s['img_prompt'][:50]}...")
        gen_image(s["img_prompt"],OUT/f"{img}.jpg")
        hy,sz=HY_S.get(s["motion"],DEF)
        scenes.append({"img":img,"emo":s["emo"],"motion":s["motion"],"hy":hy,"s":sz,"line":s["line"]})
        print(f"     \"{s['line']}\"  [{s['emo']}/{s['motion']}]")
    music=MUSIC_ROTATE[sum(ord(c) for c in slug)%len(MUSIC_ROTATE)]
    spec={"id":slug,"title":sc["title"],"music":music,"scenes":scenes}
    (OUT/f"story_{slug}.json").write_text(json.dumps(spec,ensure_ascii=False,indent=1))
    print("RENDER...")
    subprocess.run([sys.executable,str(OUT/"render_story.py"),str(OUT/f"story_{slug}.json")],check=True)
    print("DONE ->", OUT/f"final_{slug}.mp4","| title:",sc["title"])

if __name__=="__main__":
    main(sys.argv[1], sys.argv[2])
