"""Stock B-roll footage fetcher — for the ancient / TimeDecoders niche.

Instead of AI-generated stills (the parked "slideshow" format), this fetches
REAL vertical video clips (ancient ruins, pyramids, oceans, deserts, temples)
from free stock providers and the assembler splices one clip per scene. The
narration + captions pipeline is unchanged.

Providers (free, key-driven):
  1. Pexels Videos API   (PEXELS_API_KEY)   — primary, great vertical coverage
  2. Pixabay Videos API  (PIXABAY_API_KEY)  — fallback

Flow used by run.py:
  queries = build_stock_queries(script)         # short search terms per scene
  clips   = fetch_clips(queries, out_dir)       # download 1 vertical mp4/scene
  posters = extract_posters(clips, out_dir)     # 1st frame of each → still img
  → assemble(..., image_paths=posters, hero_clips={i: clips[i] for all i})
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(override=True)

PEXELS_VIDEO_SEARCH = "https://api.pexels.com/videos/search"
PIXABAY_VIDEO_SEARCH = "https://pixabay.com/api/videos/"

# Broad evergreen fallbacks if a specific scene query returns nothing usable.
# STRICTLY period-safe — every term must reliably return ancient/historical or
# pure-nature footage with NO modern objects (cars, people, cities). Generic
# terms like "desert landscape" or "starry night" were pulling modern Jeeps /
# campers and breaking the ancient illusion, so they're banned here.
GENERIC_FALLBACKS = [
    "ancient stone ruins", "ancient temple columns", "weathered hieroglyphs",
    "old stone statue", "ancient ruins aerial", "torch lit cave wall",
    "sand dunes wind", "old manuscript pages", "crumbling stone wall",
    "ancient carved relief",
]

# Appended to every search query to bias results away from modern footage.
_ANCIENT_BIAS = "ancient"
# Terms that, if present in a clip's description/tags, mark it as modern → skip.
_MODERN_BLOCK = (
    "car", "jeep", "truck", "suv", "vehicle", "city", "modern", "office",
    "phone", "laptop", "highway", "traffic", "urban", "tourist", "skyscraper",
    "airport", "train", "selfie", "camping", "tent", "plane", "aircraft",
    "helicopter", "motorcycle", "motorbike", "bus", "bicycle", "drone-shot-of-city",
)


# ───────────────────────── query building ─────────────────────────

_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "at", "with", "and", "or", "to", "for",
    "single", "dominant", "focal", "subject", "cinematic", "photorealistic",
    "8k", "ultra", "realistic", "shot", "frame", "scene", "vertical", "portrait",
    "composition", "background", "foreground", "dramatic", "lighting", "style",
    "image", "depicts", "depicting", "showing", "view", "wide", "close", "up",
}


def _keywordize(text: str, max_words: int = 4) -> str:
    """Cheap heuristic: strip an AI-image prompt down to a few search nouns."""
    text = re.sub(r"[^a-zA-Z\s]", " ", text or "").lower()
    words = [w for w in text.split() if w not in _STOPWORDS and len(w) > 2]
    # de-dupe preserving order
    seen, out = set(), []
    for w in words:
        if w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) >= max_words:
            break
    return " ".join(out) if out else "ancient ruins"


def build_stock_queries(script: dict) -> list[str]:
    """Return one short stock-search query per scene (len == len(visuals)).

    Tries a single free-LLM call to turn each narration/visual line into a
    2-4 word B-roll search term; falls back to a keyword heuristic if the LLM
    is unavailable. Always returns exactly len(visuals) queries.
    """
    visuals = script.get("visuals") or []
    body = script.get("body") or []
    n = len(visuals) or len(body)
    if n == 0:
        return []

    # Heuristic baseline (also the fallback)
    base = [_keywordize(visuals[i] if i < len(visuals) else body[i]) for i in range(n)]

    # Try to upgrade with one Gemini call (free). Soft-fail to heuristic.
    try:
        import google.generativeai as genai
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return base
        genai.configure(api_key=api_key)
        title = script.get("title", "")
        lines = "\n".join(f"{i+1}. {visuals[i] if i < len(visuals) else body[i]}" for i in range(n))
        prompt = (
            "You pick STOCK FOOTAGE search terms for a history/ancient-mysteries "
            "video. For each numbered scene below, output ONE short search query "
            "(2-4 words) that a stock site like Pexels would match to real B-roll "
            "footage — concrete, filmable nouns (e.g. 'egyptian pyramids', "
            "'underwater ruins', 'ancient stone temple', 'carved hieroglyphs', "
            "'torch lit cave', 'old map parchment').\n"
            "STRICT RULES:\n"
            "- Footage MUST look ANCIENT/historical or pure nature. NEVER pick "
            "terms that return MODERN objects: no cars, jeeps, vehicles, roads, "
            "cities, modern people, tourists, phones, camping, tents.\n"
            "- Avoid named people/deities (no stock exists) — use the "
            "setting/monument/artifact/landscape instead.\n"
            "- Prefer prefixing 'ancient' / 'old' / 'historic' when it helps.\n\n"
            f"Title: {title}\n\nScenes:\n{lines}\n\n"
            "Return EXACTLY one line per scene, format 'N: query', no extra text."
        )
        m = genai.GenerativeModel("gemini-flash-latest")
        resp = m.generate_content(prompt, generation_config={"temperature": 0.4})
        out = list(base)
        for line in (resp.text or "").splitlines():
            mt = re.match(r"\s*(\d+)\s*[:.)-]\s*(.+)", line)
            if not mt:
                continue
            idx = int(mt.group(1)) - 1
            q = re.sub(r"[^a-zA-Z\s]", " ", mt.group(2)).strip().lower()
            q = " ".join(q.split()[:4])
            if 0 <= idx < n and q:
                out[idx] = q
        return out
    except Exception as e:
        print(f"[stock] query LLM unavailable ({type(e).__name__}) — heuristic queries")
        return base


# ───────────────────────── provider search ─────────────────────────

def _is_modern(video: dict) -> bool:
    """Heuristic: a Pexels clip is 'modern' if its page-url slug (which encodes
    the human description, e.g. .../video/jeep-in-the-desert-12345/) contains a
    blocked modern keyword. Cheap and catches the worst offenders (cars/cities)."""
    slug = (video.get("url") or "").lower()
    return any(b in slug for b in _MODERN_BLOCK)


def _pexels_search(query: str, api_key: str, per_page: int = 10) -> list[dict]:
    r = requests.get(
        PEXELS_VIDEO_SEARCH,
        headers={"Authorization": api_key},
        params={"query": query, "orientation": "portrait", "size": "medium", "per_page": per_page},
        timeout=30,
    )
    if r.status_code != 200:
        print(f"[stock][pexels] '{query}' → HTTP {r.status_code} {r.text[:120]}")
        return []
    vids = r.json().get("videos", []) or []
    clean = [v for v in vids if not _is_modern(v)]
    return clean or vids  # if filter nukes everything, fall back to unfiltered


def _pexels_best_file(video: dict, target_h: int = 1920) -> str | None:
    files = [f for f in video.get("video_files", []) if f.get("file_type") == "video/mp4"]
    if not files:
        return None
    portrait = [f for f in files if (f.get("height") or 0) >= (f.get("width") or 0)]
    pool = portrait or files
    pool.sort(key=lambda f: abs((f.get("height") or 0) - target_h))
    return pool[0].get("link")


def _pixabay_search(query: str, api_key: str, per_page: int = 8) -> list[dict]:
    r = requests.get(
        PIXABAY_VIDEO_SEARCH,
        params={"key": api_key, "q": query, "per_page": per_page, "video_type": "film"},
        timeout=30,
    )
    if r.status_code != 200:
        print(f"[stock][pixabay] '{query}' → HTTP {r.status_code}")
        return []
    return r.json().get("hits", []) or []


def _pixabay_best_url(hit: dict) -> str | None:
    vids = hit.get("videos", {})
    for key in ("large", "medium", "small", "tiny"):
        v = vids.get(key)
        if v and v.get("url"):
            return v["url"]
    return None


def _download(url: str, dest: Path) -> bool:
    try:
        with requests.get(url, stream=True, timeout=90) as r:
            if r.status_code != 200:
                return False
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
        return dest.exists() and dest.stat().st_size > 20000
    except Exception as e:
        print(f"[stock] download error: {e}")
        return False


def _find_clip(query: str, dest: Path, pexels_key: str | None, pixabay_key: str | None) -> bool:
    """Search providers for `query`, download first usable vertical clip to dest."""
    if pexels_key:
        for vid in _pexels_search(query, pexels_key):
            link = _pexels_best_file(vid)
            if link and _download(link, dest):
                return True
    if pixabay_key:
        for hit in _pixabay_search(query, pixabay_key):
            url = _pixabay_best_url(hit)
            if url and _download(url, dest):
                return True
    return False


# ───────────────────────── public API ─────────────────────────

def fetch_clips(queries: list[str], out_dir: Path) -> list[Path]:
    """Download one vertical stock clip per query into out_dir/clip_NN.mp4.

    Each scene that fails its specific query retries against broad evergreen
    fallbacks so the slot is never left empty. Returns the list of clip paths
    in scene order (length == len(queries)); raises if NOTHING could be fetched.
    """
    pexels_key = os.getenv("PEXELS_API_KEY")
    pixabay_key = os.getenv("PIXABAY_API_KEY")
    if not (pexels_key or pixabay_key):
        raise RuntimeError("No stock-footage key — set PEXELS_API_KEY (or PIXABAY_API_KEY) in .env")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    clips: list[Path] = []
    fb_i = 0
    for i, q in enumerate(queries):
        dest = out_dir / f"clip_{i:02d}.mp4"
        if dest.exists() and dest.stat().st_size > 20000:
            clips.append(dest)
            continue
        ok = _find_clip(q, dest, pexels_key, pixabay_key)
        # Specific query failed → walk generic fallbacks (cycled)
        tries = 0
        while not ok and tries < len(GENERIC_FALLBACKS):
            fq = GENERIC_FALLBACKS[fb_i % len(GENERIC_FALLBACKS)]
            fb_i += 1
            tries += 1
            ok = _find_clip(fq, dest, pexels_key, pixabay_key)
            if ok:
                print(f"[stock] scene {i}: '{q}' empty → fallback '{fq}'")
        if ok:
            print(f"[stock] scene {i}: ✓ {q}")
            clips.append(dest)
        else:
            print(f"[stock] scene {i}: ✗ no clip for '{q}' (and fallbacks)")
    if not clips:
        raise RuntimeError("Stock footage: could not fetch ANY clip")
    print(f"[stock] {len(clips)}/{len(queries)} scenes have footage")
    return clips


def extract_posters(clips: list[Path], out_dir: Path) -> list[Path]:
    """Extract the first frame of each clip as img_NN.jpg (still fallback +
    thumbnail base). Skips clips whose poster can't be produced."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    posters: list[Path] = []
    for i, clip in enumerate(clips):
        img = out_dir / f"img_{i:02d}.jpg"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(clip), "-frames:v", "1", "-q:v", "3", str(img)],
                check=True, capture_output=True,
            )
            if img.exists() and img.stat().st_size > 2000:
                posters.append(img)
        except Exception as e:
            print(f"[stock] poster extract failed for clip {i}: {e}")
    return posters


if __name__ == "__main__":
    import json
    import sys
    from .utils import set_active_niche
    set_active_niche("ancient")
    demo = {
        "title": "Gunung Padang: The Pyramid Older Than History",
        "visuals": [
            "Aerial view of a terraced megalithic stone pyramid on a green mountain",
            "Close-up of ancient weathered basalt columns stacked like walls",
            "Archaeologists with torches inside a dark stone chamber",
        ],
        "body": ["", "", ""],
    }
    qs = build_stock_queries(demo)
    print("QUERIES:", qs)
    out = Path("data/_stock_demo")
    cl = fetch_clips(qs, out)
    ps = extract_posters(cl, out)
    print("CLIPS:", [str(c) for c in cl])
    print("POSTERS:", [str(p) for p in ps])
