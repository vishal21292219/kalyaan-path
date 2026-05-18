"""Voiceover via edge-tts (FREE Microsoft Edge voices, excellent Hindi support)."""
import asyncio
from pathlib import Path

import edge_tts

from .utils import load_config


def _strip_for_speech(text: str) -> str:
    # Drop emojis / characters that confuse SSML/TTS
    return "".join(ch for ch in text if ord(ch) < 0x2700)


async def _synth(text: str, out_path: Path, voice: str, rate: str, pitch: str) -> None:
    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
    await communicate.save(str(out_path))


def synthesize(script: dict, out_path: Path) -> Path:
    cfg = load_config()
    v = cfg["voice"]
    # Shloka mode uses a slower, sober male voice — Sanskrit gets jumbled
    # with a fast high-pitched voice.
    is_shloka = script.get("kind") == "shloka_episode"
    voice = v.get("shloka_voice", v["voice"]) if is_shloka else v["voice"]
    rate = v.get("shloka_rate", v["rate"]) if is_shloka else v["rate"]
    pitch = v.get("shloka_pitch", v["pitch"]) if is_shloka else v["pitch"]

    lines = [script["hook"], *script["body"], script["cta"]]
    full_text = ". ".join(_strip_for_speech(l).strip().rstrip(".") for l in lines if l) + "."
    out_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_synth(full_text, out_path, voice, rate, pitch))
    return out_path


if __name__ == "__main__":
    demo = {
        "hook": "Kya aap jaante hain Mahadev ka rahasya?",
        "body": ["Shiva ka roop sabse alag hai.", "Wo Adi hai, Anant hai."],
        "cta": "Har Har Mahadev. Follow karein roz darshan ke liye.",
    }
    p = Path("output/audio/demo.mp3")
    synthesize(demo, p)
    print(p)
