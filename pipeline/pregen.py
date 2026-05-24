"""Pre-generate scripts + images + thumbnails for scheduled future slots.

Runs nightly during Gemini's quiet window (21:00 UTC = 02:30 IST).
Each call to pregen_slot(niche, kind, date, seed) produces a self-contained
folder under data/pregenerated/{niche}/{YYYYMMDD}_{kind}_s{seed}/ containing:
  - script.json
  - images/img_00.jpg ... img_NN.jpg (gen extra buffer, use best N)
  - thumbnail.jpg
  - meta.json (topic, generated_at)

At publish time, run.py checks scheduler.get_scheduled() and if a pregen
dir exists, skips script/images/thumbnail steps and uses cached assets.
"""
from __future__ import annotations

import json
import shutil
import time
import traceback
from datetime import date as date_t, datetime
from pathlib import Path

from . import scheduler
from .image_gen import generate_images, GeminiUnavailable
from .scraper import gather_context
from .script_writer import write_script
from .thumbnail_gen import make_thumbnail
from .utils import ROOT, set_active_niche, slugify

PREGEN_ROOT = ROOT / "data" / "pregenerated"
PREGEN_ROOT.mkdir(parents=True, exist_ok=True)


def _pregen_dir_for(niche: str, kind: str, target_date: date_t, seed_offset: int) -> Path:
    return PREGEN_ROOT / niche / f"{target_date.strftime('%Y%m%d')}_{kind}_s{seed_offset}"


def is_pregen_ready(niche: str, kind: str, target_date: date_t, seed_offset: int = 0) -> Path | None:
    """Return pregen dir Path if a complete pregen exists, else None."""
    d = _pregen_dir_for(niche, kind, target_date, seed_offset)
    if not d.exists():
        return None
    script = d / "script.json"
    imgs = list((d / "images").glob("img_*.jpg")) if (d / "images").exists() else []
    if script.exists() and len(imgs) >= 5:  # need at least 5 images to be usable
        return d
    return None


def load_pregen(pregen_dir: Path) -> dict:
    """Load script + image paths + thumb from a pregen dir."""
    return {
        "script": json.loads((pregen_dir / "script.json").read_text()),
        "images": sorted((pregen_dir / "images").glob("img_*.jpg")),
        "thumbnail": (pregen_dir / "thumbnail.jpg") if (pregen_dir / "thumbnail.jpg").exists() else None,
        "meta": json.loads((pregen_dir / "meta.json").read_text()) if (pregen_dir / "meta.json").exists() else {},
    }


def pregen_slot(niche: str, kind: str, target_date: date_t, seed_offset: int = 0,
                extra_image_buffer: int = 3, force: bool = False) -> dict:
    """Generate full pregen bundle for one slot. Idempotent: skips if already done.

    Returns:
        dict with status ("ready" | "skipped" | "failed") + details
    """
    set_active_niche(niche)
    pregen_dir = _pregen_dir_for(niche, kind, target_date, seed_offset)

    # Skip if already complete (unless forced)
    if not force and is_pregen_ready(niche, kind, target_date, seed_offset):
        return {"status": "skipped", "reason": "already-ready", "dir": str(pregen_dir)}

    # Step 1: Reserve topic via scheduler (idempotent)
    days_ahead = (target_date - date_t.today()).days
    topic = scheduler.schedule_for(niche, kind, target_date, seed_offset, days_ahead=days_ahead)
    print(f"  [pregen] {niche}/{kind} {target_date} s{seed_offset} → {topic.get('title')}", flush=True)

    pregen_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Step 2: Script
        context = gather_context(topic)
        script = write_script(topic, context, long_form=False)
        # Attach topic metadata for downstream stages
        for key in ("kind", "episode_number", "ref", "verse", "theme"):
            if key in topic and key not in script:
                script[key] = topic[key]
        (pregen_dir / "script.json").write_text(json.dumps(script, indent=2, ensure_ascii=False))

        # Step 3: Images (with extra buffer)
        visuals = script.get("visuals", [])
        if extra_image_buffer > 0:
            # Pad visuals list by repeating the last few prompts (gives Gemini fallback options)
            extras = visuals[-extra_image_buffer:] if visuals else []
            visuals_to_gen = visuals + extras
        else:
            visuals_to_gen = visuals

        img_dir = pregen_dir / "images"
        img_dir.mkdir(exist_ok=True)
        try:
            images = generate_images(visuals_to_gen, img_dir)
            print(f"  [pregen] ✓ {len(images)} images saved", flush=True)
        except GeminiUnavailable as e:
            print(f"  [pregen] ⚠ image gen partial fail: {e}", flush=True)
            images = sorted(img_dir.glob("img_*.jpg"))
            if len(images) < 5:
                raise

        # Step 4: Thumbnail
        try:
            thumb_path = pregen_dir / "thumbnail.jpg"
            make_thumbnail(script, niche, thumb_path)
            print(f"  [pregen] ✓ thumbnail saved", flush=True)
        except Exception:
            traceback.print_exc()
            print(f"  [pregen] ⚠ thumbnail failed — continuing without", flush=True)

        # Step 5: Save meta + update scheduler status
        meta = {
            "niche": niche,
            "kind": kind,
            "target_date": target_date.isoformat(),
            "seed_offset": seed_offset,
            "topic": topic,
            "images_count": len(images),
            "has_thumbnail": (pregen_dir / "thumbnail.jpg").exists(),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
        (pregen_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        scheduler.update_status(niche, kind, target_date, seed_offset, "generated", pregen_dir)

        return {
            "status": "ready",
            "dir": str(pregen_dir),
            "topic": topic.get("title"),
            "images": len(images),
            "has_thumbnail": (pregen_dir / "thumbnail.jpg").exists(),
        }

    except Exception as e:
        traceback.print_exc()
        return {"status": "failed", "dir": str(pregen_dir), "error": str(e)}


def pregen_all_pending(days_ahead: int = 5, sleep_between: int = 5) -> dict:
    """Generate for all pending slots in next N days. Returns summary."""
    pending = scheduler.list_pending(days_ahead)
    print(f"[pregen] {len(pending)} pending slots in next {days_ahead} days", flush=True)
    if not pending:
        return {"total": 0, "ready": 0, "failed": 0, "skipped": 0, "details": []}

    results = []
    counts = {"ready": 0, "failed": 0, "skipped": 0}
    for i, slot in enumerate(pending, 1):
        print(f"\n[pregen] [{i}/{len(pending)}] {slot['label']} → {slot['date']}", flush=True)
        try:
            r = pregen_slot(slot["niche"], slot["kind"], slot["date"], slot["seed"])
        except Exception as e:
            traceback.print_exc()
            r = {"status": "failed", "error": str(e)}
        results.append({**slot, **r})
        counts[r.get("status", "failed")] = counts.get(r.get("status", "failed"), 0) + 1
        if i < len(pending):
            time.sleep(sleep_between)  # be polite to Gemini

    summary = {"total": len(pending), **counts, "details": results}
    return summary


def cleanup_consumed(older_than_days: int = 7) -> int:
    """Delete pregen dirs for slots marked consumed or older than threshold."""
    removed = scheduler.cleanup(older_than_days)
    # Also sweep any orphan pregen dirs not in schedule
    orphan = 0
    for niche_dir in PREGEN_ROOT.iterdir():
        if not niche_dir.is_dir():
            continue
        for slot_dir in niche_dir.iterdir():
            if not slot_dir.is_dir():
                continue
            try:
                date_str = slot_dir.name.split("_")[0]
                d = date_t(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
            except (ValueError, IndexError):
                continue
            if (date_t.today() - d).days > older_than_days:
                shutil.rmtree(slot_dir, ignore_errors=True)
                orphan += 1
    return removed + orphan


if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    summary = pregen_all_pending(days)
    print(f"\n=== PREGEN SUMMARY ===")
    print(f"total={summary['total']} ready={summary['ready']} skipped={summary['skipped']} failed={summary['failed']}")
