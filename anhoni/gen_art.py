#!/usr/bin/env python3
"""ANHONI art generator — character-locked premium comic panels via fal.
  python gen_art.py <slug>
1) one comic reference portrait per character (flux/dev)
2) each panel = nano-banana/edit with the character reference(s) -> SAME faces
Reads story_<slug>.json; writes out/<slug>/raw/panel_XX.png. Isolated."""
import os, sys, json, time, urllib.request, urllib.error
from pathlib import Path

OUT = Path(__file__).parent
ENV = OUT.parent / ".env"
E = dict(os.environ)
if ENV.exists():
    for l in ENV.read_text().splitlines():
        if "=" in l and not l.strip().startswith("#"):
            k, v = l.split("=", 1); E.setdefault(k.strip(), v.strip())
KEY = E["FAL_KEY"]

STYLE = ("premium high-detail 2D comic book illustration, bold clean black ink outlines, rich cel shading, "
         "warm saturated colours, highly detailed background environment with depth, cinematic dramatic lighting, "
         "Indian graphic novel style, expressive faces, characters in foreground, vertical composition, "
         "NOT photorealistic, no text, no speech bubbles, no watermark")
GUARD = ("STRICT ANATOMY: every person has exactly one head, TWO arms and TWO hands with five fingers each, and two legs. "
         "NO third arm/hand, NO extra or floating hands, NO duplicated or deformed limbs/fingers. Correct human proportions. "
         "Prefer simple clear hand poses.")

def fal(model, body, timeout=180):
    req = urllib.request.Request("https://fal.run/" + model, data=json.dumps(body).encode(),
        headers={"Authorization": "Key " + KEY, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def first(d):
    v = d.get("images"); return v[0]["url"] if v else None

def main(slug):
    spec = json.loads((OUT / f"story_{slug}.json").read_text())
    raw = OUT / "out" / slug / "raw"; raw.mkdir(parents=True, exist_ok=True)
    # 1) references
    refs = {}
    for key, desc in spec["characters"].items():
        url = first(fal("fal-ai/flux/dev", {"prompt": f"full body character reference of {desc}, {STYLE}, clean plain grey background, front view",
            "image_size": "portrait_4_3", "num_inference_steps": 30, "guidance_scale": 3.5, "enable_safety_checker": False}))
        refs[key] = url
        print(f"ref {key}: ok")
    # 2) panels
    for p in spec["panels"]:
        imgs = [refs[c] for c in p.get("chars", []) if c in refs]
        prompt = (f"Comic book panel. Use the provided character reference image(s) and draw the SAME character(s) with identical "
                  f"face, hair and clothes, in this scene: {p['prompt']}. {STYLE}. Keep character identity consistent. {GUARD} "
                  f"No text, no speech bubbles.")
        body = {"prompt": prompt, "image_urls": imgs, "num_images": 1} if imgs else \
               {"prompt": prompt, "image_size": "portrait_16_9", "num_inference_steps": 30, "enable_safety_checker": False}
        model = "fal-ai/nano-banana/edit" if imgs else "fal-ai/flux/dev"
        out = raw / f"panel_{p['id']:02d}.png"
        for a in range(3):
            try:
                url = first(fal(model, body)); urllib.request.urlretrieve(url, out)
                print(f"panel {p['id']:02d}: ok ({out.stat().st_size//1024}KB)"); break
            except urllib.error.HTTPError as e:
                m = e.read().decode()[:160]; print(f"panel {p['id']:02d}: HTTP {e.code} {m}")
                if "balance" in m.lower(): raise SystemExit("FAL BALANCE EXHAUSTED")
                time.sleep(3)
            except Exception as e:
                print(f"panel {p['id']:02d}: {e}"); time.sleep(3)
    print("ART DONE ->", raw)

if __name__ == "__main__":
    main(sys.argv[1])
