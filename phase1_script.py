"""Phase 1 (project .venv): fresh Itihaasvani topic + Hindi script.
Writes script JSON + a clone job (narration lines) for the OmniVoice step."""
import json, os, sys
from pathlib import Path

# load .env
for line in Path(".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

from pipeline.utils import set_active_niche, out_path, slugify, today_stamp
from pipeline.topic_generator import pick_trending
from pipeline.scraper import gather_context
from pipeline.script_writer import write_script

SEED = 1
set_active_niche("itihaas")
topic = pick_trending(seed_offset=SEED)
print("[topic]", topic.get("title"))

context = gather_context(topic)
script = write_script(topic, context, long_form=False)
for key in ("kind", "episode_number", "ref", "verse", "theme"):
    if key in topic and key not in script:
        script[key] = topic[key]

stamp = today_stamp()
slug = slugify(script["title"])
base = f"{stamp}_{slug}_myvoice"
script_path = out_path("scripts", f"{base}.json")
script_path.write_text(json.dumps(script, indent=2, ensure_ascii=False))
print("[script] title:", script["title"])
print("[script] saved:", script_path)

# narration lines (Devanagari) for OmniVoice
lines = [script["hook"], *script["body"], script["cta"]]
lines = [l.strip() for l in lines if l and l.strip()]
job = {
    "base": base,
    "script_path": str(script_path),
    "lines": lines,
    "ref_audio": "/tmp/ref_clone.wav",
    "ref_text_file": "/tmp/ref_text.txt",
    "out_wav": f"/tmp/{base}_voice.wav",
}
Path("/tmp/clone_job.json").write_text(json.dumps(job, ensure_ascii=False, indent=2))
print("[job] wrote /tmp/clone_job.json  lines:", len(lines))
print("PHASE1_DONE", base)
