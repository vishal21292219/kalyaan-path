"""Voiceover via configurable TTS provider.

Supported providers (set via config voice.provider):
- "edge"        — FREE Microsoft Edge voices via edge-tts (default)
- "elevenlabs"  — Premium ElevenLabs voices (~$22/mo for daily content)

Edge-tts mode ALSO captures word-level timings → saved as
{out_path}.words.json — used by captions.py to render animated
word-by-word subtitles.

ElevenLabs setup:
1. Sign up at https://elevenlabs.io and add ELEVENLABS_API_KEY to .env
2. Pick voices at https://elevenlabs.io/app/voice-library (filter: Hindi)
3. Recommended model: eleven_multilingual_v2
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from .utils import load_config

load_dotenv()


def _strip_for_speech(text: str) -> str:
    return "".join(ch for ch in text if ord(ch) < 0x2700)


def _build_text(script: dict) -> str:
    lines = [script["hook"], *script["body"], script["cta"]]
    return ". ".join(_strip_for_speech(l).strip().rstrip(".") for l in lines if l) + "."


# ─── Edge TTS (free Microsoft voices) ────────────────────────────────────
async def _edge_synth_with_boundaries(
    text: str, out_path: Path, voice: str, rate: str, pitch: str
) -> list[dict]:
    """Synthesize via edge-tts, capture audio + word boundaries.
    Returns list of {text, start, end} dicts (seconds)."""
    import edge_tts
    # edge-tts >=7 defaults to SentenceBoundary and emits NO WordBoundary events
    # unless boundary="WordBoundary" is requested. Without this the pipeline fell
    # back to silence/uniform estimation → captions drifted out of sync with the
    # voice (worst on long English narration). Requesting WordBoundary restores
    # accurate per-word timing for every voice, Hindi and English alike.
    try:
        communicate = edge_tts.Communicate(
            text=text, voice=voice, rate=rate, pitch=pitch, boundary="WordBoundary"
        )
    except TypeError:
        # Older edge-tts without the `boundary` kwarg — fall back to default.
        communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
    audio = bytearray()
    boundaries: list[dict] = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            # offset/duration are in 100-nanosecond units
            start = chunk["offset"] / 1e7
            duration = chunk["duration"] / 1e7
            boundaries.append({
                "text": chunk["text"],
                "start": round(start, 3),
                "end": round(start + duration, 3),
            })
    out_path.write_bytes(bytes(audio))
    return boundaries


def _synth_edge(text: str, out_path: Path, v: dict, is_shloka: bool) -> list[dict]:
    voice = v.get("shloka_voice", v["voice"]) if is_shloka else v["voice"]
    rate = v.get("shloka_rate", v["rate"]) if is_shloka else v["rate"]
    pitch = v.get("shloka_pitch", v["pitch"]) if is_shloka else v["pitch"]
    boundaries = asyncio.run(_edge_synth_with_boundaries(text, out_path, voice, rate, pitch))
    # Hindi voices (hi-IN-*) don't emit WordBoundary events. Use a layered
    # alignment strategy:
    #   1. Silence-based: detect pauses between sentences via ffmpeg's
    #      silencedetect, match to original sentences, distribute words by
    #      char-weight within each segment. ACCURATE because TTS sentences
    #      generate predictable inter-sentence pauses.
    #   2. Whisper: forced alignment of audio (may miss audio sections).
    #   3. Uniform: simple char-weighted distribution across full audio.
    if not boundaries:
        boundaries = _silence_align(text, out_path)
    if not boundaries:
        boundaries = _whisper_align(out_path, original_text=text)
    if not boundaries:
        boundaries = _estimate_word_boundaries(text, out_path)
    return boundaries


def _silence_align(text: str, audio_path: Path) -> list[dict]:
    """Align original script words to audio via ffmpeg silence detection.

    Splits text on Devanagari/ASCII sentence terminators, matches each
    sentence to a speech segment between detected silences, then distributes
    each sentence's words by character weight across its segment duration.
    Falls back (returns []) if sentence count doesn't match segment count.
    """
    import re
    import subprocess

    duration = _audio_duration_seconds(audio_path)
    if duration <= 0:
        return []

    # Detect silences (1.0s minimum, -45dB threshold — matches TTS pauses)
    try:
        r = subprocess.run(
            ["ffmpeg", "-i", str(audio_path), "-af",
             "silencedetect=noise=-45dB:d=0.6", "-f", "null", "-"],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        return []

    silences: list[tuple[float, float]] = []
    cur_start = None
    for line in r.stderr.split("\n"):
        m = re.search(r"silence_start:\s+([0-9.]+)", line)
        if m:
            cur_start = float(m.group(1))
            continue
        m = re.search(r"silence_end:\s+([0-9.]+)", line)
        if m and cur_start is not None:
            silences.append((cur_start, float(m.group(1))))
            cur_start = None

    # Build speech segments: between silences (and from 0 / to duration)
    segments: list[tuple[float, float]] = []
    cursor = 0.0
    for sil_start, sil_end in silences:
        if sil_start - cursor > 0.3:  # ignore micro segments
            segments.append((cursor, sil_start))
        cursor = sil_end
    if duration - cursor > 0.3:
        segments.append((cursor, duration))

    if not segments:
        return []

    # Split original text into sentences (Devanagari danda + ASCII terminators)
    sentences = [s.strip() for s in re.split(r"[।॥\.!?]+", text) if s.strip()]
    if not sentences:
        return []

    # If sentence count doesn't match segment count, abort — caller will fall back
    if len(sentences) != len(segments):
        print(f"[silence-align] sentences={len(sentences)} != segments={len(segments)}, skipping")
        return []

    boundaries: list[dict] = []
    sentence_segments: list[dict] = []  # for image sync — saved separately
    for sent, (seg_start, seg_end) in zip(sentences, segments):
        sentence_segments.append({
            "text": sent,
            "start": round(seg_start, 3),
            "end": round(seg_end, 3),
        })
        words = []
        for raw in sent.split():
            w = raw.strip(",.!?।॥;:()[]{}\"'`")
            if w:
                words.append(w)
        if not words:
            continue
        weights = [max(1, len(w)) for w in words]
        total_w = sum(weights)
        seg_dur = max(0.2, seg_end - seg_start)
        cumulative = 0
        for word, weight in zip(words, weights):
            start_t = seg_start + (cumulative / total_w) * seg_dur
            cumulative += weight
            end_t = seg_start + (cumulative / total_w) * seg_dur
            boundaries.append({
                "text": word,
                "start": round(start_t, 3),
                "end": round(end_t, 3),
            })

    # Save sentence-level segments so assembler can sync images to them
    try:
        import json as _json
        sents_path = audio_path.with_suffix(".sentences.json")
        sents_path.write_text(
            _json.dumps(sentence_segments, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        print(f"[silence-align] could not write sentences.json: {e}")

    print(f"[silence-align] aligned {len(boundaries)} words across {len(segments)} segments")
    return boundaries


# ─── Whisper forced alignment (accurate word timings from audio) ─────────
_WHISPER_MODEL = None


def _whisper_align(
    audio_path: Path,
    original_text: str = "",
    language: str = "hi",
    model_size: str = "medium",
) -> list[dict]:
    """Run faster-whisper on audio for per-word timings, then map back to
    original script text for correct Devanagari spelling.

    Pass `original_text` (what TTS spoke) to:
    - bias transcription via initial_prompt (better accuracy)
    - swap Whisper's transcribed text with original spelling when word counts
      match closely (timings stay from Whisper)

    'medium' model: ~150MB download, much better Hindi than 'small'.
    Memory-cached after first load.
    """
    global _WHISPER_MODEL
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("[whisper] faster-whisper not installed, skipping alignment")
        return []

    if _WHISPER_MODEL is None:
        size_mb = {"small": 75, "medium": 150, "large-v3": 1500}.get(model_size, 75)
        print(f"[whisper] loading model '{model_size}' (first run downloads ~{size_mb}MB)...")
        try:
            _WHISPER_MODEL = WhisperModel(model_size, device="cpu", compute_type="int8")
        except Exception as e:
            print(f"[whisper] model load failed: {e}")
            return []

    try:
        kwargs = dict(
            word_timestamps=True,
            language=language,
            vad_filter=False,
            beam_size=1,
            best_of=1,
        )
        if original_text:
            # initial_prompt biases Whisper toward our exact vocabulary
            kwargs["initial_prompt"] = original_text[:240]  # 240-char limit

        segments, _info = _WHISPER_MODEL.transcribe(str(audio_path), **kwargs)

        whisper_words: list[dict] = []
        for seg in segments:
            if not seg.words:
                continue
            for w in seg.words:
                t = (w.word or "").strip()
                if not t:
                    continue
                whisper_words.append({
                    "text": t,
                    "start": round(w.start, 3),
                    "end": round(w.end, 3),
                })
        print(f"[whisper] aligned {len(whisper_words)} words")

        # Try to replace Whisper text with original script text (correct spelling)
        if original_text and whisper_words:
            return _map_to_original(whisper_words, original_text)
        return whisper_words
    except Exception as e:
        print(f"[whisper] transcribe failed: {e}")
        return []


def _map_to_original(whisper_words: list[dict], original_text: str) -> list[dict]:
    """Always produce original-script text with timings anchored to Whisper.

    Strategy:
    - If Whisper word count matches original within 5% → direct 1:1 map.
    - Otherwise → use Whisper's first-word start and last-word end as anchors,
      distribute original words by character-count weight across that window.
      Original spelling is always preserved; Whisper provides timing anchors.
    """
    original = []
    for raw in original_text.split():
        w = raw.strip(",.!?।॥;:()[]{}\"'`")
        if w:
            original.append(w)

    if not original or not whisper_words:
        return whisper_words

    nw, no = len(whisper_words), len(original)
    diff_ratio = abs(nw - no) / max(no, 1)

    if diff_ratio <= 0.05:
        # Direct 1:1 mapping
        n = min(nw, no)
        result = []
        for i in range(n):
            result.append({
                "text": original[i],
                "start": whisper_words[i]["start"],
                "end": whisper_words[i]["end"],
            })
        print(f"[whisper] direct remap to original script ({n} words)")
        return result

    # Counts differ — interpolate original words by char-weight between
    # Whisper's first start and last end (still TTS-anchored sync).
    speech_start = whisper_words[0]["start"]
    speech_end = whisper_words[-1]["end"]
    speech_dur = max(0.5, speech_end - speech_start)

    weights = [max(1, len(w)) for w in original]
    total_w = sum(weights)

    result = []
    cumulative = 0
    for word, weight in zip(original, weights):
        start_t = speech_start + (cumulative / total_w) * speech_dur
        cumulative += weight
        end_t = speech_start + (cumulative / total_w) * speech_dur
        result.append({
            "text": word,
            "start": round(start_t, 3),
            "end": round(end_t, 3),
        })
    print(f"[whisper] interpolated remap (whisper={nw}, original={no}) anchored to {speech_start:.2f}-{speech_end:.2f}s")
    return result


def _estimate_word_boundaries(text: str, audio_path: Path) -> list[dict]:
    """Distribute words across audio duration weighted by char count.
    Used when TTS doesn't emit per-word timing (e.g., Hindi edge-tts voices).
    """
    duration = _audio_duration_seconds(audio_path)
    if duration <= 0:
        return []

    # Split into spoken words (skip pure punctuation)
    raw_words = text.split()
    words: list[str] = []
    for rw in raw_words:
        w = rw.strip(",.!?।॥;:()[]{}\"'`")
        if w:
            words.append(w)
    if not words:
        return []

    # Weight by char length (proxy for syllable count — works reasonably
    # for Hindi where each akshara is ~1 syllable).
    weights = [max(1, len(w)) for w in words]
    total_w = sum(weights)

    # Leave 200ms head silence and 200ms tail silence
    head = 0.20
    tail = 0.20
    speech_dur = max(0.1, duration - head - tail)

    boundaries = []
    cumulative = 0
    for word, w in zip(words, weights):
        start_t = head + (cumulative / total_w) * speech_dur
        cumulative += w
        end_t = head + (cumulative / total_w) * speech_dur
        boundaries.append({
            "text": word,
            "start": round(start_t, 3),
            "end": round(end_t, 3),
        })
    return boundaries


# ─── ElevenLabs (premium) ────────────────────────────────────────────────
def _words_from_char_alignment(align: dict) -> list[dict]:
    """Convert ElevenLabs char-level alignment into accurate word boundaries.

    The /with-timestamps endpoint returns per-character start/end times. Grouping
    characters into words (split on whitespace) gives EXACT word timing — fixes
    the caption drift that uniform estimation caused, worst at the start of long
    narration."""
    chars = align.get("characters") or []
    starts = align.get("character_start_times_seconds") or []
    ends = align.get("character_end_times_seconds") or []
    if not (chars and starts and ends) or not (len(chars) == len(starts) == len(ends)):
        return []
    words: list[dict] = []
    cur, w_start, w_end = "", None, None
    for ch, s, e in zip(chars, starts, ends):
        if ch.isspace():
            if cur:
                words.append({"text": cur, "start": round(w_start, 3), "end": round(w_end, 3)})
                cur, w_start, w_end = "", None, None
            continue
        if w_start is None:
            w_start = s
        cur += ch
        w_end = e
    if cur:
        words.append({"text": cur, "start": round(w_start, 3), "end": round(w_end, 3)})
    return words


def _synth_elevenlabs(text: str, out_path: Path, v: dict, is_shloka: bool) -> list[dict]:
    """Synthesize via ElevenLabs using the /with-timestamps endpoint so captions
    get EXACT per-word timing (stay in sync). Falls back to plain TTS + uniform
    estimate only if the timestamps endpoint is unavailable."""
    import requests
    import base64
    api_key = os.getenv("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ELEVENLABS_API_KEY not set in .env. "
            "Get one at https://elevenlabs.io → Profile → API Keys."
        )

    # Gender-aware voice pick (narrator_gender stashed by synthesize()): male →
    # elevenlabs_voice_id, female → elevenlabs_voice_id_female.
    gender = str(v.get("_narrator_gender", "male")).lower()
    if is_shloka:
        voice_id = v.get("elevenlabs_shloka_voice_id") or v.get("elevenlabs_voice_id")
    elif gender == "female" and v.get("elevenlabs_voice_id_female"):
        voice_id = v.get("elevenlabs_voice_id_female")
    else:
        voice_id = v.get("elevenlabs_voice_id")
    if not voice_id:
        raise RuntimeError("voice.elevenlabs_voice_id not set in config.")

    model = v.get("elevenlabs_model", "eleven_multilingual_v2")
    settings = v.get("elevenlabs_settings", {}) or {}

    payload = {
        "text": text,
        "model_id": model,
        "voice_settings": {
            "stability": settings.get("stability", 0.55),
            "similarity_boost": settings.get("similarity_boost", 0.80),
            "style": settings.get("style", 0.35),
            "use_speaker_boost": settings.get("use_speaker_boost", True),
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # PRIMARY: /with-timestamps → audio (base64) + exact per-character alignment.
    try:
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps",
            headers={"xi-api-key": api_key, "Content-Type": "application/json",
                     "Accept": "application/json"},
            json=payload, timeout=180,
        )
        if r.status_code != 200:
            raise RuntimeError(f"timestamps API {r.status_code}: {r.text[:200]}")
        data = r.json()
        out_path.write_bytes(base64.b64decode(data["audio_base64"]))
        align = data.get("alignment") or data.get("normalized_alignment") or {}
        boundaries = _words_from_char_alignment(align)
        if boundaries:
            print(f"[tts] elevenlabs /with-timestamps → {len(boundaries)} exact word boundaries")
            return boundaries
        print("[tts] elevenlabs alignment empty — falling back to uniform estimate")
    except Exception as e:
        print(f"[tts] /with-timestamps failed ({e}); falling back to plain TTS + uniform estimate")
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={"xi-api-key": api_key, "Content-Type": "application/json",
                     "Accept": "audio/mpeg"},
            json=payload, timeout=120,
        )
        if r.status_code != 200:
            raise RuntimeError(f"ElevenLabs API error {r.status_code}: {r.text[:300]}")
        out_path.write_bytes(r.content)

    # FALLBACK ONLY: uniform distribution (used when alignment unavailable)
    duration = _audio_duration_seconds(out_path)
    words = text.split()
    boundaries = []
    if words and duration > 0:
        per_word = duration / len(words)
        for i, w in enumerate(words):
            boundaries.append({
                "text": w,
                "start": round(i * per_word, 3),
                "end": round((i + 1) * per_word, 3),
            })
    return boundaries


def _audio_duration_seconds(path: Path) -> float:
    import subprocess
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _synth_sarvam(text: str, out_path: Path, v: dict, is_shloka: bool) -> list[dict]:
    """Sarvam AI (Bulbul) TTS — natural Hindi, cheap. Chunks text to <=480 chars,
    calls the API per chunk, concatenates the WAVs, encodes to mp3, then aligns
    word timings via the same fallback chain as edge (Sarvam gives no per-word
    timing)."""
    import base64
    import re as _re
    import subprocess
    import wave

    import requests

    api_key = os.getenv("SARVAM_API_KEY")
    if not api_key:
        raise RuntimeError("SARVAM_API_KEY not set in .env")
    speaker = v.get("sarvam_shloka_speaker", v.get("sarvam_speaker", "abhilash")) if is_shloka \
        else v.get("sarvam_speaker", "abhilash")
    model = v.get("sarvam_model", "bulbul:v2")
    lang = v.get("sarvam_language", "hi-IN")
    pace = float(v.get("sarvam_pace", 1.0))
    pitch = float(v.get("sarvam_pitch", 0.0))

    def _chunks(s: str, n: int = 480) -> list[str]:
        s = s.strip()
        parts, cur = [], ""
        for sent in _re.split(r"(?<=[.!?।])\s+", s):
            if len(cur) + len(sent) + 1 <= n:
                cur = (cur + " " + sent).strip()
            else:
                if cur:
                    parts.append(cur)
                if len(sent) <= n:
                    cur = sent
                else:
                    for i in range(0, len(sent), n):
                        parts.append(sent[i:i + n])
                    cur = ""
        if cur:
            parts.append(cur)
        return parts or [s]

    pcm, params = [], None
    for idx, ch in enumerate(_chunks(text)):
        r = requests.post(
            "https://api.sarvam.ai/text-to-speech",
            headers={"api-subscription-key": api_key, "Content-Type": "application/json"},
            json={"inputs": [ch], "target_language_code": lang, "speaker": speaker,
                  "model": model, "pace": pace, "pitch": pitch,
                  "speech_sample_rate": 22050, "enable_preprocessing": True},
            timeout=90,
        )
        r.raise_for_status()
        b64 = (r.json().get("audios") or [None])[0]
        if not b64:
            raise RuntimeError(f"Sarvam returned no audio (chunk {idx})")
        tmp = out_path.with_suffix(f".sv{idx}.wav")
        tmp.write_bytes(base64.b64decode(b64))
        with wave.open(str(tmp), "rb") as w:
            params = params or w.getparams()
            pcm.append(w.readframes(w.getnframes()))
        tmp.unlink()

    combined = out_path.with_suffix(".sarvam.wav")
    with wave.open(str(combined), "wb") as w:
        w.setparams(params)
        for fr in pcm:
            w.writeframes(fr)
    subprocess.run(["ffmpeg", "-y", "-i", str(combined), "-c:a", "libmp3lame",
                    "-b:a", "192k", str(out_path)], check=True, capture_output=True)
    combined.unlink()

    boundaries = _silence_align(text, out_path)
    if not boundaries:
        boundaries = _whisper_align(out_path, original_text=text)
    if not boundaries:
        boundaries = _estimate_word_boundaries(text, out_path)
    return boundaries


# ─── Public API ──────────────────────────────────────────────────────────
def synthesize(script: dict, out_path: Path, seed_offset: int = 0) -> Path:
    """Synthesize voice. `seed_offset` rotates voice across slots if `voice_pool`
    is configured (anti-AI-slop diversification — each slot uses a different
    voice fingerprint so YT can't pattern-detect a templated channel)."""
    cfg = load_config()
    v = dict(cfg["voice"])  # copy so we can mutate locally
    provider = v.get("provider", "edge").lower()
    is_shloka = script.get("kind") == "shloka_episode"

    # Gender-driven voice (TimeDecoders): the script's narrator_gender, chosen by
    # the LLM per story tone, maps to a specific voice. Takes PRECEDENCE over
    # voice_pool rotation. Missing/unknown gender -> male (default).
    vbg = v.get("voice_by_gender") or {}
    pool = v.get("voice_pool") or []
    if vbg and not is_shloka:
        gender = str(script.get("narrator_gender", "male")).strip().lower()
        if gender not in vbg:
            gender = "male" if "male" in vbg else next(iter(vbg))
        v["voice"] = vbg[gender]            # edge voice
        v["_narrator_gender"] = gender      # ElevenLabs voice-id picker uses this
        print(f"[tts] narrator_gender={gender} -> voice={v['voice']}")
    # Voice rotation: if a pool is defined (and no gender map), pick by (date +
    # seed) so the same slot uses the same voice on a given day.
    elif pool and not is_shloka:
        from datetime import date as _date_t
        idx = (int(_date_t.today().toordinal()) + seed_offset) % len(pool)
        chosen = pool[idx]
        print(f"[tts] voice rotation: pool[{idx}/{len(pool)}] = {chosen}  (seed={seed_offset})")
        v["voice"] = chosen

    text = _build_text(script)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    boundaries: list[dict] = []
    if provider == "elevenlabs":
        try:
            boundaries = _synth_elevenlabs(text, out_path, v, is_shloka)
            print(f"[tts] provider=elevenlabs ({len(text)} chars)")
        except Exception as e:
            if v.get("fallback_to_edge", True):
                print(f"[tts] ElevenLabs failed ({e}), falling back to edge-tts")
                boundaries = _synth_edge(text, out_path, v, is_shloka)
            else:
                raise
    elif provider == "sarvam":
        try:
            boundaries = _synth_sarvam(text, out_path, v, is_shloka)
            print(f"[tts] provider=sarvam speaker={v.get('sarvam_speaker', 'abhilash')} ({len(text)} chars)")
        except Exception as e:
            if v.get("fallback_to_edge", True):
                print(f"[tts] Sarvam failed ({e}), falling back to edge-tts")
                boundaries = _synth_edge(text, out_path, v, is_shloka)
            else:
                raise
    else:
        boundaries = _synth_edge(text, out_path, v, is_shloka)

    # Save word boundaries alongside audio
    words_path = out_path.with_suffix(".words.json")
    words_path.write_text(json.dumps(boundaries, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[tts] captured {len(boundaries)} word boundaries → {words_path.name}")

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
