#!/usr/bin/env python3
"""ANHONI story generator — expands a seed premise into a full premium story_spec
JSON (dialogue-driven suspense comic, 10 panels, character-locked) via Claude.
  python story_gen.py "<seed>" <slug>   -> writes story_<slug>.json
Isolated; reads ANTHROPIC_API_KEY from bhakti-reels/.env or env."""
import os, sys, json, re, urllib.request
from pathlib import Path

OUT = Path(__file__).parent
ENV = OUT.parent / ".env"
E = dict(os.environ)
if ENV.exists():
    for l in ENV.read_text().splitlines():
        if "=" in l and not l.strip().startswith("#"):
            k, v = l.split("=", 1); E.setdefault(k.strip(), v.strip())
KEY = E["ANTHROPIC_API_KEY"]
MODEL = "claude-opus-4-8"   # story is the soul — use the strongest model

SCHEMA = """Output ONLY one JSON object (no markdown, no prose) with EXACTLY this shape:
{
  "slug": "kebab-case-short",
  "title": "YouTube title: Hindi hook + | Anhoni #shorts  (<=90 chars, curiosity-gap, no clickbait lies)",
  "characters": { "<key>": "<very detailed FIXED visual description: age, face shape, skin tone, hair, exact clothes & colours, one distinctive feature>" },
  "music_prompt": "dark cinematic suspense background music, <mood>, tense, no vocals, no drums",
  "panels": [
    { "id": 1, "chars": ["<key>"], "bubble": "thought|speech|caption", "who": "<Name or empty>",
      "text": "<SHORT Hindi/Hinglish line, <= 9 words, fits a comic bubble>",
      "speaker": [0.5, 0.4],
      "prompt": "<scene: the character(s) doing an action + emotion + setting; premium comic; simple clear hand poses>" }
  ],
  "caption": "<Instagram/FB caption: 2-3 line hook + 'Part 2 ke liye Follow karo' + a fiction disclaimer>",
  "hashtags": ["anhoni", "..."]
}"""

RULES = """You are the star writer of ANHONI — a PREMIUM Hindi SUSPENSE / THRILLER / MYSTERY
comic channel. Your stories must be so gripping that people watch till the very end and
NEED Part 2. This is NOT cheap horror-shock — it is smart, eerie, twisty suspense.

QUALITY BAR (non-negotiable — a boring or predictable story is a FAILURE):
- PANEL 1 = a killer hook: an image + line that instantly plants a burning question. No slow setup.
- EVERY line must add tension or new information. Zero filler, zero repeated beats, no padding.
- Build logically: normal → something's off → it gets worse → a TWIST that re-frames what we already saw.
- The twist must be genuinely surprising yet FAIR (small clues were planted earlier). Never random.
- Panel 10 (caption) = a REAL cliffhanger: a fresh shocking reveal that makes Part 2 essential. Do NOT resolve the mystery.
- Dialogue = natural spoken Hinglish, sharp and SHORT (<= 8 words; bubbles are tiny). Real people, real fear/suspicion/denial.

FORMAT:
- EXACTLY 10 panels. Mostly "speech" (two characters talking) + 1-2 "thought". Panel 10 MUST be "caption".
- 1-2 recurring characters; each gets an ULTRA-detailed FIXED look (age, face, skin, hair, exact clothes+colours, one distinctive feature) — this locks them across panels.
- "speaker" = [x,y] (0..1) head position of whoever speaks/thinks that panel.
- "prompt" = vivid SCENE + the character's action & emotion + a rich detailed setting. SIMPLE hand poses (hands at sides / holding one object / in pockets) — avoid pointing/complex gestures.

POLICY: no gore/blood, no sexual content, no real named victims. Suspense/mystery/supernatural-lite. Fiction.
Deliver a story you'd be proud to put your name on."""

def generate(seed, slug):
    prompt = f"{RULES}\n\nSEED: {seed}\n\nUse slug \"{slug}\".\n\n{SCHEMA}"
    body = json.dumps({"model": MODEL, "max_tokens": 4000,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        blocks = json.load(r)["content"]
    txt = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    m = re.search(r"\{.*\}", txt, re.S)
    spec = json.loads(m.group(0))
    assert len(spec["panels"]) == 10, "need 10 panels"
    assert spec["panels"][-1]["bubble"] == "caption", "panel 10 must be caption"
    spec["slug"] = slug
    (OUT / f"story_{slug}.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2))
    print(f"STORY OK: {slug} — {spec['title']}  ({len(spec['characters'])} chars, 10 panels)")
    return spec

if __name__ == "__main__":
    generate(sys.argv[1], sys.argv[2])
