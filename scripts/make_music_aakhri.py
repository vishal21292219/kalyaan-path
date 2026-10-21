"""Custom bed for the 'Aakhri Mulaqat' reel — emotional & romantic with a faint
eerie/horror undertone. Generated via fal stable-audio (royalty-free).
Output: data/music_aakhri/emotional_bed.mp3  (picked by pick_drone via drone_dir).

Run from repo root:  python scripts/make_music_aakhri.py
"""
from pathlib import Path
import requests
import fal_client  # uses FAL_KEY from env
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "music_aakhri" / "emotional_bed.mp3"
OUT.parent.mkdir(parents=True, exist_ok=True)

PROMPT = (
    "emotional cinematic background music, romantic yet haunting, tender sad "
    "solo piano melody over warm strings, a faint eerie ghostly undertone, "
    "soft ambient pads, distant music-box twinkle, melancholic and nostalgic "
    "with a subtle chill of suspense, slow tempo, no drums, no beat, no vocals, "
    "hindi film love-story meets gentle horror, atmospheric and dreamy"
)


def main():
    print("[music] generating emotional horror-romantic bed via fal stable-audio…")
    result = fal_client.subscribe(
        "fal-ai/stable-audio",
        arguments={"prompt": PROMPT, "seconds_total": 47},
    )
    url = (result.get("audio_file") or {}).get("url") if isinstance(result.get("audio_file"), dict) else result.get("audio_file")
    if not url and result.get("audio_url"):
        url = result["audio_url"]
    if not url:
        raise RuntimeError(f"no audio url in result: {result}")
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    OUT.write_bytes(r.content)
    print(f"[music] saved → {OUT}  ({len(r.content)//1024} KB)")


if __name__ == "__main__":
    main()
