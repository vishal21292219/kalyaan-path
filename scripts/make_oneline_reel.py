#!/usr/bin/env python3
"""ONE-LINE REEL — one image, one sentence, ~7 seconds, no narration.

WHY THIS FORMAT
---------------
Measured on Awakeners (151K, the closest comparable page): their best reel that
is actually THEIRS — as opposed to a reposted viral clip — is exactly this. One
AI image, one line of text, no voice: "Anyone who abandons you is teaching you",
427 likes, 5 comments, 274 shares, 92 saves on 22K views. A 1.25% share rate,
better than anything the scripted long-form reels on this channel have done.

It costs almost nothing next to a scripted reel: one image instead of twelve, no
ElevenLabs, no caption passes, no motion clip. And because there is no narration,
it is the only reel format on this channel that can carry FACEBOOK'S OWN TRENDING
AUDIO — which the Business Suite composer does expose, and which the API path
cannot reach at all. On a narrated reel a trending track just fights the voice.

Output is 1080x1920 so it posts as a reel, not a photo.

    python scripts/make_oneline_reel.py --count 2
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import photo_post                                    # noqa: E402
from pipeline.utils import load_config                             # noqa: E402

W, H = 1080, 1920
DUR = 7.0


def _compose_vertical(raw: Path, line: str, deity: str, out: Path) -> Path:
    """Same type treatment as the photo lane, re-laid for 9:16."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.open(raw).convert("RGB")
    # fill 9:16 by cropping the sides, keeping the top (the face sits high)
    sw, sh = img.size
    want = W / H
    if sw / sh > want:
        nw = int(sh * want)
        img = img.crop(((sw - nw) // 2, 0, (sw - nw) // 2 + nw, sh))
    else:
        nh = int(sw / want)
        img = img.crop((0, 0, sw, nh))
    img = img.resize((W, H), Image.LANCZOS)

    margin = 90
    font, lines = photo_post._layout(line, W - 2 * margin)
    line_h = int(font.size * 1.26)
    baseline = H - 210                      # higher than 4:5 — reel UI sits lower
    y0 = baseline - line_h * len(lines)
    _a1, _a2 = photo_post.ALPHA_AT_TEXT, photo_post.ALPHA_AT_FOOT
    photo_post.ALPHA_AT_TEXT, photo_post.ALPHA_AT_FOOT = 215, 238
    img = photo_post._scrim(img, text_top=y0)
    photo_post.ALPHA_AT_TEXT, photo_post.ALPHA_AT_FOOT = _a1, _a2
    draw = ImageDraw.Draw(img)
    photo_post._draw_accented(draw, lines, font, deity, y0, line_h)
    mark = ImageFont.truetype(str(photo_post.FONT_MARK), 32)
    mark.set_variation_by_axes([600])
    t = "G O D S   O F   T H E   M I N D"
    draw.text(((W - mark.getlength(t)) / 2, H - 170), t, font=mark, fill=photo_post.GOLD)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=94)
    return out


def _to_video(still: Path, out: Path, dur: float = DUR) -> Path:
    """Slow push-in. Deliberately gentle: the frame IS the content here, and a
    hard move would fight the line the viewer is reading."""
    fps = 30
    frames = int(dur * fps)
    vf = (f"scale={W*2}:{H*2},"
          f"zoompan=z='min(zoom+0.0006,1.10)':d={frames}:"
          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={fps},"
          f"format=yuv420p")
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(still),
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-vf", vf, "-t", str(dur), "-c:v", "libx264", "-preset", "slow",
        "-b:v", "2500k", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
        "-shortest", "-movflags", "+faststart", str(out)], check=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=2)
    ap.add_argument("--out", default="output/oneline")
    a = ap.parse_args()

    cfg = load_config()
    niche = cfg.get("niche") or "godmind"
    pool_path = ROOT / f"data/photo_lines_{niche}.json"
    pool = json.loads(pool_path.read_text())
    out_dir = ROOT / a.out
    out_dir.mkdir(parents=True, exist_ok=True)

    made = []
    for item in pool:
        if len(made) >= a.count:
            break
        if item.get("built_at") or item.get("posted_at") or item.get("oneline_at"):
            continue
        try:
            # 9:16 generation, then the gate — a bad frame must not become a reel
            res = photo_post.build(item, out_dir / "_src")
        except Exception as e:
            print(f"[oneline] REJECTED [{item['deity']}] {str(e)[:100]}")
            continue
        slug = Path(res["image"]).stem
        still = _compose_vertical(Path(res["raw"]), item["line"], item["deity"],
                                  out_dir / f"{slug}_9x16.jpg")
        vid = _to_video(still, out_dir / f"{slug}.mp4")
        item["oneline_at"] = "built"
        made.append((item["deity"], item["line"], vid))
        mb = vid.stat().st_size / 1048576
        print(f"[oneline] {vid.name}  {mb:.1f} MB  [{item['deity']}]")
        print(f"[oneline]   {item['line']}")

    pool_path.write_text(json.dumps(pool, ensure_ascii=False, indent=2))
    print(f"\n[oneline] built {len(made)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
