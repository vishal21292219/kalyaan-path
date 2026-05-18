"""Build one real reel without an LLM — for proving the pipeline works.
Uses a hand-crafted script on Goddess Lakshmi.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.assembler import assemble
from pipeline.image_gen import generate_images
from pipeline.tts import synthesize
from pipeline.utils import out_path, slugify, today_stamp

SCRIPT = {
    "title": "Goddess Lakshmi — The Divine Source of Abundance #Shorts",
    "hook": "Kya aap jaante hain Maa Lakshmi kahan vaas karti hain?",
    "body": [
        "Maa Lakshmi Vishnu ki ardhangini hain.",
        "Wo dhan, samriddhi aur saubhagya ki devi hain.",
        "Kamal par viraajmaan, swarna abhushan se sajjit.",
        "Char haathon mein kamal, shankh aur amrit kalash.",
        "Jahan swachhata aur shraddha hai, wahin wo nivaas karti hain.",
        "Shukrawar ko unki puja vishesh phaldayi hoti hai.",
        "Om Shreem Mahalakshmiyei Namah ka jaap karen.",
    ],
    "cta": "Maa Lakshmi ka ashirwad sada bana rahe. Follow karein roz darshan ke liye.",
    "visuals": [
        "Goddess Lakshmi seated on a giant pink lotus in a calm pond at sunrise, four arms holding lotuses, gold coins flowing from one palm, soft golden divine glow, intricate jewelry, serene face",
        "Closeup of Goddess Lakshmi's serene smiling face, divine golden halo behind her head, red bindi, ornate crown, lotus petals floating around",
        "Goddess Lakshmi standing beside Lord Vishnu on Sheshnag in the cosmic ocean, blue cosmos background, stars and galaxies, divine couple radiating light",
        "Two white elephants showering Goddess Lakshmi with water from golden pots, gajalakshmi composition, lotus pond, morning mist",
        "A traditional Indian home altar during Diwali night, brass lamp diyas lit, Lakshmi idol on a red silk cloth, marigold garlands, rangoli of lotus on the floor",
        "Golden coins, jewelry, and grains of rice flowing from a giant kalash, abundant harvest, sacred imagery, warm golden light",
        "Devotee folding hands in prayer before a glowing image of Goddess Lakshmi, soft incense smoke curling upward, peaceful temple interior",
    ],
    "description": (
        "Maa Lakshmi — Hindu goddess of wealth, prosperity, and abundance. "
        "Discover where she dwells and the mantra to invoke her blessings. "
        "Jai Mata Lakshmi. #Lakshmi #Hinduism #Bhakti #Mantra #Shorts"
    ),
    "hashtags": [
        "#Lakshmi", "#MaaLakshmi", "#Hinduism", "#Bhakti", "#SanatanDharma",
        "#Mantra", "#Diwali", "#Shorts", "#Reels", "#Devotional",
    ],
}


def main() -> int:
    stamp = today_stamp()
    slug = slugify("Goddess Lakshmi")
    base = f"{stamp}_{slug}_demo"

    script_path = out_path("scripts", f"{base}.json")
    script_path.write_text(json.dumps(SCRIPT, indent=2, ensure_ascii=False))
    print(f"[script] saved → {script_path}")

    voice_path = out_path("audio", f"{base}.mp3")
    synthesize(SCRIPT, voice_path)
    print(f"[tts] saved → {voice_path}")

    img_dir = out_path("images", base)
    images = generate_images(SCRIPT["visuals"], img_dir)
    print(f"[images] generated {len(images)}")

    video_path = out_path("videos", f"{base}.mp4")
    assemble(SCRIPT, voice_path, images, video_path)
    print(f"\n[DONE] → {video_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
