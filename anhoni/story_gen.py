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
  "intro": "<the HOOK line shown on panel 1 (Hinglish, <= 16 words). Open on an instantly recognisable OFFICE moment that names the shared pain or sets up the joke (e.g. 'POV: din bhar meeting ki, ab manager ka sawaal'). Do NOT give away the panel-10 punchline. Make working people stop scrolling.>",
  "music_prompt": "light quirky corporate background music, <mood: deadpan / playful-tense>, minimal, no vocals",
  "panels": [
    { "id": 1, "chars": ["<key>"], "bubble": "thought|speech|caption", "who": "<Name or empty>",
      "text": "<SHORT Hindi/Hinglish line, <= 10 words, fits a comic bubble>",
      "speaker": [0.5, 0.4],
      "prompt": "<cinematic scene: shot type (wide/close-up/over-shoulder) + the character's action & micro-emotion + rich setting; premium comic; simple clear hand poses>" }
  ],
  "caption": "<Instagram/FB caption: 2-3 line hook + 'Part 2 ke liye Follow karo' + a fiction disclaimer>",
  "hashtags": ["anhoni", "..."]
}"""

PLAYBOOK = """PROVEN VIRAL PLAYBOOK for Hindi/Hinglish CORPORATE relatable Reels & Shorts (India, 2026). Goal: a working person watches and thinks "yeh bilkul mera office hai" and TAGS a colleague. Tone = funny-but-REAL / satire / relatable pain — NOT a tearjerker, NOT horror. The 2026 mood: burnout, "extra mile is dead", quiet-quitting, acting-your-wage; content that VALIDATES employee pain travels furthest. End on a sharp PUNCHLINE or a satisfying KARMA turn.

HOOK PATTERNS (panel-1 "intro" line — pick ONE, deliver in <=2s):
- POV drop: "POV: tumne poora din meeting ki, aur ab manager ka sawaal."
- Relatable-pain call-out: "Sirf working people samjhenge yeh dard."
- Corporate-translation tease: "Boss jo bolta hai vs jo matlab hota hai."
- The biggest office lie: "'Bas 5 minute ka quick call hai' — sabse bada jhooth."
- Say-vs-what-happened: "Appraisal me kya bola vs kya mila."
- The one manager: "Har office me ek aisa manager hota hai jo..."

FOUR WINNING FORMATS (pick the one that fits the seed):
1 SAY-vs-MEAN (corporate translation) — boss speech bubble + a caption "Matlab: <plain truth>". Highest share/"tag your manager" rate.
2 FLASHBACK-STACK — beats 4-6 are timestamped mini-scenes ("9 baje — standup 45 min", "12 baje — alignment call", "4 baje — meeting about next meeting") proving the point. Perfect for meeting-overload / quick-call.
3 KARMA TURN — setup -> escalation -> reversal at beat 9-10 (underdog quietly wins, boss exposed). Most satisfying; best for credit-theft / notice-period / rage-applying.
4 WEEK-ARC — Monday panic -> Friday relief; good for burnout / Sunday-scaries.

10-BEAT STRUCTURE (map to 10 panels):
1 HOOK (intro). 2 GROUND — an unmistakable Indian office (cubicle, glass meeting room, coffee machine, ID lanyard). 3-4 SETUP the relatable situation with SPECIFIC micro-detail. 5-7 ESCALATE the absurdity/injustice (or stack the flashbacks). 8 the turn/realisation. 9 the sharpest beat. 10 (caption) = PUNCHLINE that names the shared pain OR the karma reveal — short, quotable, screenshot-worthy.

TRENDING SCENARIOS to draw from: din-bhar-meeting then "kaam kyun nahi hua"; "5-min quick call" -> 2 ghante; "this could've been an email"; credit-chor boss exposed by CEO; appraisal "great work" -> 2% hike; "we are a family" -> layoff; boss leaves early vs team's leave rejected; fake-busy / alt-tab reflex; HR jargon translation; coffee-badging; infinite "quick sync" loop; notice-period sudden-urgency; intern "great exposure" = free labour; Sunday-scaries + Monday standup; rage-applying karma.

INDIAN TEXTURE (make it real, not generic "office life be like"): ordinary names (Sharma sir, Malhotra, Rohit, Anjali, Meera, HR wali ma'am); micro-details that get shares (2% hike, alt-tab reflex, cold dinner, 45-min standup, "CC: main", ID lanyard, laptop-lunch); a villain everyone recognises (that ONE manager) — but NEVER punch down at juniors; working people share what validates THEIR pain.

MUSIC: light, quirky, corporate-tension or deadpan — NOT sad piano, NOT horror.

TITLE + CAPTION: curiosity-gap = [relatable office situation] + [withheld punchline]. Caption: 1 relatable line + 1 gap line + 1 tag/engagement bait ("tag wo colleague jise yeh dikhani hai") + Part-2 CTA + fiction disclaimer. NEVER give away the punchline in the title.

MONETISATION-SAFE: no vulgarity, no caste/religion slur, no real company/person named. Muted-first: the on-screen text alone must carry the whole joke."""

RULES = """You are the head writer of ANHONI — a Hindi/Hinglish CORPORATE RELATABLE comic channel.
Every story is office/work life that makes a working person laugh, wince, and TAG a colleague.
Tone = funny-but-REAL / satire / relatable pain — NOT a tearjerker, NOT horror. End on a sharp
PUNCHLINE or a satisfying KARMA turn. A generic, preachy, or laugh-less story is a FAILURE.
Write ORIGINAL stories on the CORPORATE PLAYBOOK above.

THE HOOK (first 2 seconds decide everything):
- Open on an instantly recognisable office moment. The "intro" line names the shared pain or sets up the joke — WITHOUT giving away the punchline.

CRAFT (what makes it shareable, not cringe):
- SHOW the absurdity through specific micro-details (2% hike, 45-min standup, alt-tab reflex, cold dinner, "CC: main"), not vague "office life be like".
- Every panel must MOVE the bit forward — new beat of the joke or escalation. Cut any line that just restates the mood.
- Dialogue = natural spoken Hinglish, deadpan, with SUBTEXT. Sharp, specific, <= 10 words. Distinct voice: the oblivious manager vs the done-with-it employee.
- Panel 10 (caption) = the PUNCHLINE — short, quotable, screenshot-worthy — that names the pain ("Meeting na hone par... ek aur meeting") OR lands the karma reveal. Do NOT fully resolve karma stories (leave a Part-2 hook).
- Validate the employee's pain; NEVER punch down at juniors/interns. The butt of the joke is the system / the clueless boss.

NUMBERS: write every amount/quantity/time as DIGITS — "2% hike" not "do percent", "5 minute", "9 baje". Use "Rs" for money; NEVER the ₹ symbol (the font cannot render it).

FORMAT:
- EXACTLY 10 panels. Mostly "speech" + 1-2 "thought". Panel 10 MUST be "caption".
- FLASHBACK/timestamp beats (e.g. "9 baje — standup, 45 min") can be a "caption" or a "thought" panel.
- 1-2 recurring characters; each gets an ULTRA-detailed FIXED look (age, face, skin, hair, exact office clothes+colours, one distinctive feature — e.g. ID lanyard, spectacles) — locks them across panels.
- "speaker" = [x,y] (0..1) head position of whoever speaks/thinks that panel.
- "prompt" = office SCENE (varied shots — cubicle wide, meeting-room, close-up on a laptop/clock) + action & micro-emotion + setting. SIMPLE hand poses.

BANNED (feels 2021, not 2026): "Monday be like ☕😵" with no bit; "but first, coffee"; "boss makes $$ employee makes 💀" stamp with no story; preachy hustle-culture morals; tearjerker "employee cries in washroom" (we want funny, not sad); generic "that one colleague" with no specific fresh detail.

POLICY: no vulgarity, no caste/religion slur, no real company/person named. Fiction.
Deliver a bit you would screenshot and send to your own work group."""

EDITOR = """You are a RUTHLESS comedy editor AND a burnt-out working professional scrolling Reels.
Below is a draft ANHONI corporate-relatable story (JSON). Judge it with brutal honesty:
- Would you actually watch to the end and TAG a colleague, or scroll in 2 seconds?
- Is the hook an instantly recognisable office moment? Is the panel-10 PUNCHLINE sharp and quotable, or flat/predictable?
- Are the details SPECIFIC (2% hike, 45-min standup, alt-tab) or generic "office life be like"?
- Any filler panel, any preachy line, any tearjerker/horror tone that doesn't belong? Does it punch down at juniors (bad) instead of the system/clueless boss (good)?

Then REWRITE the entire story into something that genuinely lands — keep what works, ruthlessly replace what doesn't. Obey every rule and the EXACT same JSON schema.
CRITICAL: keep the SAME lane/setting as the draft — if it is a corporate/office story, it MUST stay corporate/office (do NOT convert it into a family/papa story). Improve it within its own world.
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
