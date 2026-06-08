"""Authentic real-photo fetcher for Indian monuments/temples from Wikimedia.

Why: Pexels/stock has almost no footage of specific Indian monuments, so
footage mode returned FOREIGN temples (authenticity killer). Wikimedia Commons
has real, freely-licensed photos of the actual monuments. We pull those, keep
only commercial-safe licenses (PD/CC0/CC BY/CC BY-SA), crop to vertical, and
return per-image attribution strings (auto-added to the video description).
The existing Ken Burns motion in the assembler animates these stills.

Legal: only PD/CC0/CC BY/CC BY-SA files are kept; fair-use/non-free are
skipped. CC BY/BY-SA require credit (a name line in the description) — no
payment. Credits are returned so the caller can append them.
"""
from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

API = "https://en.wikipedia.org/w/api.php"
COMMONS = "https://commons.wikimedia.org/w/api.php"

# Real-PERSON subjects → pin the recognizable free-licensed FACE photo(s) first
# (Commons category order tends to surface temples/statues before the portrait).
# Key is matched as a lowercase substring of the search query.
_PINNED_FILES = {
    "neem karoli baba": [
        "File:Neemkaroli 14.jpg",       # iconic plaid-blanket portrait (Public Domain)
        "File:Neem Karoli baba.jpg",    # garlanded altar portrait (CC0)
    ],
}
HEADERS = {"User-Agent": "BhaktiReels/1.0 (educational reels; gopulabs@gmail.com)"}

# Commercial-safe licenses (attribution may be required → we add credits).
_FREE_RE = re.compile(r"(public domain|^\s*cc0|cc[\s-]*by([\s-]*sa)?)", re.I)
# Hard blocks — never use these.
_BLOCK_RE = re.compile(r"(fair[\s-]*use|non[\s-]*free|all rights reserved|©|copyright)", re.I)
# Filenames that are icons/diagrams/maps/logos, not real photos.
_SKIP_FILE_RE = re.compile(
    r"(\.svg$|\.gif$|\.ogv$|\.webm$|logo|icon|\bmap\b|coat[_ ]of[_ ]arms|locator|"
    r"flag|seal|diagram|\bplan\b|symbol|emblem|signature|barnstar|wikidata|"
    r"\bom\b|yantra|chakra_logo|edit-|ooui|commons-logo|"
    r"rupee|\bcoin\b|stamp|banknote|postage|currency|\bnote\b|"
    r"\bsign\b|signboard|nameboard|plaque|ticket|brochure|book[_ ]cover|poster)",
    re.I,
)


def _get(endpoint: str, params: dict) -> dict:
    params = {**params, "format": "json"}
    return requests.get(endpoint, params=params, headers=HEADERS, timeout=25).json()


def _search_article(query: str) -> str | None:
    """Best-matching English Wikipedia article title for a query, or None."""
    try:
        r = _get(API, {"action": "query", "list": "search", "srsearch": query, "srlimit": 1})
        hits = r.get("query", {}).get("search", [])
        return hits[0]["title"] if hits else None
    except Exception:
        return None


def _search_commons_category(query: str) -> str | None:
    """Best-matching Commons Category (namespace 14) for a query — usually the
    richest source of real photos of a specific monument."""
    try:
        r = _get(COMMONS, {
            "action": "query", "list": "search", "srnamespace": 14,
            "srsearch": query, "srlimit": 1,
        })
        hits = r.get("query", {}).get("search", [])
        return hits[0]["title"] if hits else None
    except Exception:
        return None


def _category_files(category: str, limit: int = 80) -> list[str]:
    """File: titles directly in a Commons category."""
    try:
        r = _get(COMMONS, {
            "action": "query", "list": "categorymembers", "cmtitle": category,
            "cmtype": "file", "cmlimit": limit,
        })
        return [m["title"] for m in r.get("query", {}).get("categorymembers", [])]
    except Exception:
        return []


def _article_image_files(title: str, limit: int = 60) -> list[str]:
    """All File: titles used on an article (in roughly page order)."""
    try:
        r = _get(API, {
            "action": "query", "titles": title, "generator": "images",
            "gimlimit": limit, "prop": "info", "redirects": 1,
        })
        pages = r.get("query", {}).get("pages", {}).values()
        return [p["title"] for p in pages if p.get("title", "").startswith("File:")]
    except Exception:
        return []


def _file_meta(file_title: str) -> dict | None:
    try:
        r = _get(COMMONS, {
            "action": "query", "titles": file_title, "prop": "imageinfo",
            "iiprop": "url|extmetadata|mime|size",
        })
        pages = list(r.get("query", {}).get("pages", {}).values())
        if not pages or "imageinfo" not in pages[0]:
            return None
        ii = pages[0]["imageinfo"][0]
        em = ii.get("extmetadata", {}) or {}

        def g(k):
            return (em.get(k, {}) or {}).get("value", "") or ""

        artist = re.sub(r"<[^>]+>", "", g("Artist")).strip()
        artist = re.sub(r"\s+", " ", artist)[:60]
        return {
            "url": ii.get("url"),
            "mime": ii.get("mime", ""),
            "width": int(ii.get("width", 0) or 0),
            "license": g("LicenseShortName").strip(),
            "artist": artist,
        }
    except Exception:
        return None


def _is_free(meta: dict) -> bool:
    lic = meta.get("license", "")
    if not lic or _BLOCK_RE.search(lic):
        return False
    return bool(_FREE_RE.search(lic))


def fetch_wiki_images(
    topic: dict, out_dir: Path, want: int = 12, min_width: int = 500,
) -> tuple[list[Path], list[str]]:
    """Download up to `want` authentic, free-licensed real photos of the topic's
    monument from Wikimedia (Commons category first, then article images).
    Returns (image_paths, credit_lines).

    Falls back to [] if it can't resolve a subject or find enough real photos —
    the caller should then use AI images.
    """
    from pipeline.image_gen import _fit_to_aspect

    out_dir.mkdir(parents=True, exist_ok=True)

    # Build resolution queries: explicit English hints win over the Hinglish
    # display title (search can't parse "Konark ka 52-ton magnet").
    #   wiki  = exact subject hint (set on series episodes)
    #   query = clean English keywords (present on AM trending topics)
    queries: list[str] = []
    for key in ("wiki", "query", "title"):
        v = topic.get(key)
        if v:
            queries.append(str(v).replace("_", " "))

    # PINNED files — for real-PERSON subjects (saints/gurus) the recognizable
    # FACE must lead, but Commons category order often surfaces temples/statues
    # first. Pin the known free-licensed portrait(s) so slot 0 = the actual face.
    files: list[str] = []
    for q in queries:
        for pin_key, pin_files in _PINNED_FILES.items():
            if pin_key in q.strip().lower():
                files = list(pin_files)
                break
        if files:
            break

    # Collect candidate files: Commons category (richest) + Wikipedia article.
    seen_q = set()
    for q in queries:
        if q in seen_q:
            continue
        seen_q.add(q)
        cat = _search_commons_category(q)
        if cat:
            files += _category_files(cat)
        art = _search_article(q)
        if art:
            files += _article_image_files(art)
        if len(files) >= want * 4:
            break
    # de-dupe preserving order
    files = list(dict.fromkeys(files))
    if not files:
        return [], []

    paths: list[Path] = []
    credits: list[str] = []
    i = 0
    for ft in files:
        if _SKIP_FILE_RE.search(ft):
            continue
        meta = _file_meta(ft)
        if not meta or not meta.get("url"):
            continue
        if not meta["mime"].startswith("image/") or meta["mime"] == "image/svg+xml":
            continue
        if meta["width"] and meta["width"] < min_width:
            continue
        if not _is_free(meta):
            continue
        try:
            resp = requests.get(meta["url"], headers=HEADERS, timeout=40)
            img = Image.open(BytesIO(resp.content)).convert("RGB")
        except Exception:
            continue
        img = _fit_to_aspect(img, 1080, 1920)
        p = out_dir / f"img_{i:02d}.jpg"
        img.save(str(p), "JPEG", quality=90)
        paths.append(p)

        name = ft[len("File:"):].rsplit(".", 1)[0].replace("_", " ")
        line = name
        if meta["artist"]:
            line += f" by {meta['artist']}"
        line += f" ({meta['license']})"
        credits.append(line)
        i += 1
        if i >= want:
            break

    return paths, credits


def build_credit_block(credits: list[str]) -> str:
    """Human-readable attribution block for the video description."""
    if not credits:
        return ""
    body = "\n".join(f"• {c}" for c in credits)
    return (
        "📷 Image credits (all free-licensed, via Wikimedia Commons):\n"
        f"{body}"
    )


if __name__ == "__main__":
    import sys, tempfile
    t = {"title": sys.argv[1] if len(sys.argv) > 1 else "Padmanabhaswamy Vault B"}
    d = Path(tempfile.mkdtemp())
    ps, cr = fetch_wiki_images(t, d, want=12)
    print(f"got {len(ps)} photos in {d}")
    for c in cr:
        print("  -", c)
