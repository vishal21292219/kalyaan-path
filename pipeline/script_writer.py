"""LLM → structured reel script: hook, body, CTA, visual prompts, metadata."""
from __future__ import annotations

import json
import os
import re

from dotenv import load_dotenv

from .utils import load_config

load_dotenv()


SYSTEM_PROMPT = """You are a viral short-form scriptwriter for a Hindu devotional channel.
Output JSON ONLY (no markdown fences). Schema:

{
  "title": "YouTube-Shorts-style title, <=70 chars, hook-y (in English/Roman script)",
  "hook": "Devanagari Hindi line, <=18 words — used for VOICEOVER",
  "hook_roman": "Roman transliteration of the hook line — used for CAPTIONS",
  "body": [
     "Devanagari Hindi line for voiceover",
     "..."   // 5-9 lines, each one breath, ~6-12 words
  ],
  "body_roman": [
     "Roman transliteration line for captions",
     "..."   // EXACTLY same count as body[], 1:1 mapping per line
  ],
  "cta": "Devanagari Hindi closing line",
  "cta_roman": "Roman transliteration of the cta",
  "visuals": [
     "vivid image prompt 1 (in English)",
     "..."  // exactly {n_images} prompts
  ],
  "description": "YouTube description, English, 2-3 sentences, end with hashtags",
  "hashtags": ["#tag1", "#tag2", ...]   // 8-12 relevant
}

Rules:
- Total spoken duration ~45-55 seconds when read calmly.
- hook / body / cta MUST be in Devanagari Hindi (so TTS pronounces correctly).
- *_roman fields MUST be the SAME content transliterated to Roman/English script
  (so captions render cleanly in a Latin font). Keep proper Sanskrit words
  recognizable, e.g. "धर्म" → "Dharma", "कर्म" → "Karma".
- Captions = the *_roman fields. Keep each *_roman line SHORT (<60 chars)
  so it fits 2 caption lines max on screen.
- Tone: reverent, warm, never satirical or doctrinal/divisive.
- Visuals (image prompts): VERY important — write in English with these
  rules to avoid AI-art distortion of deities:
    * Always specify "single figure, full body, centered, anatomically
      correct, two arms" (unless the deity canonically has more, then specify
      exact count: "four arms holding lotus, conch, mace, chakra").
    * Describe a clear, simple scene — one subject, clean background.
    * Mention art style: "traditional Indian devotional painting, Raja Ravi
      Varma style" or "cinematic concept art, soft volumetric light".
    * Specify lighting + mood: "golden hour sunrise", "soft divine glow".
    * NO text, watermarks, or words in image.
- Avoid political content, modern figures, or controversial claims.
"""


def _lang_instruction(lang: str) -> str:
    return {
        "hindi": "Pure Hindi (Devanagari script in output)",
        "english": "English only",
        "hinglish": "Hinglish — Hindi spoken in Roman script, mixed naturally with English",
    }.get(lang, "Hinglish")


def _build_user_prompt(topic: dict, context: str, n_images: int) -> str:
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
    return f"""Topic: {topic['title']}
Kind: {topic.get('kind', 'general')}
Tags: {', '.join(topic.get('tags', []))}

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


def write_script(topic: dict, context: str) -> dict:
    cfg = load_config()
    n_images = cfg["images"]["num_per_reel"]
    lang = cfg["llm"]["language"]

    system = SYSTEM_PROMPT.replace("{n_images}", str(n_images)).replace(
        "{lang_instruction}", _lang_instruction(lang)
    )
    user = _build_user_prompt(topic, context, n_images)

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
