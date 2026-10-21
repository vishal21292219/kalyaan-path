"""One-off renderer for the "Aakhri Mulaqat" romantic-suspense reel.

Feeds a HAND-WRITTEN script (built from the WhatsApp story) through the existing
pipeline modules — image_gen (fal FLUX + character consistency), tts (ElevenLabs
Aakash thriller voice), assembler (Ken-Burns + Devanagari captions + suspense
music + SFX). No LLM topic generation; no publishing. Output → output/videos/.

Run from repo root:  python render_aakhri.py
"""
from __future__ import annotations

from pathlib import Path

from pipeline.utils import set_active_niche, out_path
from pipeline.image_gen import generate_images
from pipeline.tts import synthesize
from pipeline.assembler import assemble

set_active_niche("aakhri")
SLUG = "aakhri_mulaqat"

# ── Character bible (locked look → same faces across scenes) ──────────────
CHARACTER_BIBLE = [
    {
        "name": "Aarav",
        "aliases": ["आरव", "aarav"],
        "look": "a 27-year-old Indian man, lean angular face, short black hair, "
                "light stubble, sad tired eyes with faint dark circles, wearing a "
                "dark charcoal hoodie",
    },
    {
        "name": "Riya",
        "aliases": ["रिया", "riya"],
        "look": "a 25-year-old Indian woman, soft oval face, fair-wheatish skin, "
                "long wavy black hair loose over her shoulders, gentle wistful "
                "eyes, wearing a deep-red kurti, a small thin silver ring on her "
                "finger",
    },
]

# ── Narration (Hindi, Devanagari) — one calm suspense breath per line ──────
SCRIPT = {
    "kind": "story",
    "narrator_gender": "male",
    "title": "Mari hui premika ka message: 'Aaj raat 1 baje station aa jana' 😱 Aakhri Mulaqat",
    "hook": "रात के ठीक बारह बजे आरव के फोन पर एक मैसेज आया।",
    "body": [
        "अगर तुम मुझसे सच में प्यार करते हो, तो आज रात एक बजे पुराने रेलवे स्टेशन पर आ जाना... अकेले।",
        "मैसेज पढ़ते ही आरव के हाथ कांपने लगे।",
        "क्योंकि ये मैसेज रिया ने भेजा था, और रिया को मरे हुए पूरे छह महीने हो चुके थे।",
        "छह महीने पहले आरव और रिया एक-दूसरे से बेइंतहा प्यार करते थे।",
        "हर शाम दोनों उसी झील के किनारे मिलते थे।",
        "रिया अक्सर कहती, अगर कभी मैं तुमसे दूर चली जाऊं, तो मेरा इंतजार मत करना।",
        "और आरव हंसकर कहता, तुम मुझसे दूर जा ही नहीं सकती।",
        "लेकिन एक बरसात की रात रिया का एक्सीडेंट हो गया।",
        "उस रात के बाद आरव की ज़िंदगी जैसे रुक गई। रिया की आखिरी निशानी थी एक छोटी सी चांदी की अंगूठी।",
        "आज वही अंगूठी उसकी जेब में थी, जब वो ठीक एक बजे उस सुनसान स्टेशन पर पहुंचा।",
        "प्लेटफॉर्म बिल्कुल खाली था, बस एक पुरानी बेंच पर कोई बैठा दिख रहा था।",
        "आरव पास गया, तो वहां कोई नहीं था, सिर्फ उसी की चांदी की अंगूठी बेंच पर रखी चमक रही थी।",
        "और उसके पीछे धूल पर लिखा था, इस बार इंतज़ार मैंने किया।",
    ],
    "cta": "क्या रिया सच में लौट आई थी? कमेंट में बताओ, और ऐसी ही रूह कंपा देने वाली कहानियों के लिए फॉलो करो।",
}

# ── Scene prompts (content only; config style_suffix is auto-appended) ─────
# Roughly aligned to the narration; the assembler time-syncs them to the voice.
SCRIPT["visuals"] = [
    # 1 — hook (hero)
    "Aarav sitting up in a dark bedroom at midnight, a bright phone screen glowing "
    "on his shocked pale face, cold blue light, rumpled bed behind him, tense.",
    # 2 — the message
    "Extreme close-up of a smartphone screen at 12:00 AM showing a single chat "
    "message bubble, an eerie glow, Aarav's trembling hand holding the phone.",
    # 3 — dread
    "Extreme close-up of Aarav's terrified wide eyes reflecting the phone light, "
    "a bead of cold sweat, deep shadows.",
    # 4 — flashback love
    "Warm golden-hour flashback: Aarav and Riya sitting close together on the "
    "grassy edge of a calm lake, smiling, deeply in love, soft bokeh.",
    # 5 — Riya by the lake
    "Riya by the lake at dusk, gentle wistful expression, looking lovingly toward "
    "the camera, wind in her hair, dreamy soft light.",
    # 6 — tender moment
    "Aarav laughing warmly and holding Riya's hand by the lake at sunset, a tender "
    "intimate romantic moment, golden light.",
    # 7 — the accident aftermath (no gore, no body)
    "A tragic rainy night on a slick deserted road, blurred red car tail-lights "
    "receding into heavy rain and fog, a fallen deep-red dupatta and a small silver "
    "ring lying on the wet glistening asphalt under a cold streetlight, shattered "
    "glass reflections, deeply somber and heartbreaking, cinematic, no gore.",
    # 8 — Aarav's grief (broken, hollow)
    "Aarav sitting alone on the floor of a dark empty room, back against the wall, "
    "knees up, unshaven and hollow-eyed with a single tear, staring at a tiny "
    "silver ring held between his fingers, dim cold light from a window, crushing "
    "grief and emptiness, emotional cinematic portrait.",
    # 9 — the ring
    "Macro close-up of a small thin silver ring resting in a man's open palm, soft "
    "melancholic light, shallow focus.",
    # 10 — the station
    "A lonely old deserted Indian railway station platform at 1 AM, thick fog, a "
    "single flickering yellow lamp, empty rusted tracks, cinematic and eerie.",
    # 11 — approaching the figure
    "Aarav walking down the empty misty platform toward an old wooden bench where a "
    "faint blurred figure seems to sit, cold moonlight, deeply tense and eerie.",
    # 12 — cliffhanger (dramatic climax)
    "An old deserted railway-platform wooden bench in cold moonlight and drifting "
    "fog at night. On the bench a small silver ring glints in sharp focus with "
    "faint scratch-marks traced in the dust behind it. In the deep hazy background "
    "stands the barely-visible translucent ghostly silhouette of a young woman in a "
    "deep-red kurti, sorrowful and eerie, partly dissolving into the mist. Dramatic "
    "shafts of cold pale moonlight cutting through the fog, volumetric haze, a "
    "deeply emotional and chilling climax, powerful cinematic composition.",
]

def main() -> None:
    img_dir = out_path("images", SLUG)
    voice_path = out_path("audio", f"{SLUG}.mp3")
    video_path = out_path("videos", f"{SLUG}.mp4")

    print(f"== Rendering '{SCRIPT['title']}' ==")

    words_path = voice_path.with_suffix(".words.json")
    if voice_path.exists() and words_path.exists():
        print("[1/3] voiceover — reusing existing (narration unchanged)")
    else:
        print("[1/3] voiceover (ElevenLabs Aakash / thriller)…")
        synthesize(SCRIPT, voice_path)

    print("[2/3] images (fal FLUX + character consistency)…")
    images = generate_images(
        SCRIPT["visuals"], img_dir, character_bible=CHARACTER_BIBLE
    )
    print(f"      {len(images)} scenes generated")

    print("[3/3] assemble (Ken-Burns + captions + suspense music + SFX)…")
    assemble(SCRIPT, voice_path, images, video_path,
             skip_music=False, skip_captions=False)

    print(f"\nFINAL → {video_path}")


if __name__ == "__main__":
    main()
