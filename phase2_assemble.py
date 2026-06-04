"""Phase 2 (project .venv): align cloned voice -> images -> assemble -> Telegram."""
import json, os, subprocess, sys
from pathlib import Path

for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

from pipeline.utils import set_active_niche, out_path, load_config
from pipeline.tts import _whisper_align, _build_text
from pipeline.image_gen import generate_images
from pipeline.assembler import assemble

set_active_niche("itihaas")
job = json.load(open("/tmp/clone_job.json"))
base = job["base"]
script = json.loads(Path(job["script_path"]).read_text())

# 1. cloned voice wav -> project audio mp3
voice_path = out_path("audio", f"{base}.mp3")
voice_path.parent.mkdir(parents=True, exist_ok=True)
subprocess.run(["ffmpeg","-y","-i",job["out_wav"],"-codec:a","libmp3lame","-q:a","2",str(voice_path)],
               capture_output=True)
print("[voice] cloned narration ->", voice_path)

# 2. whisper align -> words.json (Devanagari mapped)
text = _build_text(script)
boundaries = _whisper_align(voice_path, original_text=text, language="hi", model_size="medium")
words_path = voice_path.with_suffix(".words.json")
words_path.write_text(json.dumps(boundaries, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[align] {len(boundaries)} word boundaries -> {words_path.name}")

# 3. images (fal)
img_dir = out_path("images", base)
images = generate_images(script["visuals"], img_dir, long_form=False,
                         character_bible=script.get("character_bible"))
print(f"[images] generated {len(images)}")

# 4. assemble WITH soft music + word-by-word captions
video_path = out_path("videos", f"{base}.mp4")
assemble(script, voice_path, images, video_path,
         skip_music=False, skip_captions=False, long_form=False, hero_clips=None)
print("[video] FINAL ->", video_path)

# 5. thumbnail + endcard
thumb_path = out_path("thumbnails", f"{base}.jpg")
try:
    from pipeline.thumbnail_gen import make_thumbnail
    make_thumbnail(script, "itihaas", thumb_path, long_form=False, img_dir=img_dir)
    from pipeline.endcard import append_thumbnail_endcard
    append_thumbnail_endcard(video_path, thumb_path, duration_sec=2.5)
    print("[thumb] ->", thumb_path)
except Exception as e:
    import traceback; traceback.print_exc(); thumb_path = None

print("ASSEMBLE_DONE", video_path)
