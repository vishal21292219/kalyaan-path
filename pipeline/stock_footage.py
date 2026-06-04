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

ROOT = Path(__file__).resolve().parent.parent
_FOOTAGE_HISTORY = ROOT / "data" / "state" / "footage_history.json"

# Broad evergreen fallbacks if a specific scene query returns nothing usable.
# STRICTLY period-safe. EXPANDED + rotated so the same fallback clip doesn't
# recur across videos (a big source of the "every video looks the same" feel).
GENERIC_FALLBACKS = [
    "ancient stone ruins", "ancient temple columns", "weathered hieroglyphs",
    "old stone statue", "ancient ruins aerial", "torch lit cave wall",
    "sand dunes wind", "old manuscript pages", "crumbling stone wall",
    "ancient carved relief", "ancient pyramid desert", "stone temple jungle",
    "ancient fortress walls", "carved cave temple", "old ruined amphitheatre",
    "ancient mosaic floor", "weathered stone columns", "misty mountain peaks",
    "stormy ocean waves", "ancient cemetery tombs", "desert canyon rocks",
    "ancient stone archway", "old castle ruins", "flowing lava rock",
    "starlit night sky desert", "frozen glacier ice", "ancient buddha statue",
    "overgrown jungle temple", "ancient roman ruins", "old shipwreck underwater",
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


def _load_footage_history(days: int = 30):
    """Return (full_dict, recent_id_set). Clips used in the last `days` are
    'recent' and get skipped so videos don't reuse the same stock clip."""
    import json as _json
    from datetime import date as _date, timedelta as _td
    try:
        d = _json.loads(_FOOTAGE_HISTORY.read_text())
    except Exception:
        return {}, set()
    cutoff = (_date.today() - _td(days=days)).isoformat()
    return d, {cid for cid, dt in d.items() if str(dt) >= cutoff}


def _save_footage_history(d: dict) -> None:
    import json as _json
    try:
        items = sorted(d.items(), key=lambda kv: kv[1])[-600:]  # prune old
        _FOOTAGE_HISTORY.parent.mkdir(parents=True, exist_ok=True)
        _FOOTAGE_HISTORY.write_text(_json.dumps(dict(items)))
    except Exception as e:
        print(f"[stock] history save skipped: {e}")


def _record_clip(d: dict, cid: str) -> None:
    from datetime import date as _date
    d[str(cid)] = _date.today().isoformat()


def _pexels_search(query: str, api_key: str, per_page: int = 20, page: int = 1) -> list[dict]:
    r = requests.get(
        PEXELS_VIDEO_SEARCH,
        headers={"Authorization": api_key},
        params={"query": query, "orientation": "portrait", "size": "medium",
                "per_page": per_page, "page": page},
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


def _find_clip(query: str, dest: Path, pexels_key: str | None, pixabay_key: str | None,
               recent: set | None = None, run_used: set | None = None,
               used_d: dict | None = None, page: int = 1) -> bool:
    """Search providers for `query`, download the first usable vertical clip that
    was NOT used recently (across videos) or already in THIS video — so the same
    stock clip stops appearing in every reel. `page` is varied per day so even an
    identical query returns a different result set."""
    recent = recent if recent is not None else set()
    run_used = run_used if run_used is not None else set()

    def _take(cid: str, link: str | None, allow_recent: bool) -> bool:
        if not link or cid in run_used:
            return False
        if not allow_recent and cid in recent:
            return False
        if _download(link, dest):
            run_used.add(cid)
            if used_d is not None:
                _record_clip(used_d, cid)
            return True
        return False

    if pexels_key:
        # pass 1: skip recently-used clips; pass 2: allow reuse if nothing fresh
        for allow_recent in (False, True):
            for pg in (page, page + 1):
                for vid in _pexels_search(query, pexels_key, page=pg):
                    if _take(f"px:{vid.get('id')}", _pexels_best_file(vid), allow_recent):
                        return True
    if pixabay_key:
        for allow_recent in (False, True):
            for hit in _pixabay_search(query, pixabay_key):
                if _take(f"pb:{hit.get('id')}", _pixabay_best_url(hit), allow_recent):
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

    # Cross-video recency (skip clips used in the last 30 days) + per-run dedup
    # (never the same clip twice in one reel). Page is rotated by date so even an
    # identical query pulls a different result set each day → no more "same clip
    # in every video".
    import hashlib
    from datetime import date as _date
    used_d, recent = _load_footage_history(days=30)
    run_used: set = set()
    base_page = (int(hashlib.md5(_date.today().isoformat().encode()).hexdigest(), 16) % 4) + 1

    # rotate the fallback list start by date so fallbacks differ across videos too
    fb_start = int(hashlib.md5(_date.today().isoformat().encode()).hexdigest(), 16) % len(GENERIC_FALLBACKS)

    clips: list[Path] = []
    fb_i = 0
    for i, q in enumerate(queries):
        dest = out_dir / f"clip_{i:02d}.mp4"
        if dest.exists() and dest.stat().st_size > 20000:
            clips.append(dest)
            continue
        page = base_page + (i % 3)  # vary page per scene too
        ok = _find_clip(q, dest, pexels_key, pixabay_key, recent, run_used, used_d, page=page)
        # Specific query failed → walk generic fallbacks (date-rotated start)
        tries = 0
        while not ok and tries < len(GENERIC_FALLBACKS):
            fq = GENERIC_FALLBACKS[(fb_start + fb_i) % len(GENERIC_FALLBACKS)]
            fb_i += 1
            tries += 1
            ok = _find_clip(fq, dest, pexels_key, pixabay_key, recent, run_used, used_d, page=page)
            if ok:
                print(f"[stock] scene {i}: '{q}' empty → fallback '{fq}'")
        if ok:
            print(f"[stock] scene {i}: ✓ {q}")
            clips.append(dest)
        else:
            print(f"[stock] scene {i}: ✗ no clip for '{q}' (and fallbacks)")

    _save_footage_history(used_d)
    if not clips:
        raise RuntimeError("Stock footage: could not fetch ANY clip")
    print(f"[stock] {len(clips)}/{len(queries)} scenes have footage ({len(run_used)} unique clips)")
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
