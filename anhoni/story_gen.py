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
MODEL = "claude-sonnet-5"

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

RULES = """You are the head writer of ANHONI — a premium Hindi SUSPENSE / THRILLER / MYSTERY
comic-story channel (NOT gore/horror-shock; tasteful eerie suspense with a twist).
Write a gripping, dialogue-DRIVEN micro-story from the seed. Requirements:
- EXACTLY 10 panels. Characters TALK to each other (mostly "speech" bubbles) with a few "thought" bubbles. Panel 10 MUST be bubble="caption" = a Part-2 cliffhanger.
- 1 or 2 recurring characters only; give each an ultra-consistent FIXED visual description (this locks their look across panels).
- Strong 3-second HOOK on panel 1. Escalate tension. A real TWIST near the end. Leave an open loop (Part 2).
- Dialogue: natural spoken Hindi/Hinglish, SHORT (bubbles are small). Roman script ok; keep it punchy.
- "speaker" = approximate [x,y] (0..1) head position of whoever is speaking/thinking in that panel, so the tail points right.
- panel "prompt": describe the SCENE + the character's action & emotion + a detailed setting. Prefer SIMPLE hand poses (hands at sides / holding one object / in pockets) — avoid complex pointing/gestures.
- POLICY: no gore, no blood, no sexual content, no real named victims. Keep it suspense/mystery/supernatural-lite. Frame as fiction.
- Make it PREMIUM and genuinely intriguing — the kind people watch till the end and follow for Part 2."""

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
