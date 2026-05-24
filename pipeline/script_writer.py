"""LLM → structured reel script: hook, body, CTA, visual prompts, metadata."""
from __future__ import annotations

import json
import os
import re

from dotenv import load_dotenv

from .utils import load_config

load_dotenv()


SCHEMA_BLOCK = """Output JSON ONLY (no markdown fences). Schema:

{
  "title": "YouTube-Shorts viral title, <=70 chars (Hinglish or Roman). MUST be a STOP-SCROLL hook — curiosity gap, dramatic claim, or specific number. Examples: 'Karna ka woh raaz jo Mahabharat ne chupaya 🔥', 'Hanuman aaj bhi zinda hain? 👁️ 5000 saal ka sach', 'Ravana ke 10 sir ka asli matlab 😱'. Add 1-2 power emojis (🔥 👁️ 😱 🔱 ⚔️ 📜).",
  "hook": "Devanagari Hindi opening line, <=16 words. MUST start with curiosity trigger like 'क्या आप जानते हैं', 'इतिहास का वो रहस्य', 'पुराणों में लिखा है कि', or a SHOCKING claim. Used for VOICEOVER + first 2 sec of captions.",
  "hook_roman": "Roman transliteration of the hook line",
  "body": [
     "Devanagari Hindi line for voiceover",
     "..."   // 5-9 lines, each one breath, ~6-12 words
  ],
  "body_roman": [
     "Roman transliteration line for captions",
     "..."   // EXACTLY same count as body[], 1:1 mapping per line
  ],
  "cta": "Devanagari Hindi closing line — MUST ask a specific question for engagement (e.g. 'आप क्या मानते हैं — कमेंट में बताएं') AND mention the channel name to subscribe.",
  "cta_roman": "Roman transliteration of the cta",
  "visuals": [
     "vivid image prompt 1 (in English)",
     "..."  // exactly {n_images} prompts
  ],
  "description": "Long-form YouTube description (Hindi/Devanagari, 5-8 lines). Structure: 1) Hook in 1-2 lines (re-state the question/claim). 2) Tease the answer in 2-3 lines without fully revealing (curiosity gap). 3) Engagement question — 'comments mein bataiye'. 4) Subscribe CTA mentioning channel name. 5) 10-15 relevant hashtags at the end including #Shorts and #YouTubeShorts. NO English-only descriptions — use Devanagari for the body text and Roman for hashtags.",
  "hashtags": ["#tag1", "#tag2", ...]   // 10-15 relevant — mix English mythology tags + Hindi transliterated tags
}

Rules:
- Total spoken duration ~45-55 seconds when read calmly.
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

    return f"""{persona}

{schema}

{lang_block}{long_form_block}

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
    return f"""Topic: {topic['title']}
Kind: {topic.get('kind', 'general')}
Tags: {', '.join(topic.get('tags', []))}
Niche: {niche}

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


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in LLM output: {text[:200]}")
    return json.loads(text[start : end + 1])


def write_script(topic: dict, context: str, long_form: bool = False) -> dict:
    cfg = load_config()
    if long_form:
        # Long-form videos use ~30 scenes (vs 10 for Shorts) and 50-80 body
        # lines (vs 5-9). Each scene plays ~30-45 sec.
        n_images = 30
    else:
        n_images = cfg["images"]["num_per_reel"]
    niche = cfg.get("niche", "bhakti")

    system = _build_system_prompt(cfg, n_images, long_form=long_form)
    user = _build_user_prompt(topic, context, n_images, niche, long_form=long_form)

    provider = cfg["llm"]["provider"]
    model = cfg["llm"]["model"]
    if provider == "gemini":
        raw = _gemini(system, user, model)
    elif provider == "groq":
        raw = _groq(system, user, model)
    else:
        raise ValueError(f"Unknown provider: {provider}")

    return _extract_json(raw)


if __name__ == "__main__":
    from .topic_generator import pick_topic
    from .scraper import gather_context
    t = pick_topic()
    ctx = gather_context(t)
    print(json.dumps(write_script(t, ctx), indent=2, ensure_ascii=False))
