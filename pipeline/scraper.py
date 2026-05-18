"""Scrape factual content from Wikipedia (CC-BY-SA) for grounding the LLM."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import requests

from .utils import ROOT

CACHE_DIR = ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
USER_AGENT = "BhaktiReels/1.0 (educational use; contact: gopulabs@gmail.com)"


def _cache_key(url: str) -> Path:
    return CACHE_DIR / (hashlib.md5(url.encode()).hexdigest() + ".json")


def _get_json(url: str, ttl_sec: int = 86400) -> dict | None:
    cache = _cache_key(url)
    if cache.exists() and (time.time() - cache.stat().st_mtime) < ttl_sec:
        return json.loads(cache.read_text())
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        r.raise_for_status()
        data = r.json()
        cache.write_text(json.dumps(data))
        return data
    except Exception as e:
        print(f"[scraper] fetch failed {url}: {e}")
        return None


def wiki_summary(title: str) -> dict | None:
    """Return Wikipedia summary {title, extract, thumbnail} or None."""
    if not title:
        return None
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    data = _get_json(url)
    if not data or "extract" not in data:
        return None
    return {
        "title": data.get("title"),
        "extract": data.get("extract"),
        "thumbnail": (data.get("thumbnail") or {}).get("source"),
        "url": (data.get("content_urls") or {}).get("desktop", {}).get("page"),
    }


def wiki_search(query: str, limit: int = 1) -> list[str]:
    url = (
        "https://en.wikipedia.org/w/api.php"
        f"?action=opensearch&search={requests.utils.quote(query)}&limit={limit}&format=json"
    )
    data = _get_json(url, ttl_sec=86400 * 7)
    if not data or len(data) < 2:
        return []
    return data[1]


def gather_context(topic: dict) -> str:
    """Gather a short factual context string for the LLM."""
    parts = []
    wiki_title = topic.get("wiki")
    if not wiki_title:
        hits = wiki_search(topic["title"])
        if hits:
            wiki_title = hits[0].replace(" ", "_")
    if wiki_title:
        summary = wiki_summary(wiki_title)
        if summary and summary.get("extract"):
            parts.append(summary["extract"])
    if not parts:
        parts.append(f"Topic: {topic['title']} - a sacred topic in Hindu tradition.")
    return "\n\n".join(parts)[:3500]


if __name__ == "__main__":
    print(gather_context({"title": "Lord Shiva", "wiki": "Shiva"}))
