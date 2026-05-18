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
from pipeline.utils import out_path, slugify, today_stamp


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
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
    args = ap.parse_args(argv)

    print("== Bhakti Reels pipeline ==")

    # 1. topic
    if args.topic and args.topic != "auto":
        topic = pick_topic(args.topic)
    elif args.kind == "shloka":
        topic = pick_shloka_episode()
    elif args.kind == "trending":
        topic = pick_trending()
    else:
        topic = pick_topic("auto")
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
    assemble(script, voice_path, images, video_path)
    print(f"[video] FINAL → {video_path}")

    # 7. publish
    if args.publish:
        try:
            from pipeline.uploader_youtube import upload as yt_upload
            url = yt_upload(video_path, script)
            print(f"[publish] youtube: {url}")
        except Exception:
            traceback.print_exc()
            print("[publish] youtube failed — see traceback above")

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

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
