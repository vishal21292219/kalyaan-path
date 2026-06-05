"""LLM → structured reel script: hook, body, CTA, visual prompts, metadata."""
from __future__ import annotations

import json
import os
import re

from dotenv import load_dotenv

from .utils import dedupe_script_narration, load_config

# override=True so .env always wins over shell-exported empty strings
# (some shells export ANTHROPIC_API_KEY="" which silently blocks loading).
load_dotenv(override=True)


SCHEMA_BLOCK = """Output JSON ONLY (no markdown fences). Schema:

{
  "title": "YouTube-Shorts viral title, <=70 chars (Hinglish or Roman). MUST be a STOP-SCROLL hook — curiosity gap, dramatic claim, or specific number. Examples: 'Karna ka woh raaz jo Mahabharat ne chupaya 🔥', 'Hanuman aaj bhi zinda hain? 👁️ 5000 saal ka sach', 'Ravana ke 10 sir ka asli matlab 😱'. Add 1-2 power emojis (🔥 👁️ 😱 🔱 ⚔️ 📜).",
  "hook": "Opening line in the CHANNEL'S PRIMARY LANGUAGE (see the LANGUAGE INSTRUCTION below — Hindi channels=Devanagari, English channels=English), <=16 words. MUST start with a curiosity trigger or a bold reframe/shocking claim. Used for VOICEOVER + first 2 sec of captions.",
  "hook_roman": "Roman transliteration of the hook (for English channels, identical to hook)",
  "body": [
     "Voiceover line in the channel's primary language (Devanagari for Hindi, English for English channels)",
     "..."   // 10-14 SHORT lines, ~9-13 words each (target 60-85s spoken; NEVER over 100s — must stay a Short)
  ],
  "body_roman": [
     "Roman transliteration line for captions (for English channels, identical to body)",
     "..."   // EXACTLY same count as body[], 1:1 mapping per line
  ],
  "cta": "Closing line in the channel's primary language — MUST ask a specific engagement question AND mention the channel name to subscribe.",
  "cta_roman": "Roman transliteration of the cta",
  "visuals": [
     "vivid image prompt 1 (in English) — depicts EXACTLY what body[0] narrates",
     "..."  // EXACTLY same count as body[]. visuals[i] must depict the scene narrated in body[i] — same characters, same action, same moment. 1:1 narrative sync.
  ],
  "character_bible": [
     {
       "name": "Shiva",                       // the EXACT word/name you use for this character inside visuals[] prompts (used to detect which scene shows them)
       "aliases": ["Mahadev", "Shiv"],        // any other words you use for the same character in visuals[]
       "look": "a majestic blue-skinned ascetic god, matted jata hair piled with a crescent moon, third eye on forehead, snake around neck, rudraksha beads, tiger-skin around waist, calm powerful face with a neat beard, holding a trident"   // ONE locked head-to-toe appearance, repeated identically every scene
     }
     // ONLY the 1-4 RECURRING named characters/deities who appear in MULTIPLE scenes. Skip one-off crowds, landscapes, objects. [] if no recurring character.
  ],
  "description": "Long-form YouTube description (Hindi/Devanagari, 5-8 lines). Structure: 1) Hook in 1-2 lines (re-state the question/claim). 2) Tease the answer in 2-3 lines without fully revealing (curiosity gap). 3) Engagement question — 'comments mein bataiye'. 4) Subscribe CTA mentioning channel name. 5) 10-15 relevant hashtags at the end including #Shorts and #YouTubeShorts. NO English-only descriptions — use Devanagari for the body text and Roman for hashtags.",
  "hashtags": ["#tag1", "#tag2", ...]   // 10-15 relevant — mix English mythology tags + Hindi transliterated tags
}

Rules:
- LENGTH (CRITICAL): keep the WHOLE body SHORT. Narration runs slow (~1.4
  words/sec for dramatic Hindi), so control length by WORD COUNT, not by
  guessing seconds:
  * TOTAL words across ALL body[] lines = 90-120 words. HARD MAX = 140 words.
  * That lands the video around 65-90 seconds.
  WHY THIS IS NON-NEGOTIABLE: a YouTube Short is capped at 180 seconds. Go over
  and YouTube stops treating it as a Short — it loses ALL Shorts-feed reach
  (one 196s video on our channel got 2 views). 140 words keeps a safe margin.
  Data agrees: our best performer (Namah Shivaya 67s) and top competitor hits
  (Jal Mahal 86s = 9M, fridge 79s, ghati road 39s) are all SHORT. Shorter +
  tighter = higher retention = more reach.
- LANGUAGE: hook / body / cta MUST be in the channel's primary language
  (see "LANGUAGE INSTRUCTION" section below). For Hindi channels use
  Devanagari script. For English channels write directly in English (in
  this case the *_roman fields equal hook/body/cta — no transliteration
  needed, set them to the same English text).
- *_roman fields are used for on-screen captions. For Hindi channels they
  are the Roman transliteration. For English channels just repeat the
  English content. Keep each *_roman line SHORT (<60 chars).
- Visuals (image prompts): VERY important — write in English following the
  image style guidance below.
- VISUAL-SCRIPT SYNC (CRITICAL — biggest quality lever):
  * visuals[] count MUST equal body[] count exactly (1 image per spoken line).
  * For each i: visuals[i] depicts the scene narrated in body[i] —
    same characters present, same action happening, same moment of the story.
  * If body[i] says "Three sons did tapasya before Brahma", visuals[i]
    shows three sons in tapasya before Brahma — NOT cities, NOT war,
    NOT what comes later. Match the narrative beat exactly.
  * Each image gets ~7-12 seconds of screen time. If it shows the wrong
    moment, viewer feels disconnect and scrolls away.
  * Hook image (visuals[0]) MUST match the opening line (body[0]),
    not the climax. Climax visual goes at climax body line.
- CHARACTER CONSISTENCY (critical for a professional look):
  * Fill "character_bible" with the 1-4 RECURRING named characters/deities
    who appear across MULTIPLE scenes (e.g. Shiva, Krishna, Hanuman, a hero).
  * Each gets ONE locked head-to-toe "look" (skin, hair, crown, weapon,
    clothing, face). The pipeline generates a single master portrait from it
    and reuses that exact identity in every scene the character appears in.
  * In visuals[], refer to each recurring character by the SAME "name" word
    you put in the bible (and list any other words used as "aliases"), so the
    pipeline can tell which scenes show them. Describe their ACTION/pose/
    background in the scene — do NOT re-describe their fixed appearance.
  * Use [] for character_bible only when the video has no recurring character
    (pure landscape/mantra/abstract). Most mythology/bhakti videos DO have one.

VIRAL-HOOK CHECKLIST for title (most important field!):
- ✅ Curiosity gap (not full answer in title)
- ✅ Specific number or "the one thing" / "the real reason"
- ✅ Power word: रहस्य/secret/truth/शाप/अमर/forbidden/hidden
- ✅ 1-2 emojis MAX (overload looks spammy)
- ✅ Under 70 chars (mobile preview cutoff)
- ❌ Generic ("History of X", "Story of Y" — boring)
- ❌ Spoiler in title (kills click)

DESCRIPTION RULES:
- Write the FULL description, not a 2-line summary. 5-8 lines minimum.
- Use Devanagari for narrative, Roman for hashtags.
- Frame as MYSTERY for itihaas niche, DEVOTIONAL warmth for bhakti.
- End with 10-15 relevant hashtags packed at the bottom.
"""

DEFAULT_PERSONA = "You are a viral short-form scriptwriter for a Hindu devotional channel."
DEFAULT_IMAGE_GUIDE = "- Describe a clear simple scene, vertical 9:16, no text or watermarks."
DEFAULT_TOPIC_GUIDE = "- Avoid political content, modern figures, or controversial claims."


# ─────────────────────────────────────────────────────────────────────────
# VIRAL CREATOR PLAYBOOK — universal best-practices distilled from top
# Indian + global Shorts creators (8M+ subs). Injected into EVERY script
# prompt regardless of niche. These rules drive retention, completion,
# and re-shares — the three signals YT Shorts algorithm weights heaviest.
# ─────────────────────────────────────────────────────────────────────────
VIRAL_PLAYBOOK = """
TOP-CREATOR PLAYBOOK (MANDATORY — applies to every line you write):

1. THREE-SECOND RULE (most important):
   - First 3 sec of hook MUST stop the scroll. Use one of:
     a) Shocking claim ("Hanuman ji aaj bhi zinda hain")
     b) Mystery question ("Kya aap jaante hain ki Krishna ki mrityu kaise hui?")
     c) Specific number teaser ("3 cheezein jo Geeta me chupi hain")
     d) Authority dropping a bomb ("NASA ne maan liya...")
   - WINNING TEMPLATE (verified from this channel's own top videos —
     specific name + dramatic moment beat generic mystery every time):
     "[Specific naam] ne [specific action] kiya, aur [unexpected result] hua —
      yeh woh sach hai jo [school / itihaas / kisi] ne kabhi nahi bataya."
   - ❌ BANNED OPENER: a vague "ek rahasya hai..." / "aaj hum jaanenge..." start.
     Channel data: generic-rahasya openers got swiped (13–34 views); specific
     dramatic-moment openers won (370–550 views). Open ON the moment.
   - NEVER open with narrative setup, history dates, or generic praise.
   - The viewer's thumb is hovering — give them a reason NOT to swipe.

2. PATTERN INTERRUPT (in every body section):
   - Use the STATEMENT → COUNTER → REVELATION structure.
     Example: "Sab kehte hain Ravan asur tha." (statement)
              "Lekin sach kuch aur hai." (counter)
              "Ravan ne hi pehli baar Shiv Tandav stotra likha tha." (revelation)
   - Break expected statements every 15-20 sec. Viewer must think "WAIT, kya?!"

3. MINI-CLIFFHANGERS (every 10-15 sec):
   - Phrases that pull viewer forward:
     "Lekin asli sach yahan se shuru hota hai..."
     "Aage aap jaaneंge..."
     "Vigyaan aaj bhi iska jawab nahi de paya..."
     "Ek aur baat jo aapko hairan kar degi..."
   - End of every 2-3 lines should make viewer NEED to know what's next.

4. SPECIFIC > GENERIC:
   - "5000 saal pehle" > "ancient times"
   - "12 jyotirlingon mein se ek" > "a famous temple"
   - "Krishna 125 saal jeeye" > "Krishna lived long"
   - Numbers, names, places, dates EVERYWHERE. Specifics = credibility = retention.

5. SIMPLE VOCABULARY (grade 8 level):
   - Avoid Sanskrit jargon unless explaining it.
   - "Dharm" = "sahi kaam"; "moksh" = "mukti"; "karm" = "actions".
   - One simple word > one fancy word. Audience is on mobile, scrolling fast.

6. ACTIVE VOICE + "AAP" (personal):
   - "Aap ye sun ke chaunk jaayenge" > "Listeners may be surprised"
   - "Krishna ne kiya" > "Kiya gaya tha" (passive kills energy)
   - Speak TO the viewer, not ABOUT the topic.

7. BINARY ENGAGEMENT CTA:
   - Ask question with only 2 possible answers (more comments):
     "Aap kya maante hain — Krishna asli the ya kalpa?"
     "Comment me likhein: A ya B?"
   - NEVER ask open-ended "what do you think" — too much friction.

8. RETENTION HOOKS (the "loops"):
   - Open with a question OR claim, but DON'T answer it until 70% point.
   - "Aakhir mein bataenge ki ye kyun hua" → forces watch-to-end.

9. ANTI-AI-SLOP MARKERS:
   - Don't use "in this video" / "today we will explore" intros.
   - Don't use "the answer might surprise you" generic placeholder.
   - Don't list 5 things with no narrative arc — story > list.
   - Don't repeat the channel name more than 2x in the script.

10. EVERY LINE HAS A JOB:
    - Either ADVANCES the narrative, REVEALS a fact, or BUILDS curiosity.
    - If a line is just transition/filler — DELETE IT.
    - Tightness > length. 7 sharp lines > 12 average lines.
"""


def _build_system_prompt(cfg: dict, n_images: int, long_form: bool = False) -> str:
    llm = cfg.get("llm", {})
    persona = llm.get("persona", DEFAULT_PERSONA).strip()
    image_guide = llm.get("image_style_guidance", DEFAULT_IMAGE_GUIDE).strip()
    topic_guide = llm.get("topic_guidance", DEFAULT_TOPIC_GUIDE).strip()
    content_spec = (llm.get("content_spec") or "").strip()
    language = llm.get("language", "hindi").lower()
    schema = SCHEMA_BLOCK.replace("{n_images}", str(n_images))

    # Build explicit language instruction so LLM doesn't default to Hindi
    if language == "english":
        lang_block = (
            "LANGUAGE INSTRUCTION (STRICT):\n"
            "- Write hook / body / cta ENTIRELY IN ENGLISH (no Hindi, no Devanagari).\n"
            "- *_roman fields = same English text (no transliteration needed).\n"
            "- Title in English. Description in English. All hashtags in English.\n"
            "- Tone is global English mystery podcast (David Attenborough meets Bright Side)."
        )
    elif language == "hinglish":
        lang_block = (
            "LANGUAGE INSTRUCTION (STRICT):\n"
            "- Write hook / body / cta in HINGLISH (Hindi words in Roman script,\n"
            "  e.g., 'Kya aap jaante hain ki Krishna ne...').\n"
            "- *_roman fields = same Hinglish text.\n"
            "- NO Devanagari script. NO pure English sentences."
        )
    else:  # hindi (default)
        lang_block = (
            "LANGUAGE INSTRUCTION (STRICT):\n"
            "- Write hook / body / cta in PURE HINDI (Devanagari script) for TTS.\n"
            "- *_roman fields MUST be Roman transliteration of the same Devanagari\n"
            "  content (used for on-screen captions). Keep Sanskrit words recognizable\n"
            "  ('धर्म' → 'Dharma', 'कर्म' → 'Karma')."
        )

    spec_block = f"\n\nCONTENT SPEC (STRICT — follow exactly):\n{content_spec}" if content_spec else ""

    long_form_block = ""
    if long_form:
        long_form_block = """

LONG-FORM MODE (CRITICAL OVERRIDE — overrides the 45-55 sec rule above):

YOU ARE INDIA'S TOP ANCIENT HISTORY WRITER + PHILOSOPHER. Channel the
voice of a master storyteller — think Devdutt Pattanaik's depth + Bhuvan
Bam's accessibility + Amish Tripathi's narrative drama. Your single goal:
make this video GO VIRAL. Every line should make the viewer think
"मुझे ये जानना ही है" and KEEP WATCHING.

VIRAL CURIOSITY ENGINE (apply to EVERY body line):
- Open with a SHOCK question or unbelievable claim that has the viewer
  saying "wait, kya?!" within first 5 seconds.
- Every 60-90 seconds, drop a NEW mini-cliffhanger
  ("aage aap जानेंगे कि...", "lekin asli rahasya yahan se shuru hota hai...",
   "vigyaan aaj bhi iska jawab नहीं de paya...")
- Use the rhetorical pattern: STATEMENT → COUNTER-CLAIM → REVELATION
  ("इतिहasakaron ne kaha X. Lekin sach kuch aur hai. Vo sach ye hai...")
- Quote authority where natural: "Pliny the Elder ne likha", "NASA ne maana",
  "Oxford ke historian ne kaha", "Rigveda mein varnan hai..."
- End every major section with a HOOK INTO NEXT section
  ("लेकin ye to bas shuruwat thi...", "asli chaunkane wala sach abhi baaki hai")

STRUCTURE (~20-25 MINUTES, 50-80 body lines, each 10-15 words):

1. HOOK (lines 1-5, 0:00-1:00):
   - Open with the most shocking claim or impossible question
   - Promise the viewer something they'll never forget

2. SETUP (lines 6-15, 1:00-4:00):
   - Establish stakes: why this matters NOW
   - Context that hooks: "agar ye sach hai, to hamari poori history galat hai"

3. MAIN REVELATIONS (lines 16-60, 4:00-18:00):
   - 5-7 sub-sections, each ~6-10 body lines
   - Each section reveals ONE jaw-dropping fact
   - Build evidence layer by layer

4. CLIMACTIC INSIGHT (lines 61-72, 18:00-22:00):
   - The biggest "MIND BLOWN" moment
   - Connect all dots — the BIGGER truth

5. PHILOSOPHICAL CLOSE + CTA (lines 73-80, 22:00-23:00):
   - Reflection on what this means for us today
   - "Comment karein agar aapko bhi laga ki...", "Subscribe karein..."

TITLE FORMULA (CRITICAL for 600K+ views):
Pattern: "[Topic ka rahasya] | [shock question] | [bigger curiosity]"
Examples that have gone viral:
- "शिव का जन्म रहस्य ! क्या सच में महादेव का कोई जन्म हुआ था | ब्रह्मा और विष्णु की अद्भुत कथा"
- "Kailasa Temple का सच | ये मंदिर इंसानों ने नहीं बनाया? | NASA भी जिस मंदिर से हैरान है"
Use 3 hooks chained with " | " separator. Each hook escalates curiosity.

DESCRIPTION (1500-1800 chars, structured):
- Line 1-2: Bold opening question + emoji hook
- Para 1: Set the mystery (3-4 sentences)
- Para 2: Hint at the revelation without giving it
- "इस वीडियो में हम जानेंगे:" SECTION:
  * 🔹 Sub-topic 1
  * 🔹 Sub-topic 2
  ... 7-9 bullet points
- Subscribe + engagement CTA
- "📩 Business: gopulabs@gmail.com"
- 12-15 hashtags (mix of niche + viral)
- "Your Queries:" SEO block with 20+ long-tail keyword variations

VISUALS (30 prompts):
- Each prompt cinematic National Geographic documentary realism
- Period-accurate ancient settings
- Single dominant focal subject
- Dramatic atmospheric lighting (golden hour, stormy sky, glowing torches)
- Mix wide establishing shots + medium shots + close-ups
- Story-driven: each image advances the narrative

HASHTAGS: Always include #Itihaasvani #ItihaasKeRahasya #SanatanDharma
#BharatGatha + 8-10 topic-specific viral hashtags.

GOAL: This video MUST be the most shareable, replayable, finish-rate video
in our channel. Pretend your salary depends on retention curve being flat.
"""

    # TimeDecoders (ancient) only: LLM picks the narrator's gender from the
    # story's tone so tts.py can map it to the right voice (Brian / Ava).
    narrator_block = ""
    if cfg.get("niche", "") == "ancient":
        narrator_block = (
            "\n\nNARRATOR VOICE (REQUIRED — include in your JSON output):\n"
            '- Add a top-level field "narrator_gender": "male" OR "female".\n'
            "- Choose it from the STORY's tone/protagonist, NOT at random:\n"
            '  * "male"  -> warrior, war, battle, conquest, weapons, dark mystery,\n'
            "    conspiracy, lost/forbidden tech, serious or ominous, male central figure.\n"
            '  * "female" -> goddess, queen, a woman\'s legend, nature, emotional or\n'
            "    tragic tale, beauty/wonder, sacred or devotional.\n"
            '- If genuinely unsure, default to "male".'
        )

    return f"""{persona}

{schema}

{VIRAL_PLAYBOOK}

{lang_block}{long_form_block}{narrator_block}

IMAGE STYLE GUIDANCE:
{image_guide}

TOPIC GUIDANCE:
{topic_guide}{spec_block}
"""


def _lang_instruction(lang: str) -> str:
    return {
        "hindi": "Pure Hindi (Devanagari script in output)",
        "english": "English only",
        "hinglish": "Hinglish — Hindi spoken in Roman script, mixed naturally with English",
    }.get(lang, "Hinglish")


def _build_user_prompt(topic: dict, context: str, n_images: int, niche: str, long_form: bool = False) -> str:
    if topic.get("kind") == "shloka_episode":
        return f"""You are creating EPISODE {topic['episode_number']} of a Bhagavad Gita shloka series.

Sanskrit Verse (Bhagavad Gita {topic['ref']}):
{topic['verse']}

Core theme: {topic['theme']}

Structure the reel like this:
- title: "Bhagavad Gita Shloka #{topic['episode_number']} | <hook in Hindi>"
- hook: start with "Shloka number {topic['episode_number']}, Adhyaya {topic['ref']}" then a question/hook (Devanagari Hindi)
- body[0]: the Sanskrit verse itself (Devanagari) — 1 line, short
- body[1]: simple Hindi meaning of the verse (1-2 lines)
- body[2..]: explain the deeper meaning with a MODERN-LIFE example
  (career, relationships, social media, money, success, failure, stress).
  Use everyday situations a young Indian audience faces today.
- cta: tell them to follow for shloka #{topic['episode_number'] + 1} tomorrow + comment "Jai Shri Krishna"
- visuals: {n_images} scenes. EVERY scene must keep a spiritual/devotional
  aesthetic — never look like a stock corporate photo. Suggested arc:
    1. Krishna on a golden chariot speaking to Arjuna, Kurukshetra at sunrise
       (Raja Ravi Varma style)
    2. Closeup of Krishna's serene face, peacock crown, divine glow
    3. A SYMBOLIC scene that maps the moral to today (NOT generic office or
       laptop). Example: lamp burning steadily in a temple at dawn, hands
       offering grain to a deity, a farmer ploughing fields under sunrise,
       a student silently bowing before a Krishna idol, a runner on a misty
       road at sunrise. Always include something hinting at devotion —
       diya, tilak, temple, idol, river, mountain, dawn light.
    4. Krishna in cosmic Vishvarupa form OR Krishna calmly playing flute
    5. Another symbolic-modern scene with devotional element
    6. A devotee meditating before a Krishna shrine, soft lamp light
    7. Final: Krishna and Arjuna, divine sunrise, blessing pose
  All vertical 9:16, single figure (anatomically correct), warm golden
  cinematic light, painting-quality not photographic.
- description + hashtags as usual

Return ONLY the JSON object."""
    if long_form:
        return f"""Topic: {topic['title']}
Niche: {niche}
Format: LONG-FORM DOCUMENTARY (20-25 min, NOT a Short)

Reference facts (from Wikipedia, distill the essentials):
\"\"\"
{context}
\"\"\"

CRITICAL: Generate a 20-25 minute documentary-style script.
- body: 50-80 short narration lines (one breath each, ~10-15 words)
- Structure: hook → setup → 5-7 major revelations → climax → CTA
- description: long-form style, include "इस वीडियो में हम जानेंगे:" with 7-9 sub-topics
- title: 3-hook chained format like "[Topic] रहस्य | [question] | [sub-curiosity]"
- visuals: {n_images} prompts (one per ~45 sec of narration), cinematic mythology art
- hashtags: 12-15 mix

Return ONLY the JSON object."""
    hook_block = ""
    if topic.get("hook") and topic.get("kind") in ("viral", "mantra"):
        hook_block = (
            f"\nVIRAL ANGLE (build the whole video around THIS specific hook — it is the "
            f"reason this topic is trending, do NOT drift to a generic overview):\n"
            f"  → {topic['hook']}\n"
            f"Open body[0] on this exact dramatic point.\n"
        )

    series_block = ""
    if topic.get("kind") == "series":
        ep = topic.get("episode_number", 1)
        tot = topic.get("episode_total", 1)
        sname = topic.get("series_name", "")
        tail = topic.get("english_tail", "")
        angle = topic.get("angle", "")
        series_block = f"""
THIS IS A SERIES EPISODE (return-viewer engine — CRITICAL):
- Series: "{sname}" — episode focus: {topic['title']}. Angle: {angle}
- TITLE format (Hinglish): start with "{sname} #{ep}:" then the dramatic hook,
  then 😱, then "{tail}", then "#facts".
  Example: "{sname} #{ep}: <dramatic Hinglish hook>! 😱 {tail} #facts"
- The episode number ({ep}) appears ONLY in the title text. NEVER speak it in the
  narration — do NOT say "episode {ep}", "part {ep}", "{ep} waala", or "is series ka
  part". The voiceover must not contain any episode number at all.
- HOOK / body[0]: open DIRECTLY on this episode's most dramatic, suspenseful
  moment — no recap, no "is series me", no numbering.
- Do NOT mention, name, or tease the NEXT episode (or any other episode's topic)
  anywhere — the schedule may reorder, so naming an upcoming topic would be wrong.
- CTA: generic return-driver ONLY, e.g. "aise aur rahasya ke liye subscribe karo"
  + ask a comment. NO episode numbers, NO "agla episode ... aa raha hai".
- Keep the SAME visual style across the series so episodes feel connected.

⚡ TIGHT + STICKY OVERRIDE (this OVERRIDES the 2:30-3:00 / 15-22 line targets
above — a tight reel keeps retention; a long slow one gets swiped):
- TOTAL spoken duration MUST be 45-65 seconds. body = 9-13 SHORT lines only.
- LINE 0 (the hook) is everything — it must land in the FIRST 1 SECOND:
  a concrete SHOCKING claim/number on the actual subject, mid-action. NO
  question setup, NO "kya aap jaante hain", NO "ek rahasya". Drop the bomb.
  Good: "Is mandir ke shikhar pe 52-ton ka magnet tha — jahaaz tak kheench leta tha."
- Pace: every single line reveals something NEW and escalates. No setup lines,
  no recap, no filler. If a line doesn't shock or advance — delete it.
- Build SUSPENSE: hold the biggest reveal for the 70-80% mark; plant a
  mini-cliffhanger ("...par asli sach aage hai") every 2-3 lines.
- Short punchy sentences (≤12 words). Mobile viewer, thumb hovering.
"""
    # TimeDecoders: rotate the OPENING STYLE per topic so videos stop feeling
    # like the same template (user feedback: "saari stories ek jaisi lagti hain").
    variety_block = ""
    if niche == "ancient" and not long_form:
        import hashlib as _hl
        _styles = [
            "IN MEDIA RES — open mid-scene at the most dramatic second, no setup ('The torch went out. Then they saw it.').",
            "SHOCKING NUMBER — lead with one hard stat that breaks the brain ('11,000 years old. Built before the wheel, before writing.').",
            "DIRECT CHALLENGE — attack the viewer's assumption ('Everything you were taught about this is a lie.').",
            "AUTHORITY BLINDSIDED — experts who couldn't explain it ('They scanned beneath it. What came back made no sense.').",
            "EERIE QUESTION — one unsettling question, no answer yet ('What if an entire city vanished in a single night?').",
            "SENSORY COLD-OPEN — drop them into the place ('Pitch black, 200 feet down, a door sealed for 1,500 years.').",
            "REVERSE REVEAL — state the bizarre result first, explain how second ('This 2,000-year-old metal still hasn't rusted. Nobody can copy it.').",
        ]
        _i = int(_hl.md5(str(topic.get("title", "")).encode()).hexdigest(), 16) % len(_styles)
        variety_block = (
            f"\nOPENING STYLE for THIS video (MANDATORY — vary structure so no two "
            f"reels feel templated): {_styles[_i]}\n"
            "Vary the fact-reveal order and sentence rhythm vs a typical video too.\n"
        )

    return f"""Topic: {topic['title']}
Kind: {topic.get('kind', 'general')}
Tags: {', '.join(topic.get('tags', []))}
Niche: {niche}
{hook_block}{series_block}{variety_block}
Reference facts (from Wikipedia, may be long — distill the essentials):
\"\"\"
{context}
\"\"\"

Generate {n_images} visual prompts. Return ONLY the JSON object."""


def _gemini(system: str, user: str, model: str) -> str:
    import google.generativeai as genai
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set in .env")
    genai.configure(api_key=api_key)
    m = genai.GenerativeModel(model, system_instruction=system)
    resp = m.generate_content(user, generation_config={"temperature": 0.85})
    return resp.text


def _claude(system: str, user: str, model: str) -> str:
    import anthropic
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in .env")
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(
        model=model or "claude-sonnet-4-6",
        max_tokens=4096,
        temperature=0.85,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return resp.content[0].text


def _groq(system: str, user: str, model: str) -> str:
    import requests
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set in .env")
    r = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model or "llama-3.3-70b-versatile",
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.85,
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _loads_lenient(candidate: str) -> dict:
    """Parse JSON, repairing the malformed output LLMs commonly emit.

    Two stages: (1) regex pre-clean for known offenders, then (2) a TARGETED
    loop that reads the JSONDecodeError position and patches exactly there —
    e.g. inserts the missing comma for "Expecting ',' delimiter" (the #1 LLM
    error) or strips a trailing comma. Far more reliable than blanket regex.
    """
    s = candidate
    # Stage 1 — blanket regex fixes.
    s = re.sub(r'([}\]"\d])(\s*\n\s*)(["{\[])', r'\1,\2\3', s)   # missing comma at line breaks
    s = re.sub(r",(\s*[}\]])", r"\1", s)                          # trailing comma before }/]
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", s)           # stray control chars

    # Stage 2 — targeted, position-aware repair loop.
    for _ in range(80):
        try:
            return json.loads(s)
        except json.JSONDecodeError as e:
            pos, msg = e.pos, e.msg
            if "Expecting ',' delimiter" in msg and 0 < pos <= len(s):
                s = s[:pos] + "," + s[pos:]                       # insert the missing comma
                continue
            if "Expecting property name" in msg or "Expecting value" in msg:
                # usually a trailing/duplicate comma just before pos → drop it
                j = pos - 1
                while j >= 0 and s[j] in " \n\r\t":
                    j -= 1
                if j >= 0 and s[j] == ",":
                    s = s[:j] + s[j + 1:]
                    continue
            raise
    return json.loads(s)  # exhausted → raise the final error


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in LLM output: {text[:200]}")
    candidate = text[start : end + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return _loads_lenient(candidate)  # if still bad, raises → caller retries


def write_script(topic: dict, context: str, long_form: bool = False,
                 prefer_free: bool = False) -> dict:
    cfg = load_config()
    if long_form:
        # Long-form videos use ~30 scenes (vs 10 for Shorts) and 50-80 body
        # lines (vs 5-9). Each scene plays ~30-45 sec.
        n_images = 30
    else:
        # Shorts mode: visuals = 1 per body line for tight script-image sync.
        # Body is now 10-14 lines (target 60-85s, must stay under the 180s Shorts
        # cap). Post-process truncates visuals to the real body count.
        n_images = cfg["images"].get("num_per_reel", 13)
    niche = cfg.get("niche", "bhakti")

    system = _build_system_prompt(cfg, n_images, long_form=long_form)
    user = _build_user_prompt(topic, context, n_images, niche, long_form=long_form)

    provider = cfg["llm"]["provider"]
    model = cfg["llm"]["model"]

    def _try_chain():
        """Provider chain: claude → gemini → groq. Fall through on failure.

        prefer_free=True skips Claude entirely and starts at Gemini → Groq.
        Used by the nightly pregen draft so it never touches the paid stack.
        """
        errs = []
        if not prefer_free and (provider == "claude" or os.getenv("ANTHROPIC_API_KEY")):
            try:
                claude_model = model if provider == "claude" else "claude-sonnet-4-6"
                return _claude(system, user, claude_model)
            except Exception as e:
                errs.append(f"claude: {type(e).__name__}: {e}")
                print(f"[script_writer] Claude failed ({errs[-1]}) — falling back")
        if provider == "gemini" or os.getenv("GEMINI_API_KEY"):
            try:
                gemini_model = model if provider == "gemini" else "gemini-flash-latest"
                return _gemini(system, user, gemini_model)
            except Exception as e:
                errs.append(f"gemini: {type(e).__name__}: {e}")
                print(f"[script_writer] Gemini failed ({errs[-1]}) — falling back")
        if os.getenv("GROQ_API_KEY"):
            try:
                groq_model = model if provider == "groq" else "llama-3.3-70b-versatile"
                return _groq(system, user, groq_model)
            except Exception as e:
                errs.append(f"groq: {type(e).__name__}: {e}")
        raise RuntimeError(f"All LLM providers failed: {' | '.join(errs)}")

    # Generate + parse, retrying the whole LLM call if the JSON won't parse
    # (malformed JSON is a flaky one-off — a fresh generation almost always fixes
    # it, far more reliable than failing the entire run).
    script = None
    last_err = None
    last_raw = ""
    for attempt in range(3):
        try:
            raw = _try_chain()
            last_raw = raw or last_raw
            script = _extract_json(raw)
            break
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
            print(f"[script_writer] JSON parse failed (attempt {attempt + 1}/3): {e} — regenerating")
    if script is None and last_raw:
        # Final fallback: ask the LLM to repair its own broken JSON. Catches
        # structural errors (unescaped quotes/newlines in Hindi strings) that
        # regex/position fixes can't. Prevents a whole run failing on bad JSON.
        try:
            print("[script_writer] all 3 regenerations failed — asking LLM to repair the JSON")
            fix_raw = _try_chain_repair(
                "You are a JSON repair tool. Output ONLY valid minified JSON — no prose, no "
                "markdown fences. Fix syntax errors (missing/trailing commas, unescaped quotes "
                "or newlines inside string values) but PRESERVE every key, value and all text "
                "exactly as given.",
                "Repair this into valid JSON:\n\n" + last_raw[:14000],
                provider, model,
            )
            script = _extract_json(fix_raw)
            print("[script_writer] ✓ LLM JSON repair succeeded")
        except Exception as e:
            last_err = e
    if script is None:
        raise RuntimeError(f"Script JSON unparseable after 3 attempts + repair: {last_err}")

    # Enforce 1:1 visual-body sync for Shorts (biggest quality lever).
    # If LLM returned mismatched counts, pad or truncate visuals to match body.
    if not long_form:
        body = script.get("body") or []
        visuals = script.get("visuals") or []
        if len(visuals) != len(body) and body:
            print(f"[script_writer] visual-body count mismatch: {len(visuals)} visuals vs {len(body)} body lines — repairing 1:1")
            if len(visuals) < len(body):
                # Pad by re-asking LLM for the missing scene-specific prompts
                missing = body[len(visuals):]
                repair_user = (
                    "The following Hindi narration lines need matching visual prompts "
                    "(English image-gen prompts, vertical 9:16 cinematic, each tightly "
                    "depicting that exact line's scene/characters/action):\n\n"
                    + "\n".join(f"{i+1}. {line}" for i, line in enumerate(missing))
                    + "\n\nReturn JSON only: {\"visuals\": [\"prompt1\", \"prompt2\", ...]} "
                    "with EXACTLY one prompt per numbered line above."
                )
                try:
                    repair_raw = _try_chain_repair(
                        "You generate image prompts that depict specific narration moments. "
                        "Return JSON only.", repair_user, provider, model)
                    repair_json = _extract_json(repair_raw)
                    extra = repair_json.get("visuals") or []
                    visuals = visuals + extra[:len(missing)]
                    print(f"[script_writer] repaired: now {len(visuals)} visuals")
                except Exception as e:
                    print(f"[script_writer] repair call failed ({e}) — padding by repeating last visual")
                    last = visuals[-1] if visuals else "Cinematic 9:16 vertical frame: " + (body[0] if body else "Indian mythology scene")
                    visuals = visuals + [last] * (len(body) - len(visuals))
            # Truncate excess
            visuals = visuals[:len(body)]
            script["visuals"] = visuals

        # HARD SAFETY NET: a Short MUST stay under 180s or it loses Shorts reach.
        # Dramatic narration ≈ 1.4 words/sec, so cap total body words at ~170
        # (≈120s, safe margin). The cta is a separate field, so trimming trailing
        # body lines never drops the closing call-to-action. Rarely triggers
        # (the prompt already targets 90-120 words) — pure backstop.
        MAX_WORDS = 170
        body = script.get("body") or []

        def _wc(lines):
            return sum(len(str(l).split()) for l in lines)

        if _wc(body) > MAX_WORDS:
            kept = []
            for line in body:
                if kept and _wc(kept) + len(str(line).split()) > MAX_WORDS:
                    break
                kept.append(line)
            n = max(3, len(kept))
            if n < len(body):
                print(f"[script_writer] body {_wc(body)}w > {MAX_WORDS}w → trimmed {len(body)}→{n} lines (keep Short <180s)")
                script["body"] = body[:n]
                if script.get("body_roman"):
                    script["body_roman"] = script["body_roman"][:n]
                if script.get("visuals"):
                    script["visuals"] = script["visuals"][:n]

    # Drop a body[0] (and its 1:1 body_roman/visuals) that merely restates the
    # hook — otherwise the opening sentence is spoken/captioned twice. Runs after
    # the visual-sync repair so counts stay aligned.
    dedupe_script_narration(script)
    return script


def _try_chain_repair(system: str, user: str, provider: str, model: str) -> str:
    """Small helper for the post-process repair call. Same provider chain as main."""
    if provider == "claude" or os.getenv("ANTHROPIC_API_KEY"):
        try:
            return _claude(system, user, model if provider == "claude" else "claude-sonnet-4-6")
        except Exception:
            pass
    if provider == "gemini" or os.getenv("GEMINI_API_KEY"):
        try:
            return _gemini(system, user, model if provider == "gemini" else "gemini-flash-latest")
        except Exception:
            pass
    if os.getenv("GROQ_API_KEY"):
        return _groq(system, user, "llama-3.3-70b-versatile")
    raise RuntimeError("No LLM provider available for visual repair")


if __name__ == "__main__":
    from .topic_generator import pick_topic
    from .scraper import gather_context
    t = pick_topic()
    ctx = gather_context(t)
    print(json.dumps(write_script(t, ctx), indent=2, ensure_ascii=False))
