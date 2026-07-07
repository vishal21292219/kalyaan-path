# Animated line-chart comparison — same spec/pipeline as money_race, different visual.
# Lines grow left-to-right over time, a date label advances, and each line carries a
# live value label + colored dot at its growing tip (dhanhq "SIP vs LIC" style).
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance, ImageOps
import subprocess, asyncio, edge_tts, sys, json, os, math
from pipeline.money_race import W, H, anton, osw, bebas, valat, PAL, assemble

MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
PX0, PX1 = 96, 556          # plot x-range (right gutter reserved for value labels)
PY0, PY1 = 392, 1112        # plot y-range (top below title, bottom above caption)

def _fmt(v, unit, suf):
    if suf == "B" and v >= 1000: return f"{unit}{v/1000:.1f}T"
    return f"{unit}{int(round(v)):,}{suf}"

def _gridfmt(v, unit):      # compact axis tick label, e.g. $1K / $10K / $1M
    for div, s in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if v >= div: return f"{unit}{int(v/div)}{s}"
    return f"{unit}{int(v)}"

def _prep(spec, bgpath):
    """Precompute series, scales and the static title/background layer (done once)."""
    data = {nm: ({int(y): val for y, val in pts.items()}, PAL[i % len(PAL)])
            for i, (nm, pts) in enumerate(spec['data'].items())}
    N = int(spec.get('max_lines', 6))
    if len(data) > N:  # keep the N highest-finishing series so the chart stays readable
        top = sorted(data.items(), key=lambda kv: kv[1][0][max(kv[1][0])], reverse=True)[:N]
        data = dict(top)
    y0 = min(min(p) for p, _ in data.values()); y1 = max(max(p) for p, _ in data.values())
    ymax = max(max(p.values()) for p, _ in data.values())
    vmin = max(1, min(min(p.values()) for p, _ in data.values()))
    unit = spec.get('unit', '$'); suf = spec.get('suffix', '')
    # Log scale: money data spans huge ranges (1000 -> 165000), so a linear axis
    # collapses every "loser" onto the baseline. Log spreads each line to its own
    # height — the winner still tops out, but gentle growers stay visible & readable.
    lo, hi = math.log10(vmin), math.log10(ymax)
    ticks = [10 ** e for e in range(int(math.floor(lo)), int(math.ceil(hi)) + 1) if lo <= e <= hi]
    bg = ImageOps.fit(Image.open(bgpath).convert('RGB'), (W, H)).filter(ImageFilter.GaussianBlur(7))
    bg = ImageEnhance.Brightness(bg).enhance(0.30)
    base = Image.alpha_composite(bg.convert('RGBA'), Image.new('RGBA', (W, H), (7, 9, 15, 140)))
    bd = ImageDraw.Draw(base)
    title = spec['title']; tf = anton(50)
    tb = bd.textbbox((0, 0), title, font=tf); tw = tb[2] - tb[0]
    bd.rounded_rectangle((W//2 - tw//2 - 26, 120, W//2 + tw//2 + 26, 198), radius=14, fill=(228, 222, 52, 255))
    bd.text((W//2, 159), title, font=tf, fill=(16, 16, 20, 255), anchor="mm")
    bd.text((W//2, 236), spec['subtitle'], font=bebas(34), fill=(226, 232, 244, 255), anchor="mm")
    return {"data": data, "y0": y0, "y1": y1, "ymax": ymax, "vmin": vmin, "lo": lo, "hi": hi,
            "ticks": ticks, "unit": unit, "suf": suf, "base": base}

def _frame(prep, tcur):
    data, y0, y1 = prep["data"], prep["y0"], prep["y1"]
    lo, hi, vmin = prep["lo"], prep["hi"], prep["vmin"]
    unit, suf = prep["unit"], prep["suf"]
    xt = lambda t: PX0 + (t - y0) / max(y1 - y0, 1) * (PX1 - PX0)
    yv = lambda v: PY1 - (math.log10(max(v, vmin)) - lo) / max(hi - lo, 1e-6) * (PY1 - PY0)
    im = prep["base"].copy(); d = ImageDraw.Draw(im)
    for tk in prep["ticks"]:                                                     # decade gridlines
        gy = yv(tk)
        d.line([(PX0, gy), (PX1 + 24, gy)], fill=(120, 132, 156, 55), width=2)
        d.text((PX0 - 10, gy), _gridfmt(tk, unit), font=bebas(22), fill=(150, 165, 190, 220), anchor="rm")
    d.line([(PX0, PY0), (PX0, PY1)], fill=(120, 132, 156, 170), width=3)         # y-axis
    d.line([(PX0, PY1), (PX1 + 24, PY1)], fill=(120, 132, 156, 170), width=3)    # baseline
    tips = []
    for nm, (pts, col) in data.items():
        s0, s1 = min(pts), max(pts)
        if tcur < s0: continue
        tend = min(tcur, s1)
        n = max(2, int((tend - s0) / 0.08) + 1)
        poly = []
        for k in range(n):
            tt = s0 + (tend - s0) * k / (n - 1)
            vv = valat(pts, tt)
            if vv is not None: poly.append((xt(tt), yv(vv)))
        if len(poly) >= 2:
            d.line(poly, fill=(10, 12, 18, 255), width=9, joint="curve")          # dark outline
            d.line(poly, fill=col + (255,), width=5, joint="curve")               # colored stroke
        vend = valat(pts, tend)
        if vend is not None:
            tips.append((yv(vend), xt(tend), nm, col, vend))
    # value labels at each line's tip, nudged apart vertically so they never overlap
    tips.sort()
    lasty = -1e9
    for ty, tx, nm, col, vend in tips:
        ly = max(ty, lasty + 54); lasty = ly
        d.ellipse((tx - 10, ty - 10, tx + 10, ty + 10), fill=col + (255,), outline=(12, 16, 24, 255), width=3)
        lx = min(int(tx) + 20, PX1 + 10)
        d.text((lx, ly - 15), nm, font=osw(28), fill=(255, 255, 255, 255), anchor="lm")
        d.text((lx, ly + 15), _fmt(vend, unit, suf), font=osw(28), fill=col + (255,), anchor="lm")
    mo = MONTHS[min(11, int((tcur % 1) * 12))]                                     # advancing date
    d.text((PX0 + 18, PY0 + 30), f"{mo} {int(tcur)}", font=anton(40), fill=(245, 212, 120, 235), anchor="lm")
    return im.convert("RGB")

def render_line(spec, bgpath, out, duration=None):
    prep = _prep(spec, bgpath)
    cap = spec.get('caption')
    def frame(tcur):
        im = _frame(prep, tcur)
        if cap:
            d = ImageDraw.Draw(im)
            for i, ln in enumerate(cap.split("\n")):
                d.text((W // 2, 1158 + i * 30), ln, font=bebas(24), fill=(178, 190, 210), anchor="mm")
        return im
    FPS = 30
    total = max(int(round((duration or 13) * FPS)), 30)
    HOLD = int(FPS * 1.6)
    p = subprocess.Popen(["ffmpeg","-y","-loglevel","error","-f","image2pipe","-framerate",str(FPS),
                          "-i","-","-vf","format=yuv420p","-c:v","libx264","-crf","20",out], stdin=subprocess.PIPE)
    for f in range(total):
        tcur = prep["y0"] + (prep["y1"] - prep["y0"]) * f / max(total - 1, 1)
        frame(tcur).save(p.stdin, "JPEG", quality=90)
    for _ in range(HOLD):
        frame(prep["y1"]).save(p.stdin, "JPEG", quality=90)
    p.stdin.close(); p.wait()

def make_video(spec, bgpath, outdir):
    def dur(f): return float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",f]).strip())
    asyncio.run(edge_tts.Communicate(spec['vo'], 'en-US-ChristopherNeural', rate='+6%').save(f"{outdir}/_vo.mp3"))
    V = dur(f"{outdir}/_vo.mp3")
    INTRO = 4.5; OUTRO = max(4.0, min(6.0, V * 0.16))
    target = max(6.0, V - INTRO - OUTRO)          # line growth fills the middle of the narration
    render_line(spec, bgpath, f"{outdir}/_line.mp4", duration=target)
    assemble(spec, bgpath, outdir, f"{outdir}/_line.mp4", V, INTRO)

if __name__ == "__main__":
    spec = json.load(open(sys.argv[1]))
    os.makedirs("output/money_races", exist_ok=True)
    make_video(spec, "assets/money_race/bg.jpg", "output/money_races")
