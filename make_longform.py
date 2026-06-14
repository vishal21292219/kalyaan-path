"""TimeDecoders long-form builder — '7 Ancient Discoveries Science STILL Can't Explain'.

Reuses the existing pipeline (ancient niche = TimeDecoders): ElevenLabs voice,
fal images (1920x1080), Ken Burns + optional Kling hero clips, word-synced
captions, subtle cinematic bed. Run locally (free except fal/ElevenLabs spend).

  python make_longform.py --segment kailasa     # build ONE segment as a sample
  python make_longform.py --full                # build the whole 11-min video
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

from pipeline.utils import set_active_niche
set_active_niche("ancient")  # TimeDecoders config (ElevenLabs male voice + fal + music bed)

from pipeline.tts import synthesize
import pipeline.image_gen as _img
from pipeline.image_gen import generate_images
from pipeline.assembler import assemble

# ── QUALITY OVERRIDE ─────────────────────────────────────────────────────
# schnell (fast/cheap) produced anatomy defects (2-trunk elephant, deformed
# animal). Force flux-pro/v1.1 + hard anatomy negatives for this long-form,
# WITHOUT touching the live channel config. Monkeypatch the config that
# image_gen reads.
import copy as _copy
from pipeline.utils import load_config as _base_load_config

_ANATOMY_NEG = (", two trunks, extra trunk, duplicate trunk, multiple trunks, "
                "extra limbs, extra legs, extra arms, fused limbs, malformed animal, "
                "deformed creature, deformed statue, disfigured, mutated, melting, "
                "broken anatomy, distorted proportions, conjoined, duplicated body parts")

# PHOTOREAL style — the live config's "cinematic teal-orange + volumetric fog +
# glowing torches" made shots look like CGI/concept-art, not real. Swap for a
# true documentary-photo look.
_PHOTOREAL_STYLE = (
    ", a realistic documentary photograph of a real ancient site, shot on a "
    "full-frame DSLR camera with a 35mm lens, natural realistic daylight, "
    "true-to-life natural colors, photojournalistic, ultra-sharp realistic "
    "stone and rock textures, real-world fine detail, subtle film grain, candid "
    "real-world composition, looks like an actual travel and archaeology "
    "expedition photo, NOT concept art, NOT a painting, NOT CGI, NOT a render, "
    "no teal-and-orange color grade, no heavy fog, no fantasy lighting, no "
    "glowing torches everywhere, realistic, no text, no watermark, no modern objects"
)

def _hq_load_config(niche=None):
    cfg = _copy.deepcopy(_base_load_config(niche))
    cfg["images"]["model"] = "fal-ai/flux-pro/v1.1"      # premium model
    cfg["images"]["provider"] = "fal"
    cfg["images"]["style_suffix"] = _PHOTOREAL_STYLE       # photoreal, not CGI
    cfg["images"]["negative"] = (cfg["images"].get("negative", "") + _ANATOMY_NEG
        + ", concept art, painting, illustration, cgi, 3d render, video game, "
          "fantasy art, oversaturated, heavy color grading, plastic look")
    return cfg

_img.load_config = _hq_load_config  # image_gen now generates at flux-pro quality

OUT = ROOT / "output" / "longform" / "td_7_ancient"
(OUT / "assets").mkdir(parents=True, exist_ok=True)

# ── SAMPLE SEGMENT: #1 Kailasa Temple (~75s) ─────────────────────────────
# Each body line = one visual beat; visual_prompts[i] matches lines[i]
# (index 0 = hook). Prompts are written to be RELEVANT to the narration.
KAILASA = {
    "kind": "viral",
    "narrator_gender": "male",
    "title": "7 Ancient Discoveries Science STILL Can't Explain",
    "hook": "And the one discovery that shouldn't be possible at all.",
    "body": [
        "Deep in the cliffs of Ellora, India, stands the Kailasa Temple. And it isn't built. It's carved.",
        "The sculptors didn't stack a single stone. They started at the top of a solid mountain, and cut downward.",
        "By hand, they removed an estimated four hundred thousand tons of solid rock.",
        "What they revealed was a complete, multi-story temple. Courtyards, pillars, staircases, and bridges.",
        "All of it carved from one single, continuous piece of stone.",
        "There is no mortar here, because there are no blocks. Nothing was ever assembled.",
        "And that's the terrifying part. With carving, there is no undo. One wrong strike, and the entire monument is ruined forever.",
        "Modern engineers estimate a project like this should take centuries. Yet it was finished in the reign of a single king.",
        "How they did it, with the precision of a machine and the scale of a mountain, we still cannot fully explain.",
    ],
    "cta": "",
}
KAILASA_VIS = [
    "a colossal ancient rock-cut Hindu temple with an ornate carved pillared facade emerging from a sheer dark stone cliff, soft golden dawn light, sweeping cinematic establishing shot, immense scale, architectural focus, no animals, no creatures",
    "the Kailasa rock-cut temple complex carved into a dark basalt cliff at Ellora, ornate stone shikhara towers and pillars, wide cinematic establishing shot, warm sunlight and long shadows, architecture only",
    "looking straight down from the top edge of a solid rocky mountain into a deep narrow man-made carved channel in the rock, vertiginous scale, dramatic light",
    "a vast freshly excavated vertical rock face beside a half-carved ancient temple, scattered stone rubble, hazy atmospheric morning light, architecture and stone only",
    "an ornate multi-story rock-cut temple courtyard with rows of tall intricately carved stone pillars, balconies and staircases, warm sun shafts, no animals, no statues of animals",
    "extreme close-up of intricate weathered Hindu carvings and floral motifs on a single continuous rock wall, fine stone detail, raking light",
    "seamless monolithic rock-cut temple architecture showing smooth carved surfaces with no joints and no separate blocks, architectural detail shot, warm light",
    "a single ancient iron chisel striking grey rock with bright orange sparks, tense cinematic macro shot, dust particles, dramatic teal and orange light",
    "an epic aerial shot slowly descending into a grand rock-cut temple courtyard at golden sunset, ornate pillars and shrines and staircases revealed, dust haze, immense scale, architecture only",
]


def build_segment(name: str, script: dict, vis: list[str], hero_idx: list[int] | None = None,
                  pad_to_lines: bool = True):
    seg = OUT / name
    (seg).mkdir(parents=True, exist_ok=True)
    print(f"\n=== Building segment '{name}' ===")

    # 1. voiceover (ElevenLabs male)
    voice = seg / f"{name}.mp3"
    synthesize(script, voice)
    print(f"[voice] {voice}")

    # 2. images (1920x1080 long-form).
    prompts = vis[:]
    if pad_to_lines:
        n_lines = len([l for l in [script["hook"], *script["body"], script["cta"]] if l])
        while len(prompts) < n_lines:
            prompts.append(vis[-1])
        prompts = prompts[:n_lines]
    imgs = generate_images(prompts, seg / "img", long_form=True)
    print(f"[images] {len(imgs)} generated")

    # 3. optional Kling hero clips (image-to-video) on key beats
    hero_clips = {}
    if hero_idx:
        from pipeline.kling_video import generate_hero_clip
        for i in hero_idx:
            if i < len(imgs):
                hp = seg / f"hero_{i}.mp4"
                ok = generate_hero_clip(
                    prompt="slow cinematic camera move, gentle parallax, subtle drifting dust and light, photoreal",
                    ref_image=imgs[i], out_path=hp, duration=6)
                if ok:
                    hero_clips[i] = hp
                    print(f"[hero] scene {i} -> {hp}")
    # 4. assemble long-form
    out_mp4 = seg / f"{name}.mp4"
    assemble(script, voice, imgs, out_mp4, long_form=True, hero_clips=hero_clips or None)
    print(f"\n✅ DONE: {out_mp4}")
    return out_mp4


# ── FULL VIDEO: 7 discoveries + cold open + outro (~11 min) ──────────────
FULL = {
    "kind": "viral",
    "narrator_gender": "male",
    "title": "7 Ancient Discoveries Science STILL Can't Explain",
    "hook": "Somewhere in India, there's a temple that weighs forty thousand tons. And it was carved from a single rock, from the top down.",
    "body": [
        "No blueprint. No modern tools. And to this day, no engineer can fully explain how. That's number one. But first, seven discoveries that break the timeline of human history. The last three shouldn't exist.",
        # #7 Göbekli Tepe
        "Number seven. In 1994, a shepherd in southern Turkey kicked a stone, and uncovered the oldest temple on Earth.",
        "Göbekli Tepe is eleven and a half thousand years old. Older than Stonehenge by six thousand years. Older than the wheel. Older than writing. Older than farming itself.",
        "Massive T-shaped pillars, twenty tons each, carved with foxes, scorpions, and vultures.",
        "But here's the problem. To move twenty-ton stones, you need an organized society. And there was no society yet.",
        "This temple came first. And civilization came after.",
        "Science still can't explain why they built it. Or why, two thousand years later, they deliberately buried the whole thing.",
        # #6 Antikythera
        "Number six. In 1901, divers off a Greek island pulled a lump of corroded bronze from a two-thousand-year-old shipwreck.",
        "For decades, nobody understood it. Then X-rays revealed the impossible.",
        "Thirty interlocking gears, machined to a precision we would not see again for fourteen hundred years.",
        "It predicted eclipses. It tracked the planets. It followed the Olympic cycle. An analog computer, built before the birth of Christ.",
        "Where did this technology come from? And why did it vanish, with nothing like it for over a thousand years?",
        # #5 Iron Pillar
        "Number five. In Delhi stands a seven-meter iron pillar, forged sixteen hundred years ago.",
        "By every law of chemistry, it should be a pile of rust. Iron, plus India's monsoon humidity, equals corrosion.",
        "But it has barely rusted in sixteen centuries.",
        "Modern metallurgists finally cracked part of the secret. A thin protective film, formed over time.",
        "But here's what they can't explain. How ancient blacksmiths, with no chemistry and no instruments, made metal purer and more corrosion-resistant than much of what we make today.",
        # #4 Puma Punku
        "Number four. Nearly thirteen thousand feet up in the Andes lie the ruins of Puma Punku. And they look machined.",
        "Identical H-shaped blocks, interchangeable, like factory parts.",
        "Cuts so straight, and corners so perfect, they appear laser-made. Drill holes spaced evenly to the millimeter.",
        "And all of it in diorite. A stone so hard, you need diamond to cut it.",
        "The builders left no written language. No metal tools. Not even the wheel.",
        "So how do you mass-produce machine-grade stonework, with stone-age technology?",
        # #3 Baghdad Battery
        "Number three. A small clay jar, two thousand years old. Inside, a copper cylinder and an iron rod.",
        "Fill it with vinegar, or grape juice, and it generates an electric current.",
        "A battery. Built eighteen hundred years before Alessandro Volta supposedly invented it.",
        "What was ancient Mesopotamia doing with electricity? Electroplating gold? Something inside a temple?",
        "Science has working replicas. But zero explanation for why it exists at all.",
        # #2 Sacsayhuamán
        "Number two. Above the city of Cusco, in Peru, stand walls made of boulders weighing up to a hundred and twenty tons.",
        "They are fitted together so tightly, you cannot slide a sheet of paper between them.",
        "No mortar. No straight edges. Every stone a unique, irregular shape, locked into its neighbors like a three-dimensional puzzle.",
        "And they have stood, earthquake-proof, for five hundred years, while colonial buildings around them collapsed.",
        "How did the Inca cut, move, and fit hundred-ton boulders with this precision, using no iron and no wheel?",
        # #1 Kailasa
        "And number one. The one that shouldn't be possible at all.",
        "The Kailasa Temple, at Ellora, India, isn't built. It's carved.",
        "The sculptors started at the top of a solid mountain, and cut downward. By hand, they removed an estimated four hundred thousand tons of rock.",
        "What they revealed was a complete, multi-story temple. Courtyards, pillars, staircases, and bridges. All from one single, continuous piece of stone.",
        "There is no mortar, because there are no blocks. Nothing was ever assembled.",
        "And that's the terrifying part. With carving, there is no undo. One wrong strike, and the entire monument is ruined forever.",
        "Engineers estimate a project like this should take centuries. Yet it was finished in the reign of a single king.",
        "How they did it, with the precision of a machine and the scale of a mountain, we still cannot fully explain.",
        # Outro
        "Seven discoveries. One pattern. Again and again, the ancient world was far more advanced than we give it credit for.",
    ],
    "cta": "Which one breaks your brain the most? Tell me in the comments. And if you want the truth your history class skipped, subscribe to TimeDecoders. The next one might be the strangest yet.",
}

FULL_VIS = [
    # cold open (0-1)
    "an aerial photograph of the Kailasa Temple at Ellora India, a giant temple carved out of a rock mountain, golden hour",
    "a dramatic wide photograph of a colossal ancient rock-cut temple set into a mountainside, warm light, real travel photo",
    # Göbekli Tepe (2-9)
    "a photograph of the Gobekli Tepe archaeological site in southern Turkey, ancient T-shaped stone pillars on a barren hilltop, daylight",
    "a rocky barren hillside in rural southern Turkey with an archaeological excavation, overcast daylight",
    "close-up photograph of a massive ancient T-shaped limestone megalith pillar with faint carved animal reliefs, weathered, natural light",
    "wide photograph of circular arrangements of huge prehistoric stone pillars at an excavation site, daylight",
    "a weathered carved stone relief of a fox and a scorpion on an ancient limestone pillar, close-up, natural light",
    "prehistoric people in animal skins hauling a massive stone pillar with ropes at dawn, realistic documentary scene",
    "a vast prehistoric stone temple site partly buried in earth, aerial photograph, soft golden light",
    "an excavation trench revealing ancient buried megalithic stone pillars, archaeologists working, daylight",
    # Antikythera (10-17)
    "an old sepia photograph of Greek sponge divers on a small wooden boat near a rocky island, early 1900s",
    "a corroded greenish lump of ancient bronze with embedded gear teeth, on a plain museum table, close-up, soft light",
    "macro photograph of the Antikythera mechanism, ancient bronze gear wheels green with patina, museum lighting",
    "a greyscale x-ray scan revealing interlocking cog wheels inside an ancient bronze device",
    "a modern reconstructed brass model of the Antikythera mechanism with gears and dials on display, soft light",
    "ancient Greek scholars studying a small bronze geared device by oil-lamp light, realistic historical scene",
    "a clear night sky full of stars with the moon and planets, an old astronomical chart, realistic",
    "an ancient shipwreck on the seafloor with clay amphorae and bronze fragments, underwater photograph",
    # Iron Pillar (18-25)
    "a photograph of the Iron Pillar of Delhi standing in a stone courtyard at the Qutb complex India, daylight",
    "close-up of the dark weathered surface of an ancient iron pillar with a smooth rust-free patina, natural light",
    "rain droplets beading and rolling off the surface of a polished ancient dark iron column, macro, overcast light",
    "an ancient Indian blacksmith's forge with glowing red-hot iron and hammers, realistic historical scene",
    "a metallurgist in gloves examining the surface of an old iron pillar with an instrument, daylight",
    "tourists standing beside a tall ancient dark iron pillar in an Indian heritage courtyard, daylight, scale",
    "extreme macro of a thin dark protective oxide film on an aged iron metal surface",
    "ancient Brahmi script inscription carved into the side of an old iron pillar, close-up, natural light",
    # Puma Punku (26-33)
    "a photograph of the Puma Punku ruins in Bolivia, scattered precision-cut grey stone blocks on a high Andean plateau, daylight",
    "close-up of a precisely cut H-shaped ancient grey stone block with razor-straight edges, Puma Punku, natural light",
    "rows of identical machine-like cut grey stone blocks lying on barren high-altitude ground, overcast daylight",
    "macro photograph of perfectly straight drilled holes evenly spaced in hard grey diorite stone",
    "a windswept high-altitude Andean plateau scattered with ancient megalithic stone ruins, dramatic clouds, daylight",
    "close-up of razor-sharp perfect right-angle corners cut into hard dark stone, ancient, natural light",
    "an archaeologist measuring the precise edge of an ancient cut stone block with a tool, daylight",
    "a wide aerial photograph of the Tiwanaku and Puma Punku archaeological complex in Bolivia, daylight",
    # Baghdad Battery (34-41)
    "a photograph of the ancient Baghdad Battery, a small terracotta clay jar with a copper cylinder, on a museum stand, soft light",
    "close-up of an ancient clay jar containing a corroded copper tube and an iron rod, museum lighting",
    "a clean cut-away cross-section diagram of the Baghdad Battery showing copper cylinder, iron rod and liquid, realistic",
    "vinegar being poured into an ancient clay jar in a lab demonstration on a bench, daylight",
    "a faint blue glow and a tiny electric spark from a replica ancient clay-jar battery, dark background, realistic",
    "an ancient Mesopotamian workshop with clay vessels, copper sheets and metal tools, realistic historical scene",
    "a craftsman carefully electroplating a small gold ornament in an ancient workshop, realistic",
    "rows of small ancient artifacts in a dim museum display case, photograph",
    # Sacsayhuamán (42-49)
    "a photograph of the Sacsayhuaman stone walls above Cusco Peru, giant interlocking grey boulders, daylight",
    "close-up of enormous irregular Inca stone blocks fitted perfectly together without mortar, natural light",
    "a hand trying to slide a sheet of paper into the tight joint between two massive Inca stones, close-up",
    "a wide photograph of the zigzag megalithic walls of Sacsayhuaman with green hills behind, daylight",
    "a single hundred-ton irregular polygonal stone block in an ancient Inca wall, low angle, natural light",
    "ancient Andean workers moving an enormous stone boulder with ropes and wooden logs, realistic historical scene",
    "an earthquake-cracked colonial stone building standing beside intact ancient Inca stonework, daylight",
    "tourists dwarfed beside the giant ancient stone walls of Sacsayhuaman Peru, daylight, scale",
    # Kailasa (50-57)
    "an aerial photograph of the Kailasa Temple at Ellora India carved from a single rock, ornate tower, daylight",
    "looking down into a deep man-made channel carved into a rock mountain beside an ancient Indian temple, daylight",
    "the multi-story rock-cut courtyard of Kailasa Temple Ellora with carved stone pillars and balconies, daylight",
    "close-up of intricate weathered Hindu carvings on the rock wall of an ancient Indian temple, natural light",
    "a seamless monolithic rock-cut temple wall with no joints and no blocks, ancient Indian architecture, daylight",
    "an ancient iron chisel and hammer resting on freshly carved grey rock with stone dust, close-up, natural light",
    "an ancient Indian king and court overseeing temple stonework, realistic historical scene, daylight",
    "a wide aerial photograph of the entire Kailasa rock-cut temple complex from above at golden hour, India",
    # outro (58-59)
    "a wide photograph of ancient megalithic stone ruins under a dramatic sky, daylight, awe-inspiring",
    "an aerial photograph of a vast ancient temple complex at golden sunset, real travel photo, awe-inspiring",
]

# Kling motion only on SAFE wide architectural/landscape shots (no close figures/animals)
FULL_HERO = [0, 30, 45, 57]

# Human-figure prompts produced defects (a monster, deformed people). Replace those
# indices with safe NO-PEOPLE object/architecture shots (flux nails these).
SAFE_FIXES = {
    7:  "a massive ancient T-shaped carved stone pillar lying on the ground beside thick fiber ropes and wooden log rollers, no people, dawn light",
    15: "a small ancient bronze geared device resting on a wooden table beside rolled parchment scrolls and an oil lamp, no people, candlelight",
    21: "an ancient blacksmith forge with glowing red-hot iron on an anvil and iron hammers and tongs, no people, dim workshop",
    22: "a magnifying lens and brass measuring instruments resting against the dark surface of an old iron pillar, no people, daylight",
    23: "a tall ancient dark iron pillar standing alone in an Indian heritage stone courtyard, low angle for scale, daylight",
    25: "extreme close-up of the weathered dark riveted metal surface of an ancient iron pillar, no text, natural light",
    32: "a precision metal caliper resting on the razor-straight cut edge of an ancient grey stone block, no people, daylight",
    37: "an ancient clay jar beside a glass beaker of pale liquid on a wooden lab bench, no people, daylight",
    39: "an ancient Mesopotamian workbench with clay vessels, thin copper sheets and bronze tools, no people, soft daylight",
    40: "a small gold ornament resting in a shallow copper bowl of liquid with faint bubbles, ancient workshop table, no people, close-up",
    44: "a thin sheet of white paper wedged at the hairline joint between two massive interlocking Inca stone blocks, extreme close-up, no people",
    47: "an enormous grey stone boulder resting on wooden log rollers with thick fiber ropes on a mountain path, no people, daylight",
    49: "the giant interlocking stone walls of Sacsayhuaman towering above an empty grassy plaza, low angle for scale, daylight",
    56: "an ancient Indian rock-cut temple mid-construction with wooden scaffolding, stone rubble and chisels lying around, no people, daylight",
}


def fix_full():
    """Regenerate ONLY the defective (human-figure) images + reuse the existing
    voice & hero clips, then re-assemble with the fixed caption code."""
    import shutil
    seg = OUT / "td_7_ancient_full"
    voice = seg / "td_7_ancient_full.mp3"
    if not voice.exists():
        raise SystemExit("voice not found — run --full first")
    idxs = sorted(SAFE_FIXES)
    print(f"[fix] regenerating {len(idxs)} defective images: {idxs}")
    tmp = generate_images([SAFE_FIXES[i] for i in idxs], seg / "img_fix", long_form=True)
    for k, i in enumerate(idxs):
        shutil.copy(tmp[k], seg / "img" / f"img_{i:02d}.jpg")
        print(f"[fix] img_{i:02d}.jpg replaced")
    imgs = sorted((seg / "img").glob("img_*.jpg"))
    hero_clips = {i: seg / f"hero_{i}.mp4" for i in FULL_HERO if (seg / f"hero_{i}.mp4").exists()}
    print(f"[fix] assembling {len(imgs)} images + {len(hero_clips)} reused hero clips")
    assemble(FULL, voice, imgs, seg / "td_7_ancient_full.mp4",
             long_form=True, hero_clips=hero_clips or None)
    print(f"\n✅ FIXED: {seg / 'td_7_ancient_full.mp4'}")


# Real Pexels footage (copyright-free) for relevant scenes → breaks the all-AI-stone
# monotony + adds reality. scene_index → search query (avoids Kling hero indices).
FOOTAGE_MAP = {
    3:  "ancient ruins",          6:  "ancient stone carving",
    9:  "archaeology excavation", 12: "gears clockwork mechanism",
    16: "starry night sky",       17: "underwater ocean deep",
    20: "rain water drops slow",  21: "blacksmith forge fire",
    26: "ancient stone ruins",    31: "mountain landscape clouds",
    34: "ancient clay pottery",   43: "ancient stone wall ruins",
    50: "ancient temple india",   53: "temple stone carving",
    58: "ancient ruins sunset",
}


def fetch_pexels_landscape(query, out, target_h=1080):
    import requests
    from pipeline.stock_footage import _is_modern, _download
    key = os.getenv("PEXELS_API_KEY")
    if not key:
        print("[footage] no PEXELS_API_KEY"); return None
    try:
        r = requests.get("https://api.pexels.com/videos/search",
            headers={"Authorization": key},
            params={"query": query, "orientation": "landscape", "size": "medium",
                    "per_page": 15, "page": 1}, timeout=30)
        if r.status_code != 200:
            print(f"[footage] '{query}' HTTP {r.status_code}"); return None
        vids = r.json().get("videos", []) or []
        vids = [v for v in vids if not _is_modern(v)] or vids
        for v in vids:
            files = [f for f in v.get("video_files", [])
                     if f.get("file_type") == "video/mp4"
                     and (f.get("width") or 0) >= (f.get("height") or 0)]
            if not files:
                continue
            files.sort(key=lambda f: abs((f.get("height") or 0) - target_h))
            link = files[0].get("link")
            if link and _download(link, out):
                print(f"[footage] '{query}' → {out.name}")
                return out
    except Exception as e:
        print(f"[footage] '{query}' error: {e}")
    return None


def rebuild_with_footage():
    """Reuse existing voice + images + Kling clips (all FREE), add real Pexels
    footage at relevant scenes, re-assemble with always-on synced captions. No
    fal / ElevenLabs spend."""
    seg = OUT / "td_7_ancient_full"
    voice = seg / "td_7_ancient_full.mp3"
    imgs = sorted((seg / "img").glob("img_*.jpg"))
    if not voice.exists() or len(imgs) < 60:
        raise SystemExit("need existing voice + 60 images (run --full then --fix first)")
    hero_clips = {i: seg / f"hero_{i}.mp4" for i in FULL_HERO if (seg / f"hero_{i}.mp4").exists()}
    fdir = seg / "footage"; fdir.mkdir(exist_ok=True)
    got = 0
    for idx, q in FOOTAGE_MAP.items():
        out = fdir / f"pex_{idx:02d}.mp4"
        if out.exists() or fetch_pexels_landscape(q, out):
            hero_clips[idx] = out; got += 1
    print(f"[footage] {got} Pexels clips + {len([i for i in FULL_HERO if (seg/f'hero_{i}.mp4').exists()])} Kling = {len(hero_clips)} real-motion scenes of 60")
    assemble(FULL, voice, imgs, seg / "td_7_ancient_full.mp4",
             long_form=True, hero_clips=hero_clips or None)
    print(f"\n✅ REBUILT with real footage + synced captions: {seg/'td_7_ancient_full.mp4'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--segment", default="kailasa")
    ap.add_argument("--footage", action="store_true", help="add Pexels footage + reassemble (FREE)")
    ap.add_argument("--full", action="store_true", help="build the whole 11-min video")
    ap.add_argument("--fix", action="store_true", help="regen defective images + reuse voice/heroes + reassemble")
    ap.add_argument("--no-hero", action="store_true", help="skip Kling hero clips")
    args = ap.parse_args()
    if args.footage:
        rebuild_with_footage()
    elif args.fix:
        fix_full()
    elif args.full:
        build_segment("td_7_ancient_full", FULL, FULL_VIS,
                      hero_idx=None if args.no_hero else FULL_HERO,
                      pad_to_lines=False)
    elif args.segment == "kailasa":
        build_segment("kailasa", KAILASA, KAILASA_VIS,
                      hero_idx=None if args.no_hero else [0, 8])
