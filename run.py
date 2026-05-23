"""End-to-end pipeline: topic → script → tts → images → video → (publish)."""
import argparse
import json
import sys
import traceback
from pathlib import Path

from pipeline.assembler import assemble
from pipeline.image_gen import generate_images
from pipeline.scraper import gather_context
from pipeline.script_writer import write_script
from pipeline.topic_generator import pick_shloka_episode, pick_topic, pick_trending
from pipeline.tts import synthesize
from pipeline.utils import out_path, set_active_niche, slugify, today_stamp


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--niche", default="bhakti",
        choices=["bhakti", "itihaas"],
        help="Which niche to run (bhakti = KalyaanPath; itihaas = Itihaas Rahasya)",
    )
    ap.add_argument(
        "--kind", default="auto",
        choices=["auto", "shloka", "trending"],
        help="auto = legacy daily rotation; shloka = next Gita verse episode; trending = current festival or popular deity",
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
    args = ap.parse_args(argv)
    if args.notify_telegram:
        args.auto_thumb = True

    set_active_niche(args.niche)
    print(f"== Reels pipeline ({args.niche}) ==")

    # 1. topic
    if args.topic and args.topic != "auto":
        topic = pick_topic(args.topic, seed_offset=args.seed_offset)
    elif args.kind == "shloka":
        topic = pick_shloka_episode()
    elif args.kind == "trending":
        topic = pick_trending(seed_offset=args.seed_offset)
    else:
        topic = pick_topic("auto", seed_offset=args.seed_offset)
    print(f"[topic] {topic}")

    stamp = today_stamp()
    slug = slugify(topic["title"])
    base = f"{stamp}_{slug}"

    # 2. scrape context
    context = gather_context(topic)
    print(f"[scrape] context length: {len(context)}")

    # 3. script via LLM
    script = write_script(topic, context)
    # attach topic metadata so assembler can render episode badge / verse overlay
    for key in ("kind", "episode_number", "ref", "verse", "theme"):
        if key in topic and key not in script:
            script[key] = topic[key]
    script_path = out_path("scripts", f"{base}.json")
    script_path.write_text(json.dumps(script, indent=2, ensure_ascii=False))
    print(f"[script] saved → {script_path}")
    print(f"[script] title: {script.get('title')}")

    # 4. TTS voiceover
    voice_path = out_path("audio", f"{base}.mp3")
    synthesize(script, voice_path)
    print(f"[tts] saved → {voice_path}")

    # 5. images
    img_dir = out_path("images", base)
    if args.skip_images and img_dir.exists() and any(img_dir.iterdir()):
        images = sorted(img_dir.glob("img_*.jpg"))
        print(f"[images] reusing {len(images)} cached")
    else:
        images = generate_images(script["visuals"], img_dir)
        print(f"[images] generated {len(images)}")

    # 6. assemble
    video_path = out_path("videos", f"{base}.mp4")
    assemble(script, voice_path, images, video_path, skip_music=args.no_music)
    print(f"[video] FINAL → {video_path}{' (no-music)' if args.no_music else ''}")

    # 6b. thumbnail (optional)
    thumb_path = None
    if args.auto_thumb:
        try:
            from pipeline.thumbnail_gen import make_thumbnail
            thumb_path = out_path("thumbnails", f"{base}.jpg")
            make_thumbnail(script, args.niche, thumb_path)
        except Exception:
            traceback.print_exc()
            print("[thumbnail] generation failed — continuing without")

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
            tg_notify(video_path, thumb_path, script, args.niche)
        except Exception:
            traceback.print_exc()
            print("[telegram] notify failed")

    # 7. publish
    if args.publish:
        from pipeline.utils import load_config
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

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
