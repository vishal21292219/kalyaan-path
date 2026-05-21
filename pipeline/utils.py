from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

_ACTIVE_NICHE = os.getenv("ACTIVE_NICHE", "bhakti")


def set_active_niche(niche: str) -> None:
    """Set the niche used by load_config() / load_topics() when no arg is passed."""
    global _ACTIVE_NICHE
    _ACTIVE_NICHE = niche
    os.environ["ACTIVE_NICHE"] = niche


def get_active_niche() -> str:
    return _ACTIVE_NICHE


def load_config(niche: str | None = None) -> dict:
    niche = niche or _ACTIVE_NICHE
    cfg_path = ROOT / "configs" / f"{niche}.yaml"
    if not cfg_path.exists():
        if niche == "bhakti":
            legacy = ROOT / "config.yaml"
            if legacy.exists():
                cfg_path = legacy
            else:
                raise FileNotFoundError(f"No config found for niche '{niche}' (tried {cfg_path} and {legacy})")
        else:
            raise FileNotFoundError(f"No config found for niche '{niche}' at {cfg_path}")
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg.setdefault("niche", niche)
    return cfg


def load_topics(niche: str | None = None) -> dict:
    niche = niche or _ACTIVE_NICHE
    cfg = load_config(niche)
    topics_file = cfg.get("paths", {}).get("topics_file", "data/topics.json")
    path = ROOT / topics_file
    if not path.exists() and niche == "bhakti":
        path = ROOT / "data" / "topics.json"
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def slugify(text: str, max_len: int = 60) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text[:max_len] or "reel"


def today_stamp() -> str:
    return datetime.now().strftime("%Y%m%d")


def out_path(*parts: str) -> Path:
    p = ROOT / "output" / Path(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
