"""End-to-end pipeline: topic → script → tts → images → video → (publish)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path

from pipeline.assembler import assemble
from pipeline.image_gen import generate_images
from pipeline.scraper import gather_context
from pipeline.script_writer import write_script
from pipeline.topic_generator import pick_mantra, pick_series, pick_shloka_episode, pick_topic, pick_trending
from pipeline.tts import synthesize
from pipeline.utils import dedupe_script_narration, load_config, out_path, set_active_niche, slugify, today_stamp


# Exact YouTube go-live time (UTC HH:MM) per auto-publish slot, keyed by
# (niche, kind, seed_offset). The generation cron fires HOURS earlier (buffer for
# GitHub's late crons); YouTube flips the private upload public at this exact time.
PUBLISH_TIMES = {
    ("bhakti",  "mantra",   0): "01:30",  # ~7:00 AM IST
    ("ancient", "trending", 1): "18:00",  # 2:00 PM ET (US afternoon)
    ("ancient", "trending", 2): "00:00",  # 8:00 PM ET (US evening prime)
    ("ancient", "trending", 3): "21:00",  # 5:00 PM ET (US afternoon — 3rd daily TD slot)
    ("bhajan",  "trending", 0): "13:30",  # ~7:00 PM IST Sunday
    ("itihaas", "trending", 1): "03:00",  # ~8:30 AM IST next morning (AM drop)
    ("itihaas", "series",   3): "14:30",  # ~8:00 PM IST — PM series (Mahabharat Villains, ACTIVE)
    ("itihaas", "trending", 3): "14:30",  # ~8:00 PM IST — PM standalone rahasya (fallback mapping)
    # GoM (audience US 60%, proven peaks 1 PM & 9 PM ET): generate EARLY with a big
    # 5-6h buffer (gen 12:00/15:00/19:00 UTC), then YT native-schedules to these
    # exact times AND FB/IG are queued (facebook_make_scheduled) → posted by the
    # reel-poster cron at the exact peak. Big buffer = even a multi-hour GitHub
    # cron lag finishes before peak → no missed slot (SOP G3); zero platform drift.
    ("godmind", "trending", 1): "17:00",  # 1 PM ET (US lunch — proven 10.6k)
    ("godmind", "trending", 2): "21:00",  # 5 PM ET (US afternoon — spread between the 1 PM & 9 PM proven peaks)
    ("godmind", "trending", 3): "01:00",  # 9 PM ET (US night — proven 9.3k)
    # Money Neurons (MN) — US money-psychology, same proven US windows. Generate
    # EARLY (big buffer) → YT native-schedules to peak + FB queued via Make poster.
    ("moneurons", "trending", 1): "17:00",  # 1 PM ET (US lunch scroll)
    ("moneurons", "trending", 2): "22:00",  # 6 PM ET (after-work finance scroll)
    ("moneurons", "trending", 3): "01:00",  # 9 PM ET (US night prime)
}


def _slot_publish_at(args) -> str | None:
    """Explicit --publish-at wins; else the slot's configured go-live time."""
    return args.publish_at or PUBLISH_TIMES.get((args.niche, args.kind, args.seed_offset))


def _publish_at_iso(hhmm: str | None) -> str | None:
    """Turn a 'HH:MM' UTC time-of-day into an RFC3339 timestamp at the NEAREST
    occurrence of that peak: today's if it's still ahead, else either tomorrow's
    or NOW. Returns None only if not given/malformed."""
    if not hhmm:
        return None
    # Full RFC3339 timestamp (date-specific schedule, e.g. "2026-06-15T01:00:00Z")
    # passes through as-is — used for one-off date drops like Neem Karoli Jayanti.
    if "T" in hhmm or "-" in hhmm:
        return hhmm
    try:
        from datetime import datetime, timedelta, timezone
        h, m = (int(x) for x in hhmm.split(":"))
        now = datetime.now(timezone.utc)
        today = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if today > now:
            target = today
        else:
            # Peak already passed today. Pick whichever occurrence is NEARER:
            #  - passed >12h ago → it's a late-night peak meant for the NEXT day
            #    (e.g. GoM's 01:00 slot generated the previous evening ~21:00).
            #    Schedule tomorrow so it lands AT its peak instead of posting
            #    hours early, getting gap-held, then dropped >6h past peak — the
            #    bug that silently ate GoM's 01:00 reel every evening.
            #  - passed <12h ago → a genuinely missed same-day peak (late gen /
            #    catch-up re-run). Post NOW+1m so it isn't stranded ~24h; the
            #    poster's per-page gap guard still spaces it and its ">6h past
            #    peak → drop" rule still blocks a bad off-peak post.
            tomorrow = today + timedelta(days=1)
            target = tomorrow if (now - today) > timedelta(hours=12) else now + timedelta(minutes=1)
        return target.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception as e:
        print(f"[publish-at] bad value {hhmm!r} ({e}) — publishing immediately")
        return None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--niche", default="bhakti",
        choices=["bhakti", "itihaas", "bhajan", "ancient", "godmind", "moneurons"],
        help="Which niche to run (bhakti = KalyaanPath; itihaas = Itihaasvani; bhajan = Flow Music MP3; ancient = Ancient World Decoded English; godmind = Gods of the Mind; moneurons = Moneurons US money-psychology)",
    )
    ap.add_argument(
        "--deity",
        choices=["hanuman", "krishna", "shiva", "ram", "devi", "ganesh", "sai", "khatu_shyam", "neem_karoli", "general"],
        help="For --niche bhajan: pick MP3 from data/music_bhajan/[deity]/. If omitted, scans all deity folders (excludes one-off specials like neem_karoli). Falls back to env BHAJAN_DEITY.",
    )
    ap.add_argument(
        "--bhajan-audio",
        help="For --niche bhajan: explicit path to MP3 (overrides --deity auto-pick).",
    )
    ap.add_argument(
        "--kind", default="auto",
        choices=["auto", "shloka", "trending", "mantra", "series"],
        help="auto = legacy daily rotation; shloka = next Gita verse episode (PARKED — pivoted to mantra); trending = current festival/popular deity; mantra = mantra-rahasya format (KalyaanPath morning slot, post-pivot)",
    )
    ap.add_argument(
        "--topic", default="auto",
        help="auto (default) or custom title (overrides --kind)",
    )
    ap.add_argument("--publish", action="store_true", help="Upload to YouTube + Instagram")
    ap.add_argument(
        "--public-url", default=None,
        help="Public HTTPS URL for the video (required for Instagram upload)",
    )
    ap.add_argument("--skip-images", action="store_true", help="Reuse existing images if present (debug)")
    ap.add_argument("--force", action="store_true", help="Bypass the already-published-today dedup guard (intentional re-runs).")
    ap.add_argument(
        "--no-music", action="store_true",
        help="Skip background music — produces voice-only mp4. Use for YouTube Shorts so you can add trending audio at upload time (algorithm boost).",
    )
    ap.add_argument(
        "--skip-captions", action="store_true",
        help="Skip word-by-word caption overlays. Faster assembly + lower ffmpeg memory/thread pressure. Use when video is pure visual + voice (no on-screen text).",
    )
    ap.add_argument(
        "--auto-thumb", action="store_true",
        help="Auto-generate a custom thumbnail for the video and save to output/thumbnails/.",
    )
    ap.add_argument(
        "--notify-telegram", action="store_true",
        help="Send video + thumbnail + metadata to Telegram bot for manual upload. Auto-enables --auto-thumb.",
    )
    ap.add_argument(
        "--seed-offset", type=int, default=0,
        help="Integer offset to vary topic pick on the same day. Use 1 for first daily drop, 2 for second, etc.",
    )
    ap.add_argument(
        "--long-form", action="store_true",
        help="Generate a 20-25 min long-form video (vs default 50-sec Short). Uses more scenes (~30), longer script (~3500 words), heavier production. Best for weekly/bi-weekly drops.",
    )
    ap.add_argument(
        "--no-motion", action="store_true",
        help="Disable the single Kling hero-scene animation (saves ~$0.4/video).",
    )
    ap.add_argument(
        "--publish-at", default=None, metavar="HH:MM",
        help="UTC time-of-day to SCHEDULE the YouTube go-live (e.g. 00:00). Upload "
             "happens now (private); YouTube flips it public at the next occurrence "
             "of this time. Makes go-live exact despite GitHub's late crons.",
    )
    args = ap.parse_args(argv)
    if args.notify_telegram:
        args.auto_thumb = True
    # Env fallbacks for workflow-driven one-offs (keeps the run steps clean; empty
    # env on normal runs → no effect).
    if not args.deity:
        args.deity = os.environ.get("BHAJAN_DEITY", "").strip() or None
    if not args.publish_at:
        args.publish_at = os.environ.get("PUBLISH_AT_ISO", "").strip() or None

    set_active_niche(args.niche)
    print(f"== Reels pipeline ({args.niche}) ==")

    # Dedup guard: skip if this exact slot (niche/kind/seed) was ALREADY
    # delivered today. Prevents duplicate uploads from catch-up / retry /
    # concurrent re-runs landing on the SAME publishAt slot — the #1 cause of
    # same-minute double videos that YouTube buries at 1-12 views. --force bypasses.
    if (args.publish or args.notify_telegram) and not args.force:
        try:
            from pipeline.publish_log import was_published_today
            if was_published_today(args.niche, args.kind, args.seed_offset):
                print(f"[dedup] {args.niche}/{args.kind} s{args.seed_offset} already delivered today — skipping (use --force to override)")
                return 0
        except Exception:
            traceback.print_exc()

    # Bhajan mode: MP3 → bhajan video (separate flow, no script/TTS)
    if args.niche == "bhajan":
        return _run_bhajan(args)

    # 1. topic — check pregen cache FIRST (saves Gemini calls at peak hours)
    from datetime import date as _date_t
    from pipeline import pregen as _pregen, scheduler as _scheduler
    pregen_active = False
    pregen_dir = None
    cached_images = None
    cached_thumb = None
    cached_script = None

    if args.topic == "auto" and not args.long_form:
        pregen_dir = _pregen.is_pregen_ready(args.niche, args.kind, _date_t.today(), args.seed_offset)
        if pregen_dir:
            pregen_data = _pregen.load_pregen(pregen_dir)
            cached_topic_meta = pregen_data["meta"].get("topic") or {}
            # Safety check: verify pregen topic still matches what realtime picker would choose
            # (catches edge case: shloka sequence drifted, festival appeared since pregen, etc.)
            if args.kind == "trending":
                realtime_topic = pick_trending(seed_offset=args.seed_offset)
            elif args.kind == "shloka":
                # For shloka, only peek (don't mutate state — we'll mutate at actual publish)
                from pipeline.scheduler import _peek_shloka_at_offset
                realtime_topic = _peek_shloka_at_offset(0)
            else:
                realtime_topic = pick_topic("auto", seed_offset=args.seed_offset)

            match_keys = ("ref", "title") if args.kind == "shloka" else ("title",)
            match_ok = all(realtime_topic.get(k) == cached_topic_meta.get(k) for k in match_keys)
            if match_ok:
                topic = cached_topic_meta
                cached_script = pregen_data["script"]
                cached_images = pregen_data["images"]
                cached_thumb = pregen_data["thumbnail"]
                pregen_active = True
                print(f"[pregen] ✓ cache hit → {pregen_dir.name}")
                print(f"[pregen] topic: {topic.get('title')}  images: {len(cached_images)}  thumb: {bool(cached_thumb)}")
            else:
                print(f"[pregen] ⚠ cache topic mismatch (cached='{cached_topic_meta.get('title')}' vs realtime='{realtime_topic.get('title')}') — falling back to realtime")

    if not pregen_active:
        if args.topic and args.topic != "auto":
            topic = pick_topic(args.topic, seed_offset=args.seed_offset)
        elif args.kind == "mantra":
            topic = pick_mantra(seed_offset=args.seed_offset)
        elif args.kind == "series":
            topic = pick_series(seed_offset=args.seed_offset)
        elif args.kind == "shloka":
            topic = pick_shloka_episode()
        elif args.kind == "trending":
            topic = pick_trending(seed_offset=args.seed_offset)
        else:
            topic = pick_topic("auto", seed_offset=args.seed_offset)

        # Long-form mode: wrap base topic in proven viral title format
        # (Top 10 / Untold story / Complete history etc. — proven on
        # Praveen Mohan, KrazzyKreations, Kaliyug ke Divya Mantra scale).
        if args.long_form and args.topic == "auto":
            from pipeline.topic_generator import viralize_longform_title
            from pipeline.utils import load_config as _lc
            lang = _lc().get("llm", {}).get("language", "hindi").lower()
            topic = viralize_longform_title(topic, language=lang)
            print(f"[topic] long-form viral-format applied: {topic.get('title')}")
    print(f"[topic] {topic}")

    # TOPIC-based dedup (second layer, after the slot guard above). A different
    # slot/seed/run picking the SAME topic, or a festival topic repeating across
    # days, slips past the slot guard and produces a DUPLICATE YouTube upload
    # (observed: Stonehenge ×7, Overthinking ×2). Skip the WHOLE run (no YT + no
    # FB) if this topic was already published in the last 10 days. --force bypasses.
    if (args.publish or args.notify_telegram) and not args.force:
        try:
            from pipeline.publish_log import title_published_recently, topic_live_on_youtube
            _tt = topic.get("title", "")
            # Two layers: (1) local ledger (fast, but can be stale under a git-race),
            # (2) LIVE YouTube check (slower, but immune to state loss — catches the
            # same-topic-different-subtitle dups the ledger missed). Either → skip.
            if title_published_recently(_tt) or topic_live_on_youtube(_tt, args.niche):
                print(f"[dedup] topic '{_tt}' already published "
                      f"recently — skipping to avoid a duplicate upload (use --force)")
                return 0
        except Exception:
            traceback.print_exc()

    stamp = today_stamp()
    slug = slugify(topic["title"])
    base = f"{stamp}_{slug}"

    # 2. scrape context  (skipped if pregen — already in cached script)
    if not pregen_active:
        context = gather_context(topic)
        print(f"[scrape] context length: {len(context)}")

    # 3. script via LLM (skipped if pregen — already cached)
    if pregen_active:
        script = cached_script
        print(f"[script] loaded from pregen cache → title: {script.get('title')}")
    else:
        script = write_script(topic, context, long_form=args.long_form)
        # attach topic metadata so assembler can render episode badge / verse overlay
        for key in ("kind", "episode_number", "ref", "verse", "theme"):
            if key in topic and key not in script:
                script[key] = topic[key]
        print(f"[script] title: {script.get('title')}")
    # Guard against the hook being repeated as body[0] (some personas instruct
    # body[0] to be the same opener as the hook → first sentence spoken twice).
    # Runs for BOTH fresh and pregen-cached scripts, before TTS + captions.
    dedupe_script_narration(script)
    script_path = out_path("scripts", f"{base}.json")
    script_path.write_text(json.dumps(script, indent=2, ensure_ascii=False))

    # 4. TTS voiceover (always realtime — fast + deterministic, not worth caching)
    voice_path = out_path("audio", f"{base}.mp3")
    synthesize(script, voice_path, seed_offset=args.seed_offset)
    print(f"[tts] saved → {voice_path}")

    # 5. images — pregen cache wins, else realtime gen
    img_dir = out_path("images", base)
    _img_cfg = load_config().get("images", {})
    # Footage mode triggers either globally (images.mode=footage) OR per-topic
    # (place/monument viral topics carry "footage": true → Pexels B-roll, while
    # mythology-figure topics on the same channel stay on fal AI images).
    footage_mode = (
        str(_img_cfg.get("mode", "image")).lower() == "footage"
        or bool(topic.get("footage"))
    ) and not args.long_form
    # Itihaasvani (Indian monuments/temples): Pexels has no real footage of these
    # → it returned FOREIGN clips (authenticity killer). Use authentic real photos
    # from Wikimedia Commons instead (Ken Burns motion animates them), with fal AI
    # India-images as fallback. Other niches (TimeDecoders) keep Pexels footage.
    # Real-person subjects (saints/gurus like Neem Karoli Baba) can't be AI-faked —
    # FORCE_REAL_PHOTOS="<Commons search term>" routes the run through the Wikimedia
    # real-photo hybrid (CC0/CC face photos spliced into AI ambiance, auto-credited),
    # exactly like Itihaasvani monuments. Works on ANY niche.
    _real_q = os.environ.get("FORCE_REAL_PHOTOS", "").strip()
    if _real_q:
        topic["query"] = _real_q   # clean English search term for Commons
    wiki_mode = (footage_mode and args.niche == "itihaas") or (bool(_real_q) and not args.long_form)
    if wiki_mode:
        footage_mode = False
    footage_clips: dict[int, Path] = {}
    if pregen_active and cached_images and len(cached_images) >= 5:
        # Copy cached images into the run's image dir (so cleanup logic stays consistent)
        img_dir.mkdir(parents=True, exist_ok=True)
        import shutil as _shutil
        for i, src in enumerate(cached_images):
            dst = img_dir / f"img_{i:02d}.jpg"
            if not dst.exists():
                _shutil.copy2(src, dst)
        images = sorted(img_dir.glob("img_*.jpg"))
        print(f"[images] ✓ used {len(images)} pre-generated images from cache")
    elif args.skip_images and img_dir.exists() and any(img_dir.iterdir()):
        images = sorted(img_dir.glob("img_*.jpg"))
        print(f"[images] reusing {len(images)} cached")
    elif wiki_mode:
        # HYBRID (Itihaasvani): scene-matched AI images that FOLLOW the script and
        # build suspense (cinematic, authentic Indian setting) as the base, with a
        # few REAL Wikimedia photos of the actual monument spliced into establishing
        # slots for recognizable authenticity. Real-photo credits auto-appended to
        # the description (CC attribution — name only, no payment). If AI is down,
        # fall back to all real photos; if both fail, retry-queue.
        import shutil as _sh
        from pipeline.wiki_images import fetch_wiki_images, build_credit_block

        # 1) AI base — per-scene, cinematic + suspenseful, authentic Indian look.
        _style = ("cinematic dramatic lighting, moody atmospheric, mysterious and "
                  "suspenseful, photorealistic, authentic ancient Indian setting, "
                  "highly detailed, no text, no watermark")
        _visuals = [f"{v}. {_style}" for v in (script.get("visuals") or [])]
        try:
            images = generate_images(_visuals, img_dir, long_form=args.long_form,
                                     character_bible=script.get("character_bible"))
            print(f"[images] {len(images)} AI scene-matched (hybrid base)")
        except Exception as e:
            print(f"[images] AI base unavailable ({type(e).__name__}: {e}) — trying all real photos")
            images = []

        # 2) Real Wikimedia monument photos (for inserts, or full set if AI down).
        real_dir = out_path("images", base + "_real")
        real_imgs, real_credits = [], []
        try:
            real_imgs, real_credits = fetch_wiki_images(topic, real_dir, want=6)
        except Exception as e:
            print(f"[wiki] real-photo fetch error: {type(e).__name__}: {e}")
        used_credits: list[str] = []

        if images:
            # Splice real photos into establishing slots (opening + spread).
            if real_imgs:
                n = len(images)
                slots = [0]
                if n >= 4:
                    slots.append(n // 2)
                if n >= 7:
                    slots.append(n - 2)
                k = 0
                for slot, rp in zip(slots, real_imgs):
                    try:
                        _sh.copy2(rp, images[slot])
                        used_credits.append(real_credits[k])
                        k += 1
                    except Exception:
                        pass
                print(f"[wiki] spliced {k} real monument photos into AI base (slots {slots[:k]})")
        else:
            # AI unavailable → use real photos as the whole set if we have enough.
            if len(real_imgs) >= 5:
                img_dir.mkdir(parents=True, exist_ok=True)
                images = []
                for i, rp in enumerate(real_imgs):
                    dst = img_dir / f"img_{i:02d}.jpg"
                    _sh.copy2(rp, dst)
                    images.append(dst)
                used_credits = list(real_credits[:len(images)])
                print(f"[wiki] AI down — using {len(images)} real Wikimedia photos")
            else:
                from pipeline.retry_queue import add_or_update
                reason = f"hybrid: AI base failed and only {len(real_imgs)} real photos"
                print(f"[retry-queue] saving for hourly retry: {reason}")
                add_or_update(
                    niche=args.niche, kind=args.kind, topic=args.topic or "auto",
                    seed_offset=args.seed_offset,
                    mode=("publish" if args.publish else ("telegram" if args.notify_telegram else "local")),
                    failed_reason=reason,
                )
                return 2

        # 3) Attribution for the real photos actually used.
        cb = build_credit_block(used_credits)
        if cb:
            script["description"] = (script.get("description", "") + "\n\n" + cb).strip()
    elif footage_mode:
        # B-roll mode (TimeDecoders): fetch REAL stock clips per scene instead of
        # AI stills. Posters (first frames) act as the still fallback + thumbnail
        # base; the clips are spliced for every scene via hero_clips below.
        try:
            from pipeline.stock_footage import build_stock_queries, fetch_clips, extract_posters
            queries = build_stock_queries(script)
            clip_dir = out_path("videos", f"_broll_{base}")
            clips = fetch_clips(queries, clip_dir)
            images = extract_posters(clips, img_dir)
            # Align: poster i ↔ clip i. Use whichever count actually materialised.
            n_ok = min(len(images), len(clips))
            images = images[:n_ok]
            footage_clips = {i: clips[i] for i in range(n_ok)}
            print(f"[footage] {n_ok} B-roll scenes ready")
            if n_ok < 3:
                raise RuntimeError(f"only {n_ok} stock clips fetched (<3)")
        except Exception as e:
            from pipeline.retry_queue import add_or_update
            reason = f"footage: {type(e).__name__}: {e}"
            print(f"[retry-queue] saving for hourly retry: {reason}")
            add_or_update(
                niche=args.niche, kind=args.kind, topic=args.topic or "auto",
                seed_offset=args.seed_offset,
                mode=("publish" if args.publish else ("telegram" if args.notify_telegram else "local")),
                failed_reason=reason,
            )
            return 2
    else:
        try:
            images = generate_images(script["visuals"], img_dir, long_form=args.long_form,
                                     character_bible=script.get("character_bible"))
            print(f"[images] generated {len(images)}")
        except Exception as e:
            # GeminiUnavailable etc. — save to retry queue, exit cleanly
            from pipeline.image_gen import GeminiUnavailable
            from pipeline.retry_queue import add_or_update
            reason = f"{type(e).__name__}: {e}"
            print(f"[retry-queue] saving for hourly retry: {reason}")
            entry = add_or_update(
                niche=args.niche,
                kind=args.kind,
                topic=args.topic or "auto",
                seed_offset=args.seed_offset,
                mode=("publish" if args.publish else ("telegram" if args.notify_telegram else "local")),
                failed_reason=reason,
            )
            print(f"[retry-queue] entry attempts={entry['attempts']}/3, next_retry_at={entry['next_retry_at']}")
            return 2  # signal: temporary failure, will be retried

    # 5b. Hero motion — animate ONE scene (the hook) into a real Kling clip so
    # the reel doesn't feel like a static slideshow. Single clip keeps cost ~$0.4.
    # Gated by config (video.hero_motion, default on), --no-motion, and not long-form.
    hero_clips = None
    if footage_mode and footage_clips:
        # Every scene already has a real stock clip → splice them all (no Kling).
        hero_clips = footage_clips
        print(f"[footage] splicing {len(footage_clips)} B-roll clips across all scenes")
    _hero_on = bool(load_config().get("video", {}).get("hero_motion", True))
    if hero_clips is None and _hero_on and not args.no_motion and not args.long_form and len(images) >= 3:
        try:
            from pipeline.kling_video import generate_hero_clip
            hero_idx = 0  # the hook image — first 3 seconds matter most for retention
            hero_motion_prompt = (
                "subtle cinematic motion: a slow gentle camera push-in, soft drifting "
                "atmosphere and divine light rays, faint particles floating, the figure "
                "breathes and blinks softly, cloth and hair sway gently — dignified, calm, "
                "no fast movement, no morphing, keep the face and design exactly the same"
            )
            hero_clip = out_path("videos", f"_hero_{base}.mp4")
            if generate_hero_clip(hero_motion_prompt, images[hero_idx], hero_clip, duration=5):
                hero_clips = {hero_idx: hero_clip}
                print(f"[motion] hero scene {hero_idx + 1} animated via Kling v3")
            else:
                print("[motion] hero clip failed — using Ken Burns still")
        except Exception as e:
            print(f"[motion] hero animation skipped: {type(e).__name__}: {e}")

    # 6. assemble
    video_path = out_path("videos", f"{base}.mp4")
    # Music policy: Telegram drops go out WITHOUT background music (user adds
    # trending audio at manual upload for the algorithm boost). Auto-publish
    # runs keep the dynamic, mood-matched cinematic music bed.
    # Music is controlled by --no-music and the niche config (video.music);
    # NOT forced off for Telegram drops anymore (we now bake our mood music/SFX
    # into the video instead of relying on manually-added platform audio).
    _skip_music = args.no_music
    assemble(script, voice_path, images, video_path, skip_music=_skip_music, skip_captions=args.skip_captions, long_form=args.long_form, hero_clips=hero_clips)
    print(f"[video] FINAL → {video_path}{' (no-music)' if _skip_music else ''}")

    # 6b. thumbnail — pregen cache wins, else realtime gen.
    # Per-channel opt-out (config `thumbnail: false`): e.g. GoM Shorts — a custom
    # thumbnail isn't shown in the Shorts feed, and the endcard isn't wanted.
    thumb_path = None
    _thumb_enabled = load_config().get("thumbnail", True)
    if args.auto_thumb and _thumb_enabled:
        thumb_path = out_path("thumbnails", f"{base}.jpg")
        if pregen_active and cached_thumb and Path(cached_thumb).exists():
            import shutil as _shutil
            _shutil.copy2(cached_thumb, thumb_path)
            print(f"[thumbnail] ✓ used pre-generated thumbnail from cache")
        else:
            try:
                from pipeline.thumbnail_gen import make_thumbnail
                make_thumbnail(script, args.niche, thumb_path, long_form=args.long_form,
                               img_dir=img_dir)
            except Exception:
                traceback.print_exc()
                print("[thumbnail] generation failed — continuing without")
                thumb_path = None

    # 6c. append thumbnail as end card on the video (replay-hook)
    if thumb_path and Path(thumb_path).exists():
        try:
            from pipeline.endcard import append_thumbnail_endcard
            append_thumbnail_endcard(video_path, thumb_path, duration_sec=2.5)
        except Exception:
            traceback.print_exc()
            print("[endcard] failed — video kept without endcard")

    # Track successful delivery so the catch-up safety net knows this slot is done.
    _delivered = False
    _platforms: dict = {}   # per-platform outcome (url / queued / posted / failed) for the Discord report

    # 6d. notify Telegram (optional). Also fires when facebook_manual is set — while
    # FB auto-posting is paused (Meta account flag), each published video is dropped
    # to Telegram with a reminder to post it to Facebook BY HAND (manual posting goes
    # through the FB app, not the flagged developer API, so it's safe).
    _fb_manual = load_config().get("publish", {}).get("facebook_manual", False)
    _tg_note = None
    if _fb_manual:
        _tg_note = ("📘➡️ *FB pe MANUALLY post kar do* (auto-FB abhi paused hai).\n"
                    "Neeche wali video download karke Facebook page pe Reel daal do.")
    if args.notify_telegram or _fb_manual:
        try:
            from pipeline.notifier_telegram import notify as tg_notify
            tg_notify(video_path, thumb_path, script, args.niche,
                      seed_offset=args.seed_offset, note=_tg_note,
                      schedule_iso=_publish_at_iso(_slot_publish_at(args)))
            _delivered = True
        except Exception:
            traceback.print_exc()
            print("[telegram] notify failed")

    # 7. publish
    if args.publish:
        cfg = load_config()
        publish_cfg = cfg.get("publish", {})

        if publish_cfg.get("youtube", True):
            try:
                from pipeline.uploader_youtube import upload as yt_upload
                url = yt_upload(video_path, script, thumb_path=thumb_path,
                                publish_at=_publish_at_iso(_slot_publish_at(args)))
                print(f"[publish] youtube: {url}")
                _platforms["youtube"] = url
                _delivered = True
            except Exception:
                traceback.print_exc()
                _platforms["youtube"] = "failed"
                print("[publish] youtube failed — see traceback above")
        else:
            print("[publish] skipped youtube (disabled in config)")

        # Facebook Page Reel (bonus channel — never blocks YouTube). Enable per
        # niche with `publish.facebook: true` + FB_PAGE_ID / FB_PAGE_TOKEN secrets.
        if publish_cfg.get("facebook", False):
            try:
                from pipeline.uploader_facebook import upload as fb_upload
                fb_url = fb_upload(video_path, script, cfg=cfg,
                                   publish_at_iso=_publish_at_iso(_slot_publish_at(args)))
                if fb_url:
                    print(f"[publish] facebook: {fb_url}")
                    _platforms["facebook"] = fb_url
                    # Bonus channel: only counts as "slot delivered" (which
                    # suppresses catch-up) when YouTube isn't the primary. Else a
                    # YT failure would be masked and never recovered.
                    if not publish_cfg.get("youtube", True):
                        _delivered = True
            except Exception:
                traceback.print_exc()
                print("[publish] facebook failed — see traceback above")

        # Facebook/IG Reel via Make.com (Cloudinary + webhook). Bypasses the
        # flagged Meta dev-app token. Enable per niche with publish.facebook_make: true.
        # AUDIT 2026-07-08: FB organic reach is CAPPED — posting 3/day HALVED GoM's
        # per-post reach (over-posting dilutes + signals low-priority). `facebook_make_slots`
        # (list of seed_offsets) limits FB to specific slots so a niche can be 1/day on FB
        # while staying 3/day on YouTube. Unset → all slots post to FB (unchanged).
        _fb_slots = publish_cfg.get("facebook_make_slots")
        if publish_cfg.get("facebook_make", False) and (_fb_slots is None or args.seed_offset in _fb_slots):
            try:
                from pipeline.uploader_make_reel import upload as make_upload
                # Resolve this channel's FB page id. GoM has no FB_PAGE_ID secret →
                # use its known page id; others use their proven FB_PAGE_ID_<NICHE>
                # secret (bhajan shares the bhakti/KalyaanPath page).
                _GOM_PAGE = "1113214471881336"
                if args.niche == "godmind":
                    _pg = _GOM_PAGE
                else:
                    _k = "BHAKTI" if args.niche in ("bhakti", "bhajan") else args.niche.upper()
                    _pg = (os.getenv(f"FB_PAGE_ID_{_k}") or os.getenv("FB_PAGE_ID") or "").strip()
                # If the niche schedules FB (facebook_make_scheduled), queue the reel
                # for its exact peak (poster cron fires it → no render-time drift).
                # Else post immediately.
                _fb_at = _publish_at_iso(_slot_publish_at(args)) if publish_cfg.get("facebook_make_scheduled") else None
                # A scheduled channel must NEVER post directly — if no time
                # resolved (slot missing from PUBLISH_TIMES), still QUEUE (now+1m)
                # so the poster's per-page gap guard stays the single posting
                # authority. A render-time direct post bypassed that guard and was
                # the back-to-back clustering bug (3 GoM reels within minutes).
                if publish_cfg.get("facebook_make_scheduled") and not _fb_at:
                    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
                    _fb_at = (_dt.now(_tz.utc) + _td(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
                if make_upload(video_path, script, channel=args.niche, fb_page_id=_pg, post_at=_fb_at):
                    print(f"[publish] make-reel {('queued for ' + _fb_at) if _fb_at else 'posted'} ({args.niche} → FB page {_pg})")
                    _platforms["facebook"] = ("queued", _fb_at) if _fb_at else "posted"
                    # Bonus channel: the reel-poster + posted-ledger own FB/IG
                    # reliability. Only mark the SLOT delivered (which suppresses
                    # catch-up) when YouTube isn't the primary for this niche —
                    # otherwise a failed YT upload would look "done" and the
                    # catch-up sweep would never recover the YouTube video.
                    if not publish_cfg.get("youtube", True):
                        _delivered = True
            except Exception:
                traceback.print_exc()
                _platforms["facebook"] = "failed"
                print("[publish] make-reel failed — see traceback above")

        if publish_cfg.get("instagram", False):
            if args.public_url:
                try:
                    from pipeline.uploader_instagram import upload as ig_upload
                    media_id = ig_upload(args.public_url, script)
                    print(f"[publish] instagram: {media_id}")
                    _platforms["instagram"] = "posted"
                except Exception:
                    traceback.print_exc()
                    _platforms["instagram"] = "failed"
                    print("[publish] instagram failed — see traceback above")
            else:
                print("[publish] skipped instagram (no --public-url provided)")
        else:
            print(f"[publish] skipped instagram (disabled for niche '{args.niche}')")

    # 7b. If long-form was just produced (published OR telegram-dropped),
    # auto-clip 3 viral Shorts for the week. Fires for BOTH modes — Itihaasvani
    # is telegram-mode (no OAuth) but still benefits from the multiplier.
    if args.long_form and (args.publish or args.notify_telegram):
        try:
            words_path = voice_path.with_suffix(".words.json")
            if not words_path.exists():
                print("[clip] no words.json — skipping long-form → Shorts clipping")
            else:
                from pipeline.clip_to_shorts import clip_long_form
                print(f"[clip] auto-clipping long-form into 3 viral Shorts...")
                shorts = clip_long_form(
                    video_path=video_path,
                    words_json_path=words_path,
                    long_form_script=script,
                    niche=args.niche,
                    n_clips=3,
                )
                # Deliver each Short to Telegram for manual upload throughout the week
                if shorts:
                    try:
                        from pipeline.notifier_telegram import _send_text, _post
                        token = os.getenv("TELEGRAM_BOT_TOKEN")
                        chat_id = os.getenv("TELEGRAM_CHAT_ID")
                        if token and chat_id:
                            _send_text(token, chat_id,
                                f"🎬 LONG-FORM CLIPPED: {len(shorts)} viral Shorts ready\n\n"
                                f"Schedule one each day this week on {args.niche} channel for max reach.")
                            for s in shorts:
                                clip_p = Path(s["clip_path"])
                                with open(clip_p, "rb") as f:
                                    _post("sendVideo", token,
                                          data={"chat_id": chat_id,
                                                "caption": f"📋 {s['hook_title']}\n\n💡 {s['why_viral']}"},
                                          files={"video": f})
                    except Exception:
                        traceback.print_exc()
                        print("[clip] TG delivery failed — Shorts saved locally")
                print(f"[clip] ✓ created {len(shorts)} Shorts in {video_path.parent}")
        except Exception:
            traceback.print_exc()
            print("[clip] long-form → Shorts clipping failed — long-form already published, continuing")

    # 8. Mark pregen as consumed (so it gets cleaned up + slot freed)
    if pregen_active:
        try:
            _scheduler.mark_consumed(args.niche, args.kind, _date_t.today(), args.seed_offset)
            print(f"[pregen] ✓ marked consumed for today's {args.niche}/{args.kind} s{args.seed_offset}")
        except Exception:
            traceback.print_exc()

    # 9. Record delivery for the catch-up safety net (only if actually delivered).
    if _delivered:
        try:
            from pipeline.publish_log import mark_published, mark_title_published
            mark_published(args.niche, args.kind, args.seed_offset)
            mark_title_published(topic.get("title", ""))  # topic-dedup ledger → no duplicate uploads
            print(f"[catchup] marked {args.niche}/{args.kind} s{args.seed_offset} as delivered today")
        except Exception:
            traceback.print_exc()
        # Discord alert (Telegram replacement) — fire-and-forget, never breaks a run.
        try:
            from pipeline.notifier_discord import report as _dc_report
            _dc_report(args.niche, args.seed_offset, script, _platforms,
                       schedule_iso=_publish_at_iso(_slot_publish_at(args)))
        except Exception:
            pass

    return 0


# ─── Bhajan mode ─────────────────────────────────────────────────────────
def _load_bhajan_lyrics(deity: str) -> str | None:
    """Lyrics for a lyric-synced bhajan (data/bhajan_lyrics_<deity>.txt), or None."""
    from pipeline.utils import ROOT
    p = ROOT / f"data/bhajan_lyrics_{deity}.txt"
    return p.read_text(encoding="utf-8").strip() if p.exists() else None


def _run_bhajan(args) -> int:
    """Flow Music MP3 → bhajan video pipeline (vertical 9:16 Short)."""
    from pipeline.bhajan import (
        pick_bhajan_audio, mark_audio_processed,
        generate_scene_prompts, _generate_images,
        assemble_bhajan_video, build_bhajan_metadata,
    )

    # 1. Pick audio
    if args.bhajan_audio:
        mp3 = Path(args.bhajan_audio).resolve()
        if not mp3.exists():
            print(f"[bhajan] MP3 not found: {mp3}")
            return 1
        # Try to infer deity from parent folder name
        deity = mp3.parent.name.lower() if mp3.parent.name.lower() in {
            "hanuman", "krishna", "shiva", "ram", "devi", "ganesh", "sai",
            "khatu_shyam", "neem_karoli", "general"
        } else "general"
    else:
        picked = pick_bhajan_audio(args.deity)
        if not picked:
            print("[bhajan] nothing to process — drop MP3s in data/music_bhajan/[deity]/")
            return 0
        mp3, deity = picked

    print(f"[bhajan] processing {mp3.name} (deity={deity})")

    stamp = today_stamp()
    slug = slugify(mp3.stem)
    base = f"{stamp}_bhajan_{deity}_{slug}"

    # 2. Generate scene storyboard via LLM
    from pipeline.utils import load_config
    cfg = load_config()
    n_scenes = cfg["images"]["num_per_bhajan"]
    # One-off real-saint bhajans (e.g. Neem Karoli Baba): storyboard the ACTUAL
    # lyrics in order (visuals sync to the verses) and splice his REAL free-licensed
    # photos in (AI never fakes a real person's face).
    _lyrics = _load_bhajan_lyrics(deity) if deity == "neem_karoli" else None
    _real_photo_q = "Neem Karoli Baba" if deity == "neem_karoli" else None
    scene_prompts = generate_scene_prompts(deity, n_scenes, lyrics=_lyrics)

    # 3. Generate images
    img_dir = out_path("images", base)
    images = _generate_images(scene_prompts, img_dir)
    if not images:
        print("[bhajan] image generation failed entirely")
        return 1
    print(f"[bhajan] {len(images)} scene images ready")

    # 3b. Real-photo splice for real-person saints — pin the iconic face at the
    # opening + a couple more spots (his actual likeness, free-licensed, auto-credit).
    _real_credit_block = ""
    if _real_photo_q and images:
        try:
            import shutil as _sh
            from pipeline.wiki_images import fetch_wiki_images, build_credit_block
            real_dir = out_path("images", base + "_real")
            real_imgs, real_credits = fetch_wiki_images({"query": _real_photo_q}, real_dir, want=6)
            if real_imgs:
                n = len(images)
                slots = [0] + ([n // 3, (2 * n) // 3] if n >= 6 else [])
                used = []
                for k, (slot, rp) in enumerate(zip(slots, real_imgs)):
                    try:
                        _sh.copy2(rp, images[slot])
                        used.append(real_credits[k])
                    except Exception:
                        pass
                print(f"[bhajan] spliced {len(used)} real photos into slots {slots[:len(used)]}")
                _real_credit_block = build_credit_block(used)
            else:
                print("[bhajan] no real photos found — using AI ambiance only")
        except Exception as e:
            print(f"[bhajan] real-photo splice failed (non-fatal): {type(e).__name__}: {e}")

    # 4. Assemble video
    video_path = out_path("videos", f"{base}.mp4")
    assemble_bhajan_video(mp3, images, video_path)

    # 5. Build script-like metadata for thumbnail/telegram/upload
    script = build_bhajan_metadata(deity, mp3.stem)
    if _real_credit_block:
        script["description"] = (script.get("description", "") + "\n\n" + _real_credit_block).strip()
    # Save script JSON (used by uploader)
    script_path = out_path("scripts", f"{base}.json")
    script_path.write_text(json.dumps({**script, "visuals": scene_prompts}, indent=2, ensure_ascii=False))

    # 6. Thumbnail (auto-generate via existing module)
    thumb_path = None
    if args.auto_thumb or args.notify_telegram:
        try:
            from pipeline.thumbnail_gen import make_thumbnail
            thumb_path = out_path("thumbnails", f"{base}.jpg")
            make_thumbnail(script, args.niche, thumb_path)
        except Exception:
            traceback.print_exc()
            print("[bhajan] thumbnail failed — continuing without")

    # 7. Endcard
    if thumb_path and Path(thumb_path).exists():
        try:
            from pipeline.endcard import append_thumbnail_endcard
            append_thumbnail_endcard(video_path, thumb_path, duration_sec=2.5)
        except Exception:
            traceback.print_exc()

    # 8. Mark processed (so next cron run doesn't re-pick this MP3)
    mark_audio_processed(mp3)

    # 9. Notify Telegram
    if args.notify_telegram:
        try:
            from pipeline.notifier_telegram import notify as tg_notify
            tg_notify(video_path, thumb_path, script, args.niche)
        except Exception:
            traceback.print_exc()

    # 10. Publish to YouTube
    _delivered = False
    if args.publish:
        try:
            from pipeline.uploader_youtube import upload as yt_upload
            url = yt_upload(video_path, script, thumb_path=thumb_path,
                            publish_at=_publish_at_iso(_slot_publish_at(args)))
            print(f"[publish] youtube: {url}")
            _delivered = True
        except Exception:
            traceback.print_exc()
    elif args.notify_telegram:
        _delivered = True  # bhajan TG drop already sent above

    if _delivered:
        try:
            from pipeline.publish_log import mark_published
            mark_published("bhajan", "trending", args.seed_offset)
            print("[catchup] marked bhajan as delivered today")
        except Exception:
            traceback.print_exc()

    print(f"[bhajan] DONE → {video_path}")
    return 0


if __name__ == "__main__":
    _argv = sys.argv[1:]
    try:
        _rc = main(_argv)
    except Exception as _e:
        try:
            from pipeline.notifier_discord import alert as _dc_alert
            _dc_alert(f"❌ run.py CRASHED: {type(_e).__name__}: {_e}\nargs: {' '.join(_argv)}")
        except Exception:
            pass
        raise
    if _rc not in (0, None):
        try:
            from pipeline.notifier_discord import alert as _dc_alert
            _dc_alert(f"⚠️ run.py exited rc={_rc} (will be retried/recovered)\nargs: {' '.join(_argv)}")
        except Exception:
            pass
    sys.exit(_rc)
