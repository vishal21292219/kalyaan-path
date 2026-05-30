"""End-to-end pipeline: topic → script → tts → images → video → (publish)."""
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
from pipeline.utils import load_config, out_path, set_active_niche, slugify, today_stamp


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--niche", default="bhakti",
        choices=["bhakti", "itihaas", "bhajan", "ancient"],
        help="Which niche to run (bhakti = KalyaanPath; itihaas = Itihaasvani; bhajan = Flow Music MP3; ancient = Ancient World Decoded English)",
    )
    ap.add_argument(
        "--deity",
        choices=["hanuman", "krishna", "shiva", "ram", "devi", "ganesh", "sai", "general"],
        help="For --niche bhajan: pick MP3 from data/music_bhajan/[deity]/. If omitted, scans all deity folders.",
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
    args = ap.parse_args(argv)
    if args.notify_telegram:
        args.auto_thumb = True

    set_active_niche(args.niche)
    print(f"== Reels pipeline ({args.niche}) ==")

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
    script_path = out_path("scripts", f"{base}.json")
    script_path.write_text(json.dumps(script, indent=2, ensure_ascii=False))

    # 4. TTS voiceover (always realtime — fast + deterministic, not worth caching)
    voice_path = out_path("audio", f"{base}.mp3")
    synthesize(script, voice_path, seed_offset=args.seed_offset)
    print(f"[tts] saved → {voice_path}")

    # 5. images — pregen cache wins, else realtime gen
    img_dir = out_path("images", base)
    _img_cfg = load_config().get("images", {})
    footage_mode = str(_img_cfg.get("mode", "image")).lower() == "footage" and not args.long_form
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
    _telegram_only = bool(args.notify_telegram) and not args.publish
    _skip_music = args.no_music or _telegram_only
    if _telegram_only and not args.no_music:
        print("[audio] Telegram drop → background music OFF (add trending audio at upload)")
    assemble(script, voice_path, images, video_path, skip_music=_skip_music, skip_captions=args.skip_captions, long_form=args.long_form, hero_clips=hero_clips)
    print(f"[video] FINAL → {video_path}{' (no-music)' if _skip_music else ''}")

    # 6b. thumbnail — pregen cache wins, else realtime gen
    thumb_path = None
    if args.auto_thumb:
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

    # 6d. notify Telegram (optional)
    if args.notify_telegram:
        try:
            from pipeline.notifier_telegram import notify as tg_notify
            tg_notify(video_path, thumb_path, script, args.niche, seed_offset=args.seed_offset)
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
                url = yt_upload(video_path, script)
                print(f"[publish] youtube: {url}")
            except Exception:
                traceback.print_exc()
                print("[publish] youtube failed — see traceback above")
        else:
            print("[publish] skipped youtube (disabled in config)")

        if publish_cfg.get("instagram", False):
            if args.public_url:
                try:
                    from pipeline.uploader_instagram import upload as ig_upload
                    media_id = ig_upload(args.public_url, script)
                    print(f"[publish] instagram: {media_id}")
                except Exception:
                    traceback.print_exc()
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

    return 0


# ─── Bhajan mode ─────────────────────────────────────────────────────────
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
            "hanuman", "krishna", "shiva", "ram", "devi", "ganesh", "sai", "general"
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
    scene_prompts = generate_scene_prompts(deity, n_scenes)

    # 3. Generate images
    img_dir = out_path("images", base)
    images = _generate_images(scene_prompts, img_dir)
    if not images:
        print("[bhajan] image generation failed entirely")
        return 1
    print(f"[bhajan] {len(images)} scene images ready")

    # 4. Assemble video
    video_path = out_path("videos", f"{base}.mp4")
    assemble_bhajan_video(mp3, images, video_path)

    # 5. Build script-like metadata for thumbnail/telegram/upload
    script = build_bhajan_metadata(deity, mp3.stem)
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
    if args.publish:
        try:
            from pipeline.uploader_youtube import upload as yt_upload
            url = yt_upload(video_path, script)
            print(f"[publish] youtube: {url}")
        except Exception:
            traceback.print_exc()

    print(f"[bhajan] DONE → {video_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
