#!/usr/bin/env python3
"""ANHONI assembler — composite comic bubbles/captions on panels -> Ken Burns
-> ANHONI branding -> suspense music -> 1080x1920 mp4.
  python assemble.py <slug>
Reads story_<slug>.json + out/<slug>/raw/*.png + out/<slug>/music.mp3.
Writes out/<slug>/final.mp4. Fonts resolve on macOS + Linux(CI). Isolated."""
import os, sys, json, math, shutil, subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops, ImageEnhance

OUT = Path(__file__).parent
W, H, FPS = 1080, 1920, 30
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"

def _font(cands, size):
    for p in cands:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()
BOLD = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
BLACK = ["/System/Library/Fonts/Supplemental/Arial Black.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
SERIF = ["/System/Library/Fonts/Supplemental/Georgia Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"]
def F(role, s): return _font(role, s)
GOLD = (214, 176, 110)

def cover(img):
    scale = W / img.width; fw, fh = W, int(img.height * scale); im = img.resize((fw, fh))
    if fh >= H:
        y = (fh - H) // 2; return im.crop((0, y, W, y + H))
    bg = ImageEnhance.Brightness(img.resize((W, H)).filter(ImageFilter.GaussianBlur(45))).enhance(0.5)
    y = (H - fh) // 2; bg.paste(im, (0, y)); return bg

SW, SH = 96, 171
def detail_map(img): return img.convert("L").resize((SW, SH)).filter(ImageFilter.FIND_EDGES).filter(ImageFilter.GaussianBlur(1)).load()
def region_detail(px, x0, y0, x1, y1):
    sx0, sx1 = max(0, int(x0/W*SW)), min(SW, int(x1/W*SW)); sy0, sy1 = max(0, int(y0/H*SH)), min(SH, int(y1/H*SH))
    tot = cnt = 0
    for yy in range(sy0, sy1):
        for xx in range(sx0, sx1): tot += px[xx, yy]; cnt += 1
    return tot / max(cnt, 1)

def wrap(d, t, f, mw):
    out, cur = [], ""
    for w in t.split():
        s = (cur + " " + w).strip()
        if d.textlength(s, font=f) <= mw: cur = s
        else: out.append(cur); cur = w
    if cur: out.append(cur)
    return out
def measure(text):
    d = ImageDraw.Draw(Image.new("RGB", (10, 10))); f = F(SERIF, 42)
    lines = wrap(d, text, f, 360); lh = 54
    tw = max(d.textlength(l, font=f) for l in lines)
    return f, lines, lh, int(tw) + 62, lh * len(lines) + 44

def place(px, bw, bh, speaker):
    m = 44; best = None
    for cyf in (0.19, 0.25, 0.31, 0.85):
        for cxf in (0.26, 0.38, 0.5, 0.62, 0.74):
            cx, cy = int(cxf*W), int(cyf*H); x0, y0, x1, y1 = cx-bw//2, cy-bh//2, cx+bw//2, cy+bh//2
            if x0 < m or x1 > W-m or y0 < m or y1 > H-m: continue
            det = region_detail(px, x0, y0, x1, y1)
            if cyf == 0.85: det *= 1.5
            det += abs(cx - speaker[0]) * 0.004
            if best is None or det < best[0]: best = (det, cx, cy)
    return (best[1], best[2]) if best else (W//2, int(H*0.18))

def cloud_bubble(d, x0, y0, x1, y1):
    cx, cy, a, b = (x0+x1)/2, (y0+y1)/2, (x1-x0)/2, (y1-y0)/2
    r = int(min(a, b)*0.5); n = max(11, int((a+b)/(r*0.82)))
    for i in range(n):
        ang = 2*math.pi*i/n; pxc, pyc = cx+a*math.cos(ang), cy+b*math.sin(ang)
        d.ellipse([pxc-r, pyc-r, pxc+r, pyc+r], fill=(255,255,255,255), outline=(22,22,28,255), width=5)
    d.ellipse([x0, y0, x1, y1], fill=(255,255,255,255))

def draw_bubble(img, text, kind, cx, cy, target):
    d = ImageDraw.Draw(img, "RGBA"); f, lines, lh, bw, bh = measure(text)
    x0, y0, x1, y1 = cx-bw//2, cy-bh//2, cx+bw//2, cy+bh//2
    ddx, ddy = target[0]-cx, target[1]-cy; dd = max(1.0, math.hypot(ddx, ddy)); ux, uy = ddx/dd, ddy/dd
    if kind == "thought":
        cloud_bubble(d, x0, y0, x1, y1)
        nx, ny = cx+(bw/2)*ux, cy+(bh/2)*uy
        for rr, dist in ((20, 22), (13, 50), (8, 74)):
            pxc, pyc = nx+ux*dist, ny+uy*dist
            d.ellipse([pxc-rr, pyc-rr, pxc+rr, pyc+rr], fill=(255,255,255,255), outline=(22,22,28,255), width=4)
    else:
        ea, eb = int(bw*0.70), int(bh*0.82); ex0, ey0, ex1, ey1 = cx-ea, cy-eb, cx+ea, cy+eb
        nx, ny = cx+ea*ux, cy+eb*uy; tl = min(dd*0.4, 50); tx, ty = nx+ux*tl, ny+uy*tl
        pxx, pyy = -uy*22, ux*22
        d.ellipse([ex0+5, ey0+7, ex1+5, ey1+7], fill=(0,0,0,70))
        d.polygon([(nx+pxx, ny+pyy), (nx-pxx, ny-pyy), (tx, ty)], fill=(255,255,255,255))
        d.line([(nx+pxx, ny+pyy), (tx, ty)], fill=(20,20,25,255), width=5)
        d.line([(nx-pxx, ny-pyy), (tx, ty)], fill=(20,20,25,255), width=5)
        d.ellipse([ex0, ey0, ex1, ey1], fill=(255,255,255,255), outline=(20,20,25,255), width=5)
    ty0 = cy - (lh*len(lines))/2
    for i, l in enumerate(lines):
        d.text((cx, ty0+i*lh+lh/2), l, font=f, fill=(20,20,25,255), anchor="mm")

def brand(img):
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle([W//2-150, 36, W//2+150, 90], radius=26, fill=(0,0,0,120))
    d.text((W//2, 63), "A N H O N I", font=F(BLACK, 30), fill=(GOLD[0], GOLD[1], GOLD[2], 245), anchor="mm")

def caption_bar(img, text):
    d = ImageDraw.Draw(img, "RGBA"); f = F(BOLD, 52); lines = wrap(d, text, f, W-200); lh = 70
    bh = lh*len(lines)+46; by = int(H*0.80)
    d.rounded_rectangle([80, by, W-80, by+bh], radius=22, fill=(0,0,0,180))
    for i, l in enumerate(lines):
        d.text((W//2, by+23+i*lh+lh//2), l, font=f, fill=(255,255,255,255), anchor="mm", stroke_width=2, stroke_fill=(0,0,0,255))

DUR = {1:5, 2:5, 3:5, 4:5, 5:5, 6:5, 7:5, 8:5, 9:6, 10:7}

def main(slug):
    spec = json.loads((OUT / f"story_{slug}.json").read_text())
    base = OUT / "out" / slug; raw = base / "raw"; FR = base / "frames"; CLIP = base / "clips"
    for d in (FR, CLIP): d.mkdir(parents=True, exist_ok=True)
    clips = []
    for p in spec["panels"]:
        pid = p["id"]; img = cover(Image.open(raw / f"panel_{pid:02d}.png").convert("RGB")).convert("RGBA")
        px = detail_map(img); sp = p.get("speaker", [0.5, 0.4]); speaker = (int(sp[0]*W), int(sp[1]*H))
        brand(img)
        if p["bubble"] == "caption": caption_bar(img, p["text"])
        else:
            f, lines, lh, bw, bh = measure(p["text"]); cx, cy = place(px, int(bw*1.5), int(bh*1.75), speaker)
            draw_bubble(img, p["text"], p["bubble"], cx, cy, speaker)
        d2 = ImageDraw.Draw(img, "RGBA"); d2.text((W-60, H-48), f"{pid}/10", font=F(BOLD, 26), fill=(255,255,255,150), anchor="mm")
        png = FR / f"p{pid:02d}.png"; img.convert("RGB").save(png)
        dur = DUR.get(pid, 5); fr = int(dur*FPS)
        z, x, y = "min(zoom+0.0012,1.12)", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
        out = CLIP / f"c{pid:02d}.mp4"
        vf = (f"scale=1350:2400,zoompan=z='{z}':x='{x}':y='{y}':d={fr}:s={W}x{H}:fps={FPS},"
              f"fade=t=in:st=0:d=0.3,fade=t=out:st={dur-0.3}:d=0.3,format=yuv420p")
        subprocess.run([FFMPEG, "-y", "-loop", "1", "-i", str(png), "-t", str(dur), "-vf", vf, "-r", str(FPS),
                        "-c:v", "libx264", "-preset", "medium", "-crf", "19", str(out)], check=True, capture_output=True)
        clips.append(out)
    lst = base / "list.txt"; lst.write_text("".join(f"file '{c}'\n" for c in clips))
    silent = base / "silent.mp4"
    subprocess.run([FFMPEG, "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c:v", "libx264", "-crf", "19", "-pix_fmt", "yuv420p", str(silent)], check=True, capture_output=True)
    total = sum(DUR.get(p["id"], 5) for p in spec["panels"])
    final = base / "final.mp4"; music = base / "music.mp3"
    if music.exists():
        subprocess.run([FFMPEG, "-y", "-i", str(silent), "-stream_loop", "-1", "-i", str(music),
            "-filter_complex", f"[1:a]afade=t=in:st=0:d=1.5,afade=t=out:st={total-2}:d=2,loudnorm=I=-16:TP=-1.5[a]",
            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", str(final)], check=True, capture_output=True)
    else:
        shutil.copy(silent, final)
    print("VIDEO ->", final)
    return str(final)

if __name__ == "__main__":
    main(sys.argv[1])
