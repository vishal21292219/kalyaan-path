"""Append the auto-generated thumbnail as a static end card to the assembled
video. Helps YouTube Shorts replay-hook + acts as branded outro.

The endcard:
- Lasts `duration_sec` (default 2.5)
- Matches video's resolution + fps + sar
- Has silent audio (anullsrc) to keep AV streams aligned during concat
- Optional gentle audio fade-out on the source video for smooth handoff
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


def _probe(video_path: Path) -> dict:
    r = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_streams", "-show_format",
            "-of", "json", str(video_path),
        ],
        capture_output=True, text=True,
    )
    return json.loads(r.stdout)


def append_thumbnail_endcard(
    video_path: Path,
    thumbnail_path: Path,
    duration_sec: float = 2.5,
    audio_fade_sec: float = 0.6,
) -> Path:
    """Append the thumbnail as static end card to the end of video.
    Audio on source video fades out during the last `audio_fade_sec` so the
    handoff to silent endcard feels intentional. Replaces the original file.
    """
    if not video_path.exists():
        print(f"[endcard] video not found: {video_path}")
        return video_path
    if not thumbnail_path or not Path(thumbnail_path).exists():
        print(f"[endcard] thumbnail not found, skipping")
        return video_path

    meta = _probe(video_path)
    video_stream = next((s for s in meta["streams"] if s["codec_type"] == "video"), None)
    audio_stream = next((s for s in meta["streams"] if s["codec_type"] == "audio"), None)
    if not video_stream:
        print(f"[endcard] no video stream — skipping")
        return video_path

    W = int(video_stream["width"])
    H = int(video_stream["height"])
    fps_str = video_stream.get("r_frame_rate", "30/1")
    try:
        num, den = fps_str.split("/")
        fps = max(1, int(round(int(num) / max(int(den), 1))))
    except Exception:
        fps = 30
    src_duration = float(meta["format"]["duration"])

    work = video_path.parent / f"_endcard_{video_path.stem}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)
    final = work / "with_endcard.mp4"

    # Build a single-pass ffmpeg filter_complex that:
    #   1. Re-emits source video, fading audio in last audio_fade_sec
    #   2. Loops thumbnail for duration_sec at matched size/fps
    #   3. Synthesizes silent audio of duration_sec to pair with endcard
    #   4. Concats both streams
    fade_start = max(0.0, src_duration - audio_fade_sec)
    has_audio = audio_stream is not None

    inputs = [
        "-i", str(video_path),                                # 0: source
        "-loop", "1", "-t", f"{duration_sec:.2f}",
        "-i", str(thumbnail_path),                            # 1: thumbnail image
    ]
    if has_audio:
        inputs += [
            "-f", "lavfi",
            "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100",  # 2: silence (duration limited via -shortest in concat)
        ]

    if has_audio:
        filter_complex = (
            f"[1:v]scale={W}:{H}:flags=lanczos,setsar=1,fps={fps},format=yuv420p[end];"
            f"[0:v][end]concat=n=2:v=1:a=0[outv];"
            f"[0:a]afade=t=out:st={fade_start:.2f}:d={audio_fade_sec:.2f}[srcafade];"
            f"[2:a]atrim=duration={duration_sec:.2f}[sil];"
            f"[srcafade][sil]concat=n=2:v=0:a=1[outa]"
        )
        map_args = ["-map", "[outv]", "-map", "[outa]"]
    else:
        filter_complex = (
            f"[1:v]scale={W}:{H}:flags=lanczos,setsar=1,fps={fps},format=yuv420p[end];"
            f"[0:v][end]concat=n=2:v=1:a=0[outv]"
        )
        map_args = ["-map", "[outv]"]

    cmd = (
        ["ffmpeg", "-y", *inputs,
         "-filter_complex", filter_complex,
         *map_args,
         "-c:v", "libx264", "-preset", "fast", "-crf", "20",
         "-pix_fmt", "yuv420p",
         "-color_range", "tv", "-movflags", "+faststart"]
        + (["-c:a", "aac", "-b:a", "192k"] if has_audio else [])
        + [str(final)]
    )
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"[endcard] FAILED — keeping original. ffmpeg stderr:\n{r.stderr[-800:]}")
        shutil.rmtree(work, ignore_errors=True)
        return video_path

    shutil.move(str(final), str(video_path))
    shutil.rmtree(work, ignore_errors=True)
    print(f"[endcard] appended {duration_sec:.1f}s thumbnail endcard (audio fade {audio_fade_sec}s)")
    return video_path
