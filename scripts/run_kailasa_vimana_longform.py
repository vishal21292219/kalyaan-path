"""One-off long-form runner: Kailasa Temple + Vimana (Itihaasvani).

Pre-loads context from 3 Wikipedia sources (Kailasa Temple Ellora,
Vaimanika Shastra, Vimana) so the LLM has rich grounding for a
20-25 min documentary script.

Run from project root:
    .venv/bin/python scripts/run_kailasa_vimana_longform.py
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.utils import out_path, set_active_niche, slugify, today_stamp  # noqa: E402
from pipeline.scraper import wiki_summary  # noqa: E402
from pipeline.script_writer import write_script  # noqa: E402
from pipeline.tts import synthesize  # noqa: E402
from pipeline.image_gen import generate_images, _generate_gemini, GeminiUnavailable  # noqa: E402
from pipeline.assembler import assemble  # noqa: E402


VIRAL_TITLE = (
    "Kailasa Temple aur Vimana Rahasya | 1200 Saal Ka Asambhav Sach | "
    "Kya Hamare Purvajon Ke Paas Lupt Vigyan Tha?"
)

WIKI_SOURCES = [
    "Kailasa_temple,_Ellora",
    "Vaimanika_Shastra",
    "Vimana",
    "Ellora_Caves",
    "Rashtrakuta_dynasty",
]


def build_rich_context() -> str:
    """Stitch summaries from multiple wikis. Cached after first run."""
    parts: list[str] = []
    for slug in WIKI_SOURCES:
        s = wiki_summary(slug)
        if s and s.get("extract"):
            parts.append(f"=== {s.get('title', slug)} ===\n{s['extract']}")
            print(f"[ctx] {slug}: {len(s['extract'])} chars")
        else:
            print(f"[ctx] {slug}: MISS")
    # Add curated angle hints (factual + viral) — fed to the LLM as context, not as script.
    parts.append(
        "=== KEY VIRAL ANGLES (use these as evidence pillars) ===\n"
        "1. Kailasa Temple (Cave 16, Ellora): carved top-down from a single basalt "
        "monolith ~756-773 CE under Rashtrakuta king Krishna I. ~200,000 tons of "
        "rock excavated. The removed rock has never been fully accounted for in the "
        "surrounding terrain.\n"
        "2. Modern engineer M.K. Dhavalikar estimated the structure would take a "
        "century-plus with current tools. The traditional ~18-year construction "
        "window is mathematically improbable: ~60 tons of stone removed PER DAY.\n"
        "3. Subtractive (not additive) construction. One mis-strike = no recovery. "
        "Three storeys, life-size elephants, full Ramayan/Mahabharat friezes — all "
        "tarashed into one rock.\n"
        "4. Vimana references in primary texts: Pushpaka Vimana (Ramayan — "
        "Valmiki), Saubha (Mahabharata — Salwa attacks Dwarka), Rigveda 1.164.47 "
        "imagery of a sky-craft using water-vapour propulsion, Yajurveda 'ratha' "
        "without horses or wheels.\n"
        "5. Vaimanika Shastra (Pandit Subbaraya Shastry, channelled 1918-1923, "
        "claimed to be from Maharshi Bharadwaj's lost 'Yantra Sarvasva'): "
        "describes Shakuna, Rukma, Sundara, Tripura Vimanas. 31 components — "
        "mirrors, gyroscopes, energy tubes, cloaking (invisibility) tech, "
        "para-shabda-grahaka (radar-like).\n"
        "6. 1974 IISc Bangalore study (Mukunda et al.) reviewed Vaimanika Shastra "
        "and found the described craft aerodynamically non-viable — BUT this "
        "applies only to the 1918 transcription; it does NOT debunk the primary "
        "Vedic/Itihaasa references.\n"
        "7. Connection theory (clearly framed as theory, not fact): if ancient "
        "Bharat possessed sonic / focused-energy rock-shaping tools described in "
        "Sanskrit tantra (e.g., 'stambhana yantra'), it could explain both the "
        "Kailasa excavation speed AND the missing 200,000 tons of debris.\n"
        "8. Editorial honesty: present mainstream view + alternative angles as "
        "OPEN QUESTIONS. Never assert fringe theories as proven fact. Let the "
        "viewer decide — this drives comments and shares.\n"
        "9. Ellora context: 34 rock-cut caves (Hindu, Buddhist, Jain) carved "
        "5th-10th century CE. UNESCO World Heritage 1983. Kailasa is Cave 16 — "
        "the architectural climax.\n"
    )
    return "\n\n".join(parts)[:6000]  # bigger window for long-form


def main() -> int:
    set_active_niche("itihaas")
    print("== Itihaasvani LONG-FORM run: Kailasa + Vimana ==")

    # 1. Build topic
    topic = {
        "kind": "custom",
        "title": VIRAL_TITLE,
        "wiki": None,
        "tags": [
            "kailasa", "ellora", "vimana", "vaimanika shastra", "ancient india",
            "lost technology", "mythology", "rahasya", "itihaas",
        ],
    }
    print(f"[topic] {topic['title']}")

    # 2. Rich, multi-source context
    context = build_rich_context()
    print(f"[ctx] total: {len(context)} chars")

    stamp = today_stamp()
    slug = slugify("kailasa-vimana-rahasya-longform")
    base = f"{stamp}_{slug}"

    # 3. Script (RESUMABLE — reuse existing JSON if present)
    script_path = out_path("scripts", f"{base}.json")
    if script_path.exists():
        script = json.loads(script_path.read_text())
        print(f"[script] reused cached → {script_path}")
    else:
        script = write_script(topic, context, long_form=True)
        for key in ("kind", "tags"):
            if key in topic and key not in script:
                script[key] = topic[key]
        script_path.write_text(json.dumps(script, indent=2, ensure_ascii=False))
        print(f"[script] saved → {script_path}")
    print(f"[script] title : {script.get('title')}")
    print(f"[script] body  : {len(script.get('body', []))} lines")
    print(f"[script] visual: {len(script.get('visuals', []))} prompts")

    # 4. TTS (RESUMABLE — reuse cached MP3 if present)
    voice_path = out_path("audio", f"{base}.mp3")
    if voice_path.exists() and voice_path.stat().st_size > 100_000:
        print(f"[tts] reused cached → {voice_path}")
    else:
        synthesize(script, voice_path)
        print(f"[tts] saved → {voice_path}")

    # 5. Images (RESUMABLE — skip any img_NN.jpg already on disk)
    img_dir = out_path("images", base)
    img_dir.mkdir(parents=True, exist_ok=True)
    from pipeline.utils import load_config
    cfg = load_config()
    style = cfg["images"]["style_suffix"]
    negative = cfg["images"]["negative"]
    model = cfg["images"].get("model", "gemini-3.1-flash-image-preview")
    images: list[Path] = []
    for i, raw_prompt in enumerate(script["visuals"]):
        path = img_dir / f"img_{i:02d}.jpg"
        if path.exists() and path.stat().st_size > 1024:
            print(f"[images] {i:02d} cached → skip")
            images.append(path)
            continue
        prompt = f"{raw_prompt}{style}. Avoid: {negative}"
        try:
            if _generate_gemini(prompt, path, model):
                images.append(path)
                print(f"[images] {i:02d} generated")
        except GeminiUnavailable as e:
            print(f"[images] {i:02d} FAILED ({e}) — continuing")
    print(f"[images] total {len(images)} / requested {len(script['visuals'])}")

    # 6. Assemble (keep music — uses trending_track.mp3 fallback)
    video_path = out_path("videos", f"{base}.mp4")
    assemble(script, voice_path, images, video_path, skip_music=True)
    print(f"[video] FINAL → {video_path}")

    # 7. Thumbnail
    thumb_path = None
    try:
        from pipeline.thumbnail_gen import make_thumbnail
        thumb_path = out_path("thumbnails", f"{base}.jpg")
        make_thumbnail(script, "itihaas", thumb_path)
        print(f"[thumb] → {thumb_path}")
    except Exception:
        traceback.print_exc()
        print("[thumb] generation failed — continuing")

    # 8. Endcard
    if thumb_path and Path(thumb_path).exists():
        try:
            from pipeline.endcard import append_thumbnail_endcard
            append_thumbnail_endcard(video_path, thumb_path, duration_sec=2.5)
            print("[endcard] appended")
        except Exception:
            traceback.print_exc()

    print("\n========================================")
    print(f" DONE: {video_path}")
    print(f" THUMB: {thumb_path}")
    print(f" SCRIPT: {script_path}")
    print("========================================")
    return 0


if __name__ == "__main__":
    sys.exit(main())
