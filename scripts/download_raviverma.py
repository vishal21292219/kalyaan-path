"""Download Raja Ravi Varma paintings from Wikimedia Commons (public domain).

Each painting is searched via the Commons API, highest-resolution version
downloaded to data/library_raviverma/, and metadata recorded in manifest.json.

Source: all Ravi Varma works (1848-1906) are in the public domain in India
and worldwide (life + 60 years expired in 1966; US public domain via
pre-1923 publication).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
LIB_DIR = ROOT / "data" / "library_raviverma"
MANIFEST = LIB_DIR / "manifest.json"

# Curated list — name + searchable Commons query + deity/scene tags.
# Each entry must produce ONE clean public-domain Ravi Varma image.
PAINTINGS = [
    # ─── Krishna ────────────────────────────────────────────
    {"slug": "krishna_as_envoy",         "q": "Sri Krishna as Envoy Ravi Varma",       "deity": "krishna",  "tags": ["krishna", "mahabharat", "envoy"]},
    {"slug": "yashoda_krishna",          "q": "Yashoda Adorning Krishna Ravi Varma",   "deity": "krishna",  "tags": ["krishna", "yashoda", "child"]},
    {"slug": "radha_moonlight",          "q": "Radha in the Moonlight Ravi Varma",     "deity": "krishna",  "tags": ["krishna", "radha", "love"]},
    {"slug": "krishna_yashoda_milk",     "q": "Krishna with Yashoda Ravi Varma",       "deity": "krishna",  "tags": ["krishna", "yashoda", "milk"]},
    # ─── Rama ───────────────────────────────────────────────
    {"slug": "rama_conquers_varuna",     "q": "Lord Rama Conquers Varuna Ravi Varma",  "deity": "rama",     "tags": ["rama", "varuna", "ocean"]},
    {"slug": "rama_jatayu",              "q": "Jatayu fights Ravana Ravi Varma",       "deity": "rama",     "tags": ["jatayu", "ravana", "ramayana"]},
    {"slug": "sita_bhumi_pravesh",       "q": "Sita Bhumi Pravesh Ravi Varma",         "deity": "rama",     "tags": ["sita", "ending", "ramayana"]},
    # ─── Mahabharat ─────────────────────────────────────────
    {"slug": "draupadi_disrobing",       "q": "Disrobing of Draupadi Ravi Varma",      "deity": "general",  "tags": ["draupadi", "mahabharat", "kuru"]},
    {"slug": "draupadi_kichaka",         "q": "Draupadi Dreading Kichaka Ravi Varma",  "deity": "general",  "tags": ["draupadi", "kichaka"]},
    {"slug": "arjuna_subhadra",          "q": "Arjuna and Subhadra Ravi Varma",        "deity": "general",  "tags": ["arjuna", "subhadra", "love"]},
    {"slug": "shantanu_matsyagandha",    "q": "Shantanu and Matsyagandha Ravi Varma",  "deity": "general",  "tags": ["shantanu", "satyavati"]},
    # ─── Shakuntala ────────────────────────────────────────
    {"slug": "shakuntala",               "q": "Shakuntala Ravi Varma",                 "deity": "general",  "tags": ["shakuntala", "kalidasa"]},
    {"slug": "shakuntala_patralekhan",   "q": "Shakuntala Patra-lekhan Ravi Varma",    "deity": "general",  "tags": ["shakuntala", "letter"]},
    # ─── Damayanti ─────────────────────────────────────────
    {"slug": "hamsa_damayanti",          "q": "Hamsa Damayanti Ravi Varma",            "deity": "general",  "tags": ["damayanti", "swan", "nala"]},
    {"slug": "damayanti_swan",           "q": "Damayanti Talking to Swan Ravi Varma",  "deity": "general",  "tags": ["damayanti", "swan"]},
    # ─── Devi / Lakshmi / Saraswati ────────────────────────
    {"slug": "saraswati",                "q": "Saraswati Ravi Varma",                  "deity": "saraswati","tags": ["saraswati", "veena", "vidya"]},
    {"slug": "lakshmi",                  "q": "Goddess Lakshmi Ravi Varma",            "deity": "lakshmi",  "tags": ["lakshmi", "lotus", "dhan"]},
    {"slug": "descent_of_ganga",         "q": "Descent of Ganga Ravi Varma",           "deity": "shiva",    "tags": ["ganga", "shiva", "descent"]},
    {"slug": "mohini",                   "q": "Mohini Ravi Varma",                     "deity": "vishnu",   "tags": ["mohini", "vishnu", "avatar"]},
    # ─── Shanmukha / Subramanya ────────────────────────────
    {"slug": "shanmukha",                "q": "Sri Shanmukha Subramania Swami Ravi Varma", "deity": "kartikeya", "tags": ["kartikeya", "murugan"]},
    # ─── Indrajit / Meghnad ────────────────────────────────
    {"slug": "victory_of_indrajit",      "q": "Victory of Indrajit Ravi Varma",        "deity": "general",  "tags": ["indrajit", "meghnad", "ramayana"]},
    {"slug": "victory_of_meghanada",     "q": "Victory of Meghanada Ravi Varma",       "deity": "general",  "tags": ["meghnad", "indrajit"]},
    # ─── Sage / Rishi ──────────────────────────────────────
    {"slug": "girl_kanwa_hermitage",     "q": "Girl in Sage Kanwa Hermitage Ravi Varma", "deity": "general", "tags": ["rishi", "ashram"]},
    {"slug": "shakuntala_dushyanta",     "q": "Shakuntala looking for Dushyanta Ravi Varma", "deity": "general", "tags": ["shakuntala", "search"]},
    # ─── Cultural ──────────────────────────────────────────
    {"slug": "galaxy_of_musicians",      "q": "Galaxy of Musicians Ravi Varma",        "deity": "general",  "tags": ["music", "women", "culture"]},
    {"slug": "nair_lady_hair",           "q": "Nair Lady Adorning Her Hair Ravi Varma","deity": "general",  "tags": ["nair", "kerala", "woman"]},
    {"slug": "malabar_lady",             "q": "Malabar Lady Ravi Varma",               "deity": "general",  "tags": ["malabar", "kerala"]},
    {"slug": "woman_holding_fruit",      "q": "Woman Holding a Fruit Ravi Varma",      "deity": "general",  "tags": ["lady", "kerala"]},
    {"slug": "nair_woman",               "q": "Nair Woman Ravi Varma",                 "deity": "general",  "tags": ["nair", "woman"]},
    # ─── Extra Devi forms ──────────────────────────────────
    {"slug": "mohini_ball",              "q": "Mohini playing with ball Ravi Varma",   "deity": "vishnu",   "tags": ["mohini", "vishnu"]},
]


API = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": "bhakti-reels-library/1.0 (vishal@gopulabs)"}


def _get_with_backoff(params: dict, attempts: int = 5) -> dict:
    """GET with exponential backoff on 429 + 5xx."""
    for i in range(attempts):
        r = requests.get(API, params=params, headers=HEADERS, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 502, 503, 504):
            wait = 5 * (2 ** i)
            print(f"  ↻ HTTP {r.status_code}, backing off {wait}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
    raise RuntimeError(f"API failed after {attempts} attempts")


def search_image(query: str) -> dict | None:
    """Search Commons for the painting, return best file metadata."""
    # 1. Search in File: namespace
    data = _get_with_backoff({
        "action": "query",
        "format": "json",
        "list": "search",
        "srnamespace": 6,
        "srlimit": 5,
        "srsearch": query,
    })
    hits = data.get("query", {}).get("search", [])
    if not hits:
        return None
    # Prefer jpg over svg/png
    titles = [h["title"] for h in hits if h["title"].lower().endswith((".jpg", ".jpeg"))]
    if not titles:
        titles = [hits[0]["title"]]
    title = titles[0]

    # 2. Get image info (url + size) for the chosen file
    data = _get_with_backoff({
        "action": "query",
        "format": "json",
        "prop": "imageinfo",
        "iiprop": "url|size|mime",
        "iiurlwidth": 2048,
        "titles": title,
    })
    pages = data.get("query", {}).get("pages", {})
    page = next(iter(pages.values()))
    info = (page.get("imageinfo") or [{}])[0]
    if not info.get("thumburl") and not info.get("url"):
        return None
    return {
        "title": title,
        "url": info.get("thumburl") or info["url"],  # thumburl is the resized 2048-wide
        "width": info.get("thumbwidth") or info.get("width"),
        "height": info.get("thumbheight") or info.get("height"),
        "source_url": info.get("descriptionurl"),
    }


def download(url: str, out_path: Path) -> bool:
    try:
        r = requests.get(url, headers=HEADERS, timeout=120)
        if r.status_code != 200 or len(r.content) < 5000:
            return False
        out_path.write_bytes(r.content)
        return True
    except Exception as e:
        print(f"  ✗ download error: {e}")
        return False


def main():
    LIB_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    if MANIFEST.exists():
        manifest = json.loads(MANIFEST.read_text())
    done_slugs = {m["slug"] for m in manifest}

    for i, p in enumerate(PAINTINGS, 1):
        if p["slug"] in done_slugs:
            print(f"[{i:2d}/{len(PAINTINGS)}] {p['slug']} → already in manifest, skipping")
            continue
        print(f"[{i:2d}/{len(PAINTINGS)}] searching: {p['q']}")
        info = search_image(p["q"])
        if not info:
            print(f"  ✗ no hits for '{p['q']}'")
            continue
        print(f"  ✓ {info['title']}  ({info.get('width')}x{info.get('height')})")
        out_path = LIB_DIR / f"{p['slug']}.jpg"
        if not download(info["url"], out_path):
            print(f"  ✗ download failed")
            continue
        size_kb = out_path.stat().st_size / 1024
        print(f"  ✓ saved {size_kb:.0f} KB → {out_path.name}")
        manifest.append({
            "slug": p["slug"],
            "file": str(out_path.relative_to(ROOT)),
            "wiki_title": info["title"],
            "wiki_source": info.get("source_url"),
            "deity": p["deity"],
            "tags": p["tags"],
            "width": info.get("width"),
            "height": info.get("height"),
            "size_kb": round(size_kb),
        })
        MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        time.sleep(2.0)  # be nice to Wikimedia (avoids 429s)

    print(f"\n=== DONE ===")
    print(f"Manifest entries: {len(manifest)}")
    print(f"Library: {LIB_DIR}")
    print(f"Manifest: {MANIFEST}")


if __name__ == "__main__":
    sys.exit(main())
