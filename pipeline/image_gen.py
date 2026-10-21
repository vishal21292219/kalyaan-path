"""Image generation — multi-provider chain.

Primary:  fal.ai FLUX 1.1-pro (PAID ~$0.04/img, anatomy-correct, premium quality)
Fallback: HuggingFace FLUX schnell (FREE, anatomy issues but reliable)
Last:     Gemini Nano Banana (FREE, often quota-banned)

If ALL fail after retries → raise GeminiUnavailable so run.py can record
the failure in retry_queue.json and exit cleanly. Hourly retry cron retries.
"""
from __future__ import annotations

import base64
import os
import re
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from .utils import ROOT, load_config, slugify

load_dotenv(override=True)

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
HF_ROUTER_BASE = "https://router.huggingface.co/hf-inference/models"
HF_DEFAULT_MODEL = "black-forest-labs/FLUX.1-schnell"
FAL_FLUX_PRO = "fal-ai/flux-pro/v1.1"
MAX_RETRIES = 5
RETRY_SPACING_SEC = 30


def _generate_fal_flux(prompt: str, out_path: Path,
                       model: str = FAL_FLUX_PRO,
                       target_w: int = 1080, target_h: int = 1920,
                       seed: int | None = None) -> bool:
    """Generate image via fal.ai FLUX 1.1-pro. PRIMARY (paid, premium quality).
    Returns True on success, False on failure (caller falls back to HF).

    seed: when set, locks the diffusion seed so the same character/appearance
    prompt renders a consistent face across scenes (character-bible feature)."""
    key = os.getenv("FAL_KEY")
    if not key:
        print("[image_gen][fal] FAL_KEY missing, skipping fal provider")
        return False
    try:
        import fal_client
    except ImportError:
        print("[image_gen][fal] fal_client not installed — pip install fal-client")
        return False
    # fal_client uses FAL_KEY env automatically
    # Pick closest supported aspect: portrait 9:16 vs landscape 16:9
    is_portrait = target_h > target_w
    image_size = "portrait_16_9" if is_portrait else "landscape_16_9"
    # schnell is a few-step distilled model (max 12 steps); pro/dev want ~28.
    steps = 8 if "schnell" in str(model).lower() else 28
    # Endpoint schemas differ (checked 2026-10-21). flux-pro/v1.1 accepts NONE of
    # num_inference_steps / guidance_scale / enable_safety_checker — they were
    # being sent and silently ignored, so "we set guidance to 3.5" was never true
    # on the premium model. dev/schnell do take them; schnell is guidance- AND
    # timestep-distilled, so its guidance value is inert and steps cap at 12.
    arguments = {
        "prompt": prompt,
        "image_size": image_size,
        "num_images": 1,
        "output_format": "jpeg",
    }
    m = str(model).lower()
    if "flux-pro" in m:
        arguments["safety_tolerance"] = "2"
    else:
        arguments["num_inference_steps"] = min(steps, 12) if "schnell" in m else steps
        arguments["enable_safety_checker"] = True
        if "schnell" not in m:
            # 4.0 sits in the band that helps attribute fidelity without the
            # plastic over-contrast that shows up past ~6.
            arguments["guidance_scale"] = 4.0
    if seed is not None:
        arguments["seed"] = int(seed)
    try:
        result = fal_client.subscribe(
            model,
            arguments=arguments,
            with_logs=False,
        )
        url = result.get("images", [{}])[0].get("url")
        if not url:
            print(f"[image_gen][fal] no image url in response: {result}")
            return False
        r = requests.get(url, timeout=60)
        if r.status_code == 200 and len(r.content) > 5000:
            out_path.write_bytes(r.content)
            return True
        print(f"[image_gen][fal] download failed: HTTP {r.status_code}, {len(r.content)}B")
        return False
    except Exception as e:
        print(f"[image_gen][fal] error: {type(e).__name__}: {e}")
        return False


class GeminiUnavailable(RuntimeError):
    """Raised when all image providers fail after retries.
    Name kept for backward compat with run.py's catch logic."""


def is_blank(path: Path) -> bool:
    """True if the file is an effectively empty frame.

    2026-10-21: img_05 of a live GoM reel was a 34KB solid-black JPEG (every
    other scene was ~450KB) and it shipped into the finished video as a black
    frame at 00:34. fal's premium endpoint does NOT raise when its safety
    checker fires — it answers HTTP 200 with a black image — so every provider
    in the chain reported success. Silent success on a failed step is this
    project's most expensive bug class; every frame is now checked.

    NOTE scope: this is the ONLY image_gen change from that investigation. The
    bearded-Shiva problem found in the same session is NOT fixed here — three
    prompt-level fixes were tried against flux-pro and each either failed or
    regressed the art style into photoreal cosplay, so the master path is left
    exactly as it was rather than shipping a fourth guess. See the session note
    in configs/godmind.yaml (images.deity_blocks)."""
    try:
        from PIL import Image, ImageStat
        st = ImageStat.Stat(Image.open(path).convert("L"))
        return st.stddev[0] < 10 or st.mean[0] < 12
    except Exception:
        return True


def _generate_hf_flux(prompt: str, out_path: Path, model: str = HF_DEFAULT_MODEL,
                      max_retries: int = 3) -> bool:
    """Generate image via HuggingFace FLUX schnell.
    Returns True on success, False on failure (caller handles fallback)."""
    token = os.getenv("HUGGINGFACE_TOKEN")
    if not token:
        print("[image_gen][hf] HUGGINGFACE_TOKEN missing, skipping HF provider")
        return False
    url = f"{HF_ROUTER_BASE}/{model}"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"inputs": prompt}
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=90)
            ctype = r.headers.get("content-type", "")
            if r.status_code == 200 and "image" in ctype:
                out_path.write_bytes(r.content)
                if out_path.stat().st_size > 5000:
                    return True
                print(f"[image_gen][hf] attempt {attempt}: tiny image ({out_path.stat().st_size}B)")
            elif r.status_code == 503:
                # Model cold-starting — wait + retry
                msg = r.text[:200] if r.text else "503 model loading"
                print(f"[image_gen][hf] attempt {attempt}: {msg}")
                time.sleep(20)  # cold start usually ~20-40s
            elif r.status_code == 429:
                # Rate limited — back off
                print(f"[image_gen][hf] attempt {attempt}: 429 rate-limited, backing off")
                time.sleep(25)
            else:
                print(f"[image_gen][hf] attempt {attempt}: HTTP {r.status_code} {r.text[:150]}")
                if attempt < max_retries:
                    time.sleep(5)
        except Exception as e:
            print(f"[image_gen][hf] attempt {attempt}: {e}")
            if attempt < max_retries:
                time.sleep(5)
    return False


def _generate_gemini(prompt: str, out_path: Path, model: str) -> bool:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise GeminiUnavailable("GEMINI_API_KEY missing in .env")

    url = f"{GEMINI_BASE}/{model}:generateContent?key={api_key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
    }
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.post(url, json=body, timeout=180)
            if r.status_code == 200:
                data = r.json()
                for part in data["candidates"][0]["content"]["parts"]:
                    if "inlineData" in part:
                        out_path.write_bytes(base64.b64decode(part["inlineData"]["data"]))
                        if out_path.stat().st_size > 5000:
                            return True
                last_err = "no inlineData in response"
                print(f"[image_gen][gemini] attempt {attempt}: {last_err}")
            elif r.status_code == 503:
                last_err = "503 UNAVAILABLE (Google high demand)"
                print(f"[image_gen][gemini] attempt {attempt}: {last_err}")
            else:
                last_err = f"HTTP {r.status_code} — {r.text[:200]}"
                print(f"[image_gen][gemini] attempt {attempt}: {last_err}")
        except Exception as e:
            last_err = str(e)
            print(f"[image_gen][gemini] attempt {attempt}: {e}")
        if attempt < MAX_RETRIES:
            time.sleep(RETRY_SPACING_SEC)
    raise GeminiUnavailable(f"Gemini failed after {MAX_RETRIES} retries: {last_err}")


# ─────────────────────────────────────────────────────────────────────────
# CHARACTER CONSISTENCY (Level 2 — reference conditioning)
#
# Each scene image is normally an independent FLUX generation, so a recurring
# deity's face/design drifts across scenes within ONE video. The fix that
# actually works (used by strong AI-reel creators): generate ONE master
# portrait per recurring character, then render every scene that features that
# character via nano-banana-2/edit, passing the master(s) as reference images
# so the SAME identity is reused — only the pose/action/background change.
#
# Driven by the script's "character_bible": a list of recurring characters,
# each { "name": "...", "aliases": [...], "look": "..." }. A scene is
# reference-conditioned off whichever bible characters are named in its prompt.
# Multi-character scenes pass MULTIPLE references (nano-banana keeps each one).
# Scenes with no recurring character fall back to plain FLUX (establishing
# shots, crowds, landscapes) so they are never corrupted by a wrong reference.
# ─────────────────────────────────────────────────────────────────────────

_HAIR_CLAUSE = re.compile(
    r"[^,.;—]*\b(beard|bearded|moustache|mustache|stubble|clean-shaven|cleanshaven|"
    r"facial hair|goatee)\b[^,.;—]*", re.I)


def _strip_facial_hair(look: str) -> str:
    """Remove every facial-hair claim from an LLM-written `look`.

    The deity_blocks in config are sourced and tested and already state the jaw
    correctly; `look` is regenerated every run and cannot be trusted with it.
    script_writer's template used to SHOW Shiva "with a neat beard", and told the
    writer Shiva is one of the bearded deities -- which is wrong, and is what
    actually produced the bearded master portraits chased through prompts,
    references and models for a whole session. That template is fixed now, but
    the writer is an LLM and will drift back, so where a block exists its wording
    wins and the look's version is removed before it can contradict it."""
    out = _HAIR_CLAUSE.sub("", look or "")
    out = re.sub(r"\s*,\s*,", ",", out)
    return re.sub(r"\s{2,}", " ", out).strip(" ,;—") or (look or "")


def _detect_cast(prompt: str, bible: list[dict]) -> list[dict]:
    """Return bible characters whose name/alias appears in the scene prompt."""
    low = prompt.lower()
    hits = []
    for ch in bible:
        name = (ch.get("name") or "").strip()
        if not name:
            continue
        tokens = [name] + list(ch.get("aliases") or [])
        if any(t and t.lower() in low for t in tokens):
            hits.append(ch)
    return hits


def _build_character_masters(bible: list[dict], out_dir: Path, style: str,
                             negative: str, target_w: int, target_h: int,
                             fal_model: str = FAL_FLUX_PRO) -> dict[str, str]:
    """Generate (once, cached on disk) a master portrait per recurring character
    and upload it to fal. Returns {character_name: fal_url}. Masters use the
    SAME style_suffix as scenes so the reference matches the video's art style."""
    from .char_consistent import _fal_upload
    masters: dict[str, str] = {}
    for ch in bible:
        name = (ch.get("name") or "").strip()
        look = (ch.get("look") or "").strip()
        if not name or not look:
            continue
        mp = out_dir / f"master_{slugify(name)}.jpg"

        # PINNED REFERENCE. A hand-checked frame in assets/refs/<deity>.jpg wins
        # over anything we can generate. Added 2026-10-21 after the master for
        # Shiva came back bearded on every prompt form tried (negation stripped,
        # block alone, bare-jaw sentence leading) and that beard then propagated
        # into every reference-conditioned scene of a live reel. Prompt wording
        # was the wrong tool. Each pinned file was produced by generating for
        # canon and then EDITING the one wrong attribute (nano-banana-2/edit),
        # so it carries correct iconography AND the channel's art style.
        # To pin a deity: drop a verified frame at assets/refs/<lowercase>.jpg.
        pinned = ROOT / "assets/refs" / f"{slugify(name)}.jpg"
        if pinned.exists():
            url = _fal_upload(str(pinned))
            if url:
                masters[name] = url
                print(f"[consistency] master ← PINNED assets/refs/{pinned.name} → {name}")
                continue
            print(f"[consistency] pinned ref upload failed for {name} — generating instead")

        if not mp.exists():
            # The master portrait defines the deity for every scene that
            # references it, so it gets the same one-deity treatment.
            _icfg = load_config()          # cfg is not in this function's scope
            _blk = _deity_block(look, _icfg)
            _tail = ((_icfg.get("images", {}) or {}).get("style_tail") or "").strip() if _blk else style
            # Where a sourced deity block exists it OWNS the iconography, so any
            # facial-hair claim the writer put in `look` is removed before it can
            # contradict the block. See _strip_facial_hair.
            _look = _strip_facial_hair(look) if _blk else look
            prompt = (
                f"Full-body single-character reference portrait of {_look}. "
                f"{_blk} "
                f"Centered frontal hero pose, clean plain simple background, "
                f"dramatic divine lighting, intricate detail, masterpiece{_tail}."
            )
            # The master is the HIGHEST-LEVERAGE frame in the whole render: every
            # reference-conditioned scene inherits its face. Measured on a real
            # Indra reel 2026-10-21 — the master came back bearded and all EIGHT
            # conditioned scenes carried that beard into the finished video, while
            # the per-scene gate only ever saw the four plain-FLUX frames. So the
            # master is gated here, and hard: regenerate until it passes.
            ok_master = False
            for attempt in range(3):
                if not _generate_fal_flux(prompt, mp, model=fal_model,
                                          target_w=target_w, target_h=target_h):
                    continue
                if is_blank(mp):
                    print(f"[consistency] master {name}: blank frame — retrying")
                    continue
                if not (load_config().get("images", {}) or {}).get("frame_check"):
                    ok_master = True
                    break
                from .frame_check import check as _fc
                good, why = _fc(mp, slugify(name), f"a reference portrait of {name}")
                if good:
                    ok_master = True
                    break
                print(f"[consistency] master {name} attempt {attempt+1}: "
                      f"FRAME CHECK FAILED — {'; '.join(why)}")
            if not ok_master:
                FRAME_ISSUES.append(f"master {name}: never passed the frame check")
                print(f"[consistency] master FAILED for {name} — scenes will use plain FLUX")
                try:
                    mp.unlink()
                except Exception:
                    pass
                continue
        url = _fal_upload(mp)
        if url:
            masters[name] = url
            print(f"[consistency] master ready → {name}")
    return masters


def generate_images(visual_prompts: list[str], out_dir: Path,
                    long_form: bool = False,
                    seeds: list[int | None] | None = None,
                    character_bible: list[dict] | None = None) -> list[Path]:
    """Generate scene images. For long-form (documentary), output 1920x1080
    horizontal. For Shorts, output 1080x1920 vertical (existing default).
    Post-processes each image to enforce target aspect (Gemini doesn't always
    honor the prompt orientation).

    seeds: optional per-image diffusion seeds (same length as visual_prompts).
    A scene featuring a recurring character should reuse that character's
    locked seed so the face stays consistent across scenes (character bible).
    Only the fal provider honors the seed; HF/Gemini fallbacks ignore it.
    """
    from PIL import Image
    cfg = load_config()
    style = cfg["images"]["style_suffix"]
    negative = cfg["images"]["negative"]
    cfg_model = cfg["images"].get("model", "gemini-3.1-flash-image-preview")
    # The fal model (e.g. fal-ai/flux/schnell) used for BULK scene images. Falls
    # back to flux-pro default.
    fal_model = cfg_model if str(cfg_model).startswith("fal-ai/") else FAL_FLUX_PRO
    # Cost-smart quality: the master portrait defines the deity FACE that the
    # consistency mechanism propagates to every hero scene. Render the master with
    # a STRONGER model (images.master_model, e.g. fal-ai/flux/dev) while keeping
    # bulk scenes on the cheap base model. Defaults to the base model if unset.
    _mm = cfg["images"].get("master_model")
    master_model = _mm if (_mm and str(_mm).startswith("fal-ai/")) else fal_model
    # The Gemini last-resort needs a real Gemini image model — never the fal id.
    gemini_model = cfg["images"].get("gemini_image_model", "gemini-3.1-flash-image-preview")
    model = gemini_model if (str(cfg_model).startswith("fal-ai/") or "flux" in str(cfg_model).lower()) else cfg_model
    # Provider gate: only attempt the PAID fal.ai stack when images.provider == "fal".
    # Set provider to "huggingface" (free stack) to skip fal entirely — no wasted
    # failing calls, no character-master/nano-banana cost. Flip back to "fal" when
    # the fal balance is recharged.
    use_fal = str(cfg["images"].get("provider", "fal")).lower() == "fal"

    if long_form:
        # Override the cfg-supplied vertical hint with landscape orientation
        # Replace common vertical-orientation phrases in style suffix
        style_fixed = style
        for vert_phrase in ["vertical 9:16 portrait composition", "vertical 9:16 portrait",
                            "9:16 portrait", "vertical portrait", "(1080x1920)"]:
            style_fixed = style_fixed.replace(vert_phrase, "")
        orientation_hint = (
            " HORIZONTAL 16:9 LANDSCAPE composition (1920x1080), cinematic widescreen "
            "documentary frame, subject occupies left or center with environmental depth, "
            "wide establishing shot perspective."
        )
        style = style_fixed + orientation_hint
        target_w, target_h = 1920, 1080
        print(f"[image_gen] LONG-FORM mode → 1920x1080 horizontal landscape")
    else:
        target_w, target_h = 1080, 1920

    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[Path] = []
    fal_succeeded = 0
    hf_succeeded = 0
    gemini_succeeded = 0
    ref_succeeded = 0
    last_error = None

    # ── Character consistency: build a master portrait per recurring character.
    # Gated by config (images.consistency, default ON) + a usable bible. Skipped
    # for long-form (horizontal documentary) where recurring deities are rare.
    masters: dict[str, str] = {}
    bible = character_bible or []
    # Defaults FALSE: deleting the key from config should turn a paid feature OFF,
    # not silently leave it on. Same reasoning as video.hero_motion below.
    consistency_on = bool(cfg["images"].get("consistency", False)) and not long_form and bible and use_fal
    # Cost guard: only the most impactful scenes are reference-conditioned (each
    # costs a nano-banana edit). Default 3 hero shots/video — ~80% of the visual
    # consistency benefit at a fraction of the cost. 0 = unlimited.
    max_ref = int(cfg["images"].get("consistency_max_scenes", 3))
    ref_used = 0
    if consistency_on:
        masters = _build_character_masters(bible, out_dir, style, negative, target_w, target_h, fal_model=master_model)
        if masters:
            cap = f"first {max_ref}" if max_ref else "all"
            print(f"[consistency] {len(masters)} character master(s) — reference-conditioning {cap} recurring scene(s)")

    # ── HERO first image: scene 0 is the 3-sec retention hook AND the FB reel
    # cover. With Kling hero-motion OFF, this STILL frame must carry the "wow" —
    # render it with a PREMIUM model + a cinematic quality boost (~$0.025 vs the
    # old $1.4-2.8 Kling clip). Tunable via images.hero_model (default flux/dev,
    # 28-step) — a big jump over the 4-step schnell used for bulk scenes.
    HERO_BOOST = (", cinematic hero shot, dramatic volumetric lighting, ultra-detailed, "
                  "razor-sharp focus, striking eye-catching composition, rich depth "
                  "and atmosphere, premium quality")
    _hm = cfg["images"].get("hero_model")
    hero_model = _hm if (_hm and str(_hm).startswith("fal-ai/")) else "fal-ai/flux/dev"
    # Premium the OPENING the viewer judges (not just frame 0): the first
    # `hero_scenes` scenes render at hero quality. Default 2 (~first 8-12s + the FB
    # cover). Cost ~$0.05/video — still trivial vs the removed Kling clip.
    hero_scenes = max(1, int(cfg["images"].get("hero_scenes", 2)))

    # Enforce DARSHAN before anything else: a scene with no deity in it cannot be
    # fixed by regenerating it, so the prompt itself is re-staged. See _force_deity.
    _forced = _force_deity(list(visual_prompts), cfg)
    _nf = sum(1 for a, b in zip(visual_prompts, _forced) if a != b)
    if _nf:
        print(f"[image_gen] re-staged {_nf}/{len(_forced)} deity-less scenes around the deity")
    visual_prompts = _forced

    for i, _vp in enumerate(visual_prompts):
        # Enforce the "no text in frame" rule the writer keeps breaking.
        raw_prompt = _strip_text_requests(_vp)
        if raw_prompt != _vp:
            print(f"[image_gen] img {i}: stripped a text-rendering request from the scene")
        is_hero = (i < hero_scenes)   # opening scenes = retention hook + FB cover → premium
        boost = HERO_BOOST if is_hero else ""
        # No "Avoid: ..." tail: FLUX has no negative channel, so appending the
        # ban list was DESCRIBING the banned things (same-seed test: it produced
        # the four arms it was meant to prevent). images.negative stays in
        # config, unused here, for a model that has one (qwen-image).
        # With deity_blocks configured, one deity's marks + a short style tail
        # replace the six-deity style_suffix — see _deity_block.
        block = _deity_block(raw_prompt, cfg)
        if block:
            tail = (cfg["images"].get("style_tail") or "").strip()
            prompt = f"{raw_prompt}. {block}{tail}{boost}"
        else:
            prompt = f"{raw_prompt}{style}{boost}"
        path = out_dir / f"img_{i:02d}.jpg"
        seed = seeds[i] if seeds and i < len(seeds) else None

        # Reference-conditioning path: if this scene names recurring character(s)
        # we have a master for, render it via nano-banana/edit off those master(s)
        # so the identity stays locked. Falls through to FLUX on any failure.
        if masters and (max_ref == 0 or ref_used < max_ref):
            cast = _detect_cast(raw_prompt, bible)
            ref_urls = [masters[c["name"]] for c in cast if c.get("name") in masters]
            if ref_urls:
                from .char_consistent import generate_scene_with_reference
                names = " and ".join(c["name"] for c in cast if c.get("name") in masters)
                if generate_scene_with_reference(
                    ref_urls, raw_prompt + boost, path,
                    char_name=names, art_style=style.lstrip(", ").strip(),
                    target_w=target_w, target_h=target_h,
                ):
                    # Gate the conditioned frame too. This path used to
                    # `continue` straight past the vision check below, so on a
                    # real render 8 of 12 frames were never looked at — the whole
                    # point of the gate, missed by where it was wired.
                    _d = _deity_name(raw_prompt, cfg)
                    if (cfg.get("images", {}) or {}).get("frame_check"):
                        from .frame_check import check as _fc
                        _good, _why = _fc(path, _d, raw_prompt)
                        if not _good:
                            FRAME_ISSUES.append(f"img {i} (ref): {'; '.join(_why)}")
                            print(f"[image_gen] img {i}: FRAME CHECK FAILED on the "
                                  f"reference path — {'; '.join(_why)}")
                    ref_succeeded += 1
                    ref_used += 1
                    results.append(path)
                    continue
                print(f"[consistency] img {i}: reference edit failed → plain FLUX fallback")

        # Provider chain: fal.ai FLUX 1.1-pro (paid premium) → HF FLUX schnell (free) → Gemini (free)
        ok = False
        if use_fal and _generate_fal_flux(prompt, path, model=(hero_model if is_hero else fal_model), target_w=target_w, target_h=target_h, seed=seed) and not is_blank(path):
            ok = True
            fal_succeeded += 1
        elif _generate_hf_flux(prompt, path):
            print(f"[image_gen] img {i}: HF FLUX schnell succeeded")
            ok = True
            hf_succeeded += 1
        else:
            print(f"[image_gen] img {i}: fal + HF failed, trying Gemini last-resort...")
            try:
                if _generate_gemini(prompt, path, model):
                    ok = True
                    gemini_succeeded += 1
            except GeminiUnavailable as e:
                last_error = e
                print(f"[image_gen] img {i}: Gemini also failed: {e}")

        # Last line of defence: no provider's frame reaches the assembler blank,
        # whatever it reported. A missing scene is recoverable; a black frame in
        # a published reel is not.
        if ok and is_blank(path):
            print(f"[image_gen] img {i}: provider returned a BLANK frame — dropping scene")
            ok = False

        # VISION GATE. The pipeline cannot see its own output, so every rule the
        # channel actually cares about (bare jaw, clothed goddess, adult deity,
        # picture matching its line) has until now been unenforceable prose. One
        # vision call per frame makes it a check. Retry once, then keep the frame
        # but record it loudly — a missing scene breaks the render, a flagged one
        # only needs a human to look.
        if ok and (cfg.get("images", {}) or {}).get("frame_check"):
            from .frame_check import check
            good, why = check(path, _deity_name(raw_prompt, cfg), raw_prompt)
            if not good:
                print(f"[image_gen] img {i}: FRAME CHECK FAILED — {'; '.join(why)} — regenerating")
                if use_fal and _generate_fal_flux(
                        prompt, path, model=(hero_model if is_hero else fal_model),
                        target_w=target_w, target_h=target_h) and not is_blank(path):
                    good, why = check(path, _deity_name(raw_prompt, cfg), raw_prompt)
                if not good:
                    FRAME_ISSUES.append(f"img {i}: {'; '.join(why)}")
                    print(f"[image_gen] img {i}: STILL FAILING after retry — {'; '.join(why)}")

        if ok:
            # Enforce target aspect ratio: resize+center-crop if provider gave wrong orientation
            try:
                img = Image.open(path)
                if img.size != (target_w, target_h):
                    img = _fit_to_aspect(img, target_w, target_h)
                    img.save(str(path), "JPEG", quality=92)
            except Exception as e:
                print(f"[image_gen] resize warning on img {i}: {e}")
            results.append(path)

    if FRAME_ISSUES:
        print(f"[image_gen] {len(FRAME_ISSUES)} FRAME(S) FAILED THE VISION CHECK:")
        for f in FRAME_ISSUES:
            print(f"  - {f}")

    print(f"[image_gen] {len(results)}/{len(visual_prompts)} generated "
          f"(ref-consistent: {ref_succeeded}, fal: {fal_succeeded}, HF: {hf_succeeded}, "
          f"Gemini: {gemini_succeeded}) @ {target_w}x{target_h}")

    # If we got NOTHING and Gemini failed, raise so retry queue catches it
    if not results and last_error is not None:
        raise last_error
    if not results:
        raise GeminiUnavailable("All providers failed for every image")
    return results


# Frames that failed the vision gate in the current run. run.py can surface this
# (the Discord failure alert already exists) so a flagged render is never silent.
FRAME_ISSUES: list[str] = []


_TEXT_REQUEST = re.compile(
    r"[^,.;—]*\b(?:the\s+)?(?:sanskrit\s+|devanagari\s+)?"
    r"(?:word|words|letters?|lettering|script|inscription|text|writing|written|"
    r"spelled|calligraphy|mantra\s+written)\b[^,.;—]*", re.I)


def _strip_text_requests(visual: str) -> str:
    """Drop clauses asking for WORDS to be rendered inside the image.

    2026-10-21: a live reel's scene 9 asked for "a radiant Sanskrit word SATTVA
    in pure gold light floating at the centre of the frame". No diffusion model
    can spell Sanskrit, so it produced a halo of convincing-looking nonsense
    letters — which the vision gate correctly failed, twice, burning a
    regeneration each time. images.image_style_guidance already says NO text and
    the writer asked for it anyway, so the ban is enforced here instead of
    merely requested. The rest of the scene direction is kept."""
    out = _TEXT_REQUEST.sub("", visual or "")
    out = re.sub(r"\s*,\s*,", ",", out)
    out = re.sub(r"\s{2,}", " ", out).strip(" ,;—")
    return out or (visual or "")


# CONCRETE sacred OBJECTS only. "deity", "goddess" and "god" were in this list
# and are not objects — they are words the writer uses to DESCRIBE a frame. On
# 2026-10-21 the hook scene "a lone human silhouette half-submerged in fog,
# phone screen glow the only light" contained the word "deity" further along in
# its own text, so this let it through as already-sacred, _force_deity skipped
# it, and the reel opened on a banned modern silhouette — as its FB cover frame.
_SACRED = ("trishul", "trident", "vajra", "chakra", "conch", "shankh",
           "lotus throne", "murti", "yantra", "lingam", "shivling", "gada",
           "vahana", "temple", "mandir", "damaru", "kirita", "mundamala")


def _force_deity(visuals: list[str], cfg: dict) -> list[str]:
    """Make every scene a DARSHAN frame.

    2026-10-21, measured on a finished reel: 5 of 9 sampled frames had no deity
    in them at all — a person asleep in bed with a phone, a silhouette in a
    doorway, a tiny figure in a light beam, a bare torso, a woman's profile made
    of clouds. The script's own visual directions asked for exactly that. Every
    one of those shapes is already BANNED in images.image_style_guidance, which
    is prose and therefore never ran. The user's words: "images bhagwaan wali
    feeling nahi de rahe, aur relevant nahi lag rahe".

    A deity-less scene cannot be rescued by regenerating it — the prompt itself
    has no deity in it — so the prompt is rewritten here: the scene's action is
    kept and re-staged around the deity this script is actually about, found
    from whichever deity the script names most often.
    """
    blocks = (cfg.get("images", {}) or {}).get("deity_blocks") or {}
    if not blocks:
        return visuals
    counts: dict[str, int] = {}
    for v in visuals:
        d = _deity_name(v, cfg)
        if d:
            counts[d] = counts.get(d, 0) + 1
    lead = max(counts, key=counts.get) if counts else ""
    out = []
    for v in visuals:
        low = (v or "").lower()
        if _deity_name(v, cfg) or any(k in low for k in _SACRED):
            out.append(v)
            continue
        if lead:
            out.append(f"{lead.title()} is the large dominant figure filling the frame, "
                       f"facing the viewer. Around him: {v}")
        else:
            out.append(f"A Hindu deity is the large dominant figure filling the frame, "
                       f"facing the viewer in ornate devotional iconography. Around the deity: {v}")
    return out


def _match_deity(text: str, blocks: dict) -> str:
    """Which deity_blocks key this text NAMES, as a whole word, or "".

    WORD BOUNDARIES MATTER MORE THAN THEY LOOK. This matched on a bare substring
    until 2026-10-21, which meant "dramatic" contained "ram" — so any scene
    description with the word "dramatic" in it (and the LLM writes that
    constantly; the channel's own style text says "dramatic chiaroscuro
    lighting") silently had RAM's full iconography injected: dark blue skin, a
    longbow, a kirita crown. That is why reels about other deities kept coming
    back full of blue archers, and why a deity-less scene was left un-restaged
    and shipped as a woman alone in a forest. "drama", "programme" and
    "panorama" hit it too.

    Longest key first so "kartikeya" is not shadowed by a shorter one."""
    if not blocks:
        return ""
    low = (text or "").lower()
    for name in sorted(blocks, key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", low):
            return name
    return ""


def _deity_name(text: str, cfg: dict) -> str:
    """Which deity_blocks key this prompt names, or "". Longest key first so
    "kartikeya" is not shadowed by a shorter one — same rule as _deity_block."""
    blocks = (cfg.get("images", {}) or {}).get("deity_blocks") or {}
    return _match_deity(text, blocks)


def _deity_block(text: str, cfg: dict) -> str:
    """Return the iconography block for the deity named in `text`, or "".

    Added 2026-10-21. The old approach put SIX deities' attributes into every
    prompt via images.style_suffix (416 of 624 T5 tokens) while the scene's own
    text was ~3% — attributes bound to whoever was nearest rather than to the
    deity asked for, and on the bulk model (schnell, 256-token cap) most of the
    prompt was discarded unread. One deity's marks per prompt fixes both.
    Longest name first so "kartikeya" is not shadowed by a shorter key.
    """
    blocks = (cfg.get("images", {}) or {}).get("deity_blocks") or {}
    name = _match_deity(text, blocks)
    return str(blocks[name]).strip() if name else ""


def _fit_to_aspect(img, target_w: int, target_h: int):
    """Center-crop + resize image to exact target dimensions, preserving content."""
    from PIL import Image
    sw, sh = img.size
    target_aspect = target_w / target_h
    src_aspect = sw / sh
    if src_aspect > target_aspect:
        # Source is wider — crop sides
        new_w = int(sh * target_aspect)
        left = (sw - new_w) // 2
        img = img.crop((left, 0, left + new_w, sh))
    elif src_aspect < target_aspect:
        # Source is taller — crop top/bottom
        new_h = int(sw / target_aspect)
        top = (sh - new_h) // 2
        img = img.crop((0, top, sw, top + new_h))
    return img.resize((target_w, target_h), Image.LANCZOS)


# Public exception for run.py to catch
__all__ = ["generate_images", "GeminiUnavailable", "_generate_gemini"]
