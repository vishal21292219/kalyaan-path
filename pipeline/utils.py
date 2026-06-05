from __future__ import annotations

import difflib
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


def _norm_line(s: str) -> str:
    """Normalise a narration line for duplicate comparison: lowercase, drop
    punctuation (ASCII + Devanagari danda), collapse whitespace."""
    s = (s or "").lower()
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)   # strip punctuation
    s = re.sub(r"[।॥]", " ", s)                          # Devanagari dandas
    return re.sub(r"\s+", " ", s).strip()


def _lines_duplicate(a: str, b: str) -> bool:
    """True when two narration lines are effectively the same sentence — exact
    after normalisation, one fully contained in the other (same opener restated),
    or ≥85% similar. Conservative so genuinely distinct lines are never merged."""
    na, nb = _norm_line(a), _norm_line(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    shorter, longer = sorted((na, nb), key=len)
    if shorter in longer and len(shorter) >= 0.6 * len(longer):
        return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= 0.85


def dedupe_script_narration(script: dict) -> dict:
    """Drop duplicate opening lines so the hook isn't narrated/captioned twice.

    The voiceover and captions are both built as [hook, *body, cta], with the
    hook spoken first and body[0] meant to CONTINUE from it. Some channel
    personas (e.g. Gods of the Mind) tell the LLM to make body[0] the same
    'reframe' opener as the hook, so the model emits the hook verbatim as
    body[0] → the first sentence is heard and shown twice.

    Remove any body line that duplicates the previous kept line (starting from
    the hook), keeping the 1:1 body_roman / visuals entries in sync. Mutates and
    returns the script. Idempotent — safe to call on already-clean scripts.
    """
    body = list(script.get("body") or [])
    if not body:
        return script

    body_roman = list(script.get("body_roman") or [])
    visuals = list(script.get("visuals") or [])
    roman_synced = len(body_roman) == len(body)
    visuals_synced = len(visuals) == len(body)

    keep: list[int] = []
    prev = script.get("hook", "")
    for i, line in enumerate(body):
        if _lines_duplicate(prev, line):
            continue                # duplicate of hook / previous kept line — drop
        keep.append(i)
        prev = line

    if len(keep) == len(body):
        return script               # nothing duplicated

    script["body"] = [body[i] for i in keep]
    if roman_synced:
        script["body_roman"] = [body_roman[i] for i in keep]
    if visuals_synced:
        script["visuals"] = [visuals[i] for i in keep]
    print(f"[dedupe] removed {len(body) - len(keep)} duplicate narration line(s) "
          f"(hook was repeated as body opener)")
    return script
