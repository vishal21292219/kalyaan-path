import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def load_config() -> dict:
    with open(ROOT / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_topics() -> dict:
    with open(ROOT / "data" / "topics.json", "r", encoding="utf-8") as f:
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
