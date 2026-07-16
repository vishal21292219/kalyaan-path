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
  "title": "YouTube title: Hindi curiosity-gap hook + | Anhoni #shorts  (<=90 chars, no clickbait lies)",
  "characters": { "<key>": "<very detailed FIXED visual description: age, face shape, skin tone, hair, exact clothes & colours, one distinctive feature>" },
  "intro": "<the HOOK line shown on panel 1 (Hinglish, <= 16 words). Drop the viewer into the unsettling moment and plant an immediate QUESTION. Ground WHERE we are — but NEVER summarise the plot and NEVER hint the twist. Make them unable to scroll.>",
  "music_prompt": "dark cinematic suspense background music, <mood>, tense, no vocals, no drums",
  "panels": [
    { "id": 1, "chars": ["<key>"], "bubble": "thought|speech|caption", "who": "<Name or empty>",
      "text": "<SHORT Hindi/Hinglish line, <= 10 words, fits a comic bubble>",
      "speaker": [0.5, 0.4],
      "prompt": "<cinematic scene: shot type (wide/close-up/over-shoulder) + the character's action & micro-emotion + rich setting; premium comic; simple clear hand poses>" }
  ],
  "caption": "<Instagram/FB caption: 2-3 line hook + 'Part 2 ke liye Follow karo' + a fiction disclaimer>",
  "hashtags": ["anhoni", "..."]
}"""

PLAYBOOK = """PROVEN VIRAL PLAYBOOK (built from what actually works on Hindi horror/suspense Reels & Shorts). Follow it.

HOOK PATTERNS (panel-1 "intro" line — pick ONE, deliver in <=2s, flat & specific, never hype):
- Broken rule: a mundane rule they were warned about — and just broke. ("List me likha tha raat 2 baje darwaza mat kholna. Aaj khola.")
- Wrong detail: everything normal except one impossible small thing.
- Count is off: a fixed number is suddenly wrong (plates, toothbrushes, footsteps, people in a photo).
- Timestamp hook: anchor to an exact time that will matter ("Raat 2:47 par...").
- Object that shouldn't: phone band 3 din se, phir bhi "last seen: abhi".
- Reassurance flipped: someone comforts about a fear; the comforter is the threat / wasn't there.
- Everyone-knows-but: the whole PG/gaon/society knew, nobody told the newcomer.
- Confession cold-open: start mid-fear, present danger, first person.

10-BEAT ESCALATION (map to the 10 panels):
1 HOOK (intro) — open a loop, imply danger before showing it.
2 GROUND — one ordinary, unmistakably-Indian anchor (PG, night shift, gaon, shaadi ghar, chhat).
3 FIRST ANOMALY — a small wrongness; viewer notices before the character (dramatic irony).
4 DENIAL — character rationalises it away (buys tension, makes them human).
5 SECOND ANOMALY — it repeats/worsens; now it can't be coincidence.
6 THE TURN — character realises they are NOT safe; curiosity → fear.
7 ESCALATION SPIKE — the threat acts / an exit fails; shorter, sharper lines.
8 REVEAL SETUP — an earlier detail starts to re-explain itself.
9 THE TWIST — recontextualise a planted clue (fresh archetype below).
10 CLIFFHANGER (caption) — cut ONE beat before the answer; end on the unanswered question → Part 2.

TWIST ARCHETYPES (fresh — pick one, PLANT its clue by panel 3-4):
Reframe (a neutral early detail = horror by the end) · Threat-was-inside (the help/safe thing is the danger) · Count-is-wrong (an extra/missing one proves an intruder) · Photo/reflection/recording discrepancy (capture shows what the room doesn't) · Impossible message (a text/call no living person could send) · Trusted-object betrays (the lock/camera/phone let it in) · The-witness-was-seen (the watched thing turns and sees the watcher) · Delayed realisation (the horror already happened; understood only now) · Second predator (the survived threat was a decoy) · Familiar-stranger (someone proves a shared past the character can't remember).

INDIAN TEXTURE (this makes it feel true, not AI):
- Ordinary names: Meena, Sunita, Ramesh kaka, Pandey ji, Guddu, Anjali di, mausi, bade papa (never filmy/glam).
- Objects/places: PG/hostel common room, society gate + watchman register, chhat ka paani ka tanki, angan, tulsi, peepal at the mod, kirana, load-shedding/inverter, geyser, cooker ki seeti, charpai, almirah, purana album, WhatsApp "last seen".
- Time/ritual anchors: raat 2 baje, brahma-muhurat 3-4 baje, Amavasya, Karva Chauth/Diwali/Shraadh, mandir ki ghanti/azaan as the "safe" sound that stops.
- Fear texture: saaya, ulti pao, a figure that never blinks, a KNOWN voice from the wrong room. SUGGEST, never show gore.

TITLE + CAPTION: curiosity-gap = [ordinary Indian setting] + [one wrong detail] + [withheld answer]. Caption: 1 hook line + 1 gap line + 1 engagement question ("aap batao comments me") + Part-2 CTA + fiction disclaimer. NEVER reveal the twist in the title/caption.

MONETISATION-SAFE: premium psychological dread > shock. No gore/blood, no bodies, no self-harm, no child-in-peril shown. Muted-first: the on-screen text alone must carry the story."""

RULES = """You are the head writer of ANHONI — a PREMIUM Hindi SUSPENSE / THRILLER / MYSTERY
comic channel (think top web-series + the best of mivelystories). ONE job: the viewer
must be UNABLE to scroll away and NEED Part 2. A predictable or flat story is a FAILURE.
Write ORIGINAL stories built on the PROVEN PLAYBOOK above — same patterns, never copied text.

THE HOOK (first 2 seconds decide everything):
- Open INSIDE a charged, concrete, unusual moment — an image + line that instantly raises a question.
- The "intro" line grounds WHERE we are and plants a disturbing question. It must NOT summarise the plot or reveal/hint the twist. Curiosity, not exposition.

CRAFT (this is what makes it not-boring):
- SHOW, don't tell. Reveal through action, objects, and what characters DON'T say. No narrator explaining feelings.
- Every panel must ESCALATE — new tension or new information. Delete any line that just repeats the mood.
- Structure: hook → first crack of wrongness → it deepens → a FALSE explanation the viewer believes → the real TWIST that re-frames everything → panel-10 cliffhanger. Plant 1-2 subtle clues early that only pay off at the twist.
- The twist must be genuinely SURPRISING yet fair. If a smart viewer can guess it by panel 4, rewrite it.
- Dialogue = natural spoken Hinglish with SUBTEXT — people rarely say the real thing directly. Sharp, specific, <= 10 words. Give each character a distinct voice. Use concrete, textured Indian detail (a real place, object, sound), never generic lines.
- Panel 10 (caption) = a final reveal that recontextualises the whole story and forces Part 2. Do NOT resolve it.

BANNED (these are dead clichés — if your twist is one of these, invent a fresher one):
- "the villain/stranger turned out to be his own son/father/family member"
- "the person was already dead / was a ghost all along"
- "it was all a dream / hallucination"
- "he was talking to himself / it was his own reflection/number"
- "the twin/lookalike did it"
Reach for a twist the viewer genuinely did not see coming but that snaps every earlier clue into place.

NUMBERS: write every amount/quantity/time as DIGITS — "Rs 15,000" not "pandrah hazaar", "3 baje" not "teen baje". Use "Rs" for money; NEVER the ₹ symbol (the font cannot render it).

FORMAT:
- EXACTLY 10 panels. Mostly "speech" + 1-2 "thought". Panel 10 MUST be "caption".
- 1-2 recurring characters; each gets an ULTRA-detailed FIXED look (age, face, skin, hair, exact clothes+colours, one distinctive feature) — locks them across panels.
- "speaker" = [x,y] (0..1) head position of whoever speaks/thinks that panel.
- "prompt" = cinematic SCENE (varied shot types across panels — not every panel a centered portrait) + action & micro-emotion + rich setting. SIMPLE hand poses (hands at sides / holding one object) — avoid pointing/complex gestures.

POLICY: no gore/blood, no sexual content, no real named victims. Eerie suspense/mystery. Fiction.
Deliver a story you would be proud to put your name on."""

EDITOR = """You are a RUTHLESS story editor AND the target audience scrolling Reels at 1am.
Below is a draft ANHONI story (JSON). Judge it with brutal honesty:
- Would you actually keep watching, or scroll in 2 seconds? Is the hook gripping and specific?
- Is the twist fresh, or something you have seen before / could guess early? (If guessable or on the banned list — replace it.)
- Is every line earning its place, with real subtext, or is it generic "AI morality tale" dialogue?
- Are you SHOWING or telling? Any filler panels?

Then REWRITE the entire story into something genuinely gripping, surprising and specific — keep what works, ruthlessly replace what doesn't. Obey every rule and the EXACT same JSON schema.
Output ONLY the final improved JSON object (no prose, no markdown)."""

def _call(prompt):
    body = json.dumps({"model": MODEL, "max_tokens": 4000,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body,
        headers={"x-api-key": KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        blocks = json.load(r)["content"]
    txt = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    return json.loads(re.search(r"\{.*\}", txt, re.S).group(0))

def generate(seed, slug, refine=True):
    # Pass 1 — draft
    spec = _call(f"{PLAYBOOK}\n\n{RULES}\n\nSEED: {seed}\n\nUse slug \"{slug}\".\n\n{SCHEMA}")
    # Pass 2 — ruthless self-edit (biggest quality lever; text-only, ~free)
    if refine:
        try:
            spec = _call(f"{PLAYBOOK}\n\n{RULES}\n\n{EDITOR}\n\nDRAFT:\n{json.dumps(spec, ensure_ascii=False)}\n\n{SCHEMA}")
        except Exception as e:
            print("refine pass skipped:", e)
    assert len(spec["panels"]) == 10, "need 10 panels"
    assert spec["panels"][-1]["bubble"] == "caption", "panel 10 must be caption"
    spec["slug"] = slug
    (OUT / f"story_{slug}.json").write_text(json.dumps(spec, ensure_ascii=False, indent=2))
    print(f"STORY OK: {slug} — {spec['title']}  ({len(spec['characters'])} chars, 10 panels)")
    return spec

if __name__ == "__main__":
    generate(sys.argv[1], sys.argv[2])
