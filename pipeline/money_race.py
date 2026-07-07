# Reusable "money race" video engine — same code, ANY topic via a spec.
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageOps
import subprocess, asyncio, edge_tts, sys, json
W,H=720,1280; LD="assets/fonts/"; FD=LD
def font(p,s):
    try: return ImageFont.truetype(p,s)
    except: return ImageFont.truetype(LD+"Anton-Regular.ttf",s)
anton=lambda s: font(LD+"Anton-Regular.ttf",s); osw=lambda s: font(LD+"Khand-Bold.ttf",s); bebas=lambda s: font(LD+"BebasNeue-Regular.ttf",s)
PAL=[(233,138,58),(95,176,232),(120,200,150),(199,146,234),(242,207,107),(224,122,95),(157,180,255),(84,217,160),(143,217,182),(232,168,120),(120,190,220),(210,150,190)]
def initials(nm):
    ps=nm.replace('.',' ').split(); 
    return (ps[0][0]+ps[-1][0]).upper() if len(ps)>1 else ps[0][:2].upper()
def valat(pts,yf):
    ks=sorted(pts)
    if yf<=ks[0]: return pts[ks[0]] if yf>=ks[0]-0.001 else None
    if yf>=ks[-1]: return pts[ks[-1]]
    for i in range(len(ks)-1):
        if ks[i]<=yf<=ks[i+1]:
            t=(yf-ks[i])/(ks[i+1]-ks[i]); return pts[ks[i]]+(pts[ks[i+1]]-pts[ks[i]])*t
    return None
def render_race(spec, bgpath, out, duration=None):
    data={nm:({int(y):v for y,v in pts.items()},PAL[i%len(PAL)]) for i,(nm,pts) in enumerate(spec['data'].items())}
    bg=ImageOps.fit(Image.open(bgpath).convert('RGB'),(W,H)).filter(ImageFilter.GaussianBlur(7))
    bg=ImageEnhance.Brightness(bg).enhance(0.30)
    base=Image.alpha_composite(bg.convert('RGBA'),Image.new('RGBA',(W,H),(7,9,15,130)))
    top=352; rowh=82; x0=248; barmax=W-x0-146; N=8; pos={}; unit=spec.get('unit','$'); suf=spec.get('suffix','B')
    y0=min(min(p) for p,_ in data.values()); y1=max(max(p) for p,_ in data.values())
    def frame(yf):
        vals=[(valat(pts,yf),nm,col) for nm,(pts,col) in data.items() if yf>=min(pts)-0.01 and valat(pts,yf) is not None]
        vals.sort(reverse=True); vis=vals[:N]; maxv=max(v for v,_,_ in vis) if vis else 1
        targ={nm:i for i,(v,nm,c) in enumerate(vis)}
        if not pos:
            for nm,i in targ.items(): pos[nm]=i
        for nm in list(pos):
            if nm not in targ: pos[nm]+=(N+1-pos[nm])*0.25
        for nm,i in targ.items(): pos.setdefault(nm,N+1); pos[nm]+=(i-pos[nm])*0.22
        im=base.copy(); d=ImageDraw.Draw(im)
        d.text((W//2,150),spec['title'],font=anton(50),fill=(245,212,120,255),anchor="mm")
        d.text((W//2,198),spec['subtitle'],font=bebas(30),fill=(200,214,236,255),anchor="mm")
        d.text((W//2,278),str(int(yf)),font=anton(96),fill=(245,212,120,255),anchor="mm")
        vmap={nm:(v,c) for v,nm,c in vis}
        for nm,(v,col) in vmap.items():
            yy=top+pos[nm]*rowh
            if yy<top-rowh or yy>H-40: continue
            cy=int(yy+50); bw=max(int(v/maxv*barmax),8)
            d.rounded_rectangle((x0-6,cy-32,x0+bw+6,cy+32),radius=32,fill=col+(70,))
            bar=Image.new("RGBA",(bw,58),(0,0,0,0)); bd=ImageDraw.Draw(bar)
            for xx in range(bw):
                tt=xx/max(bw,1); cc=tuple(int(col[k]*(0.5+0.5*tt)) for k in range(3)); bd.line([(xx,0),(xx,58)],fill=cc+(255,))
            m=Image.new("L",bar.size,0); ImageDraw.Draw(m).rounded_rectangle((0,0,bw,58),radius=29,fill=255); im.paste(bar,(x0,cy-29),m)
            d.ellipse((150,cy-40,230,cy+40),fill=(24,32,50),outline=col+(255,),width=5)
            d.text((190,cy),initials(nm),font=anton(30),fill=(255,255,255),anchor="mm")
            d.text((68,cy),str(targ[nm]+1),font=osw(38),fill=(150,165,190),anchor="mm")
            d.text((x0+18,cy),nm,font=anton(26),fill=(255,255,255),anchor="lm")
            vv=(f"{unit}{v/1000:.1f}T" if (suf=="B" and v>=1000) else f"{unit}{int(round(v)):,}{suf}")
            d.text((W-16,cy),vv,font=osw(30),fill=col,anchor="rm")
        return im.convert("RGB")
    FPS=30; HOLD=48; yrs=list(range(int(y0),int(y1)+1)); steps=max(len(yrs)-1,1)
    # frames-per-year-step: derive from the target duration so the animation
    # is paced to the voiceover instead of racing through whenever a topic
    # spans few years (e.g. crypto 2018-2026 would otherwise finish in ~5s).
    if duration:
        total=max(int(round(duration*FPS)),steps+HOLD)
        per=max(1,int(round((total-HOLD)/steps)))
    else:
        per=13
    p=subprocess.Popen(["ffmpeg","-y","-loglevel","error","-f","image2pipe","-framerate",str(FPS),"-i","-","-vf","format=yuv420p","-c:v","libx264","-crf","20",out],stdin=subprocess.PIPE)
    for yi in range(len(yrs)-1):
        for s in range(per): frame(yrs[yi]+s/per).save(p.stdin,"JPEG",quality=90)
    for _ in range(HOLD): frame(yrs[-1]).save(p.stdin,"JPEG",quality=90)
    p.stdin.close(); p.wait()

def make_card(spec,bgpath,blocks,out):
    bg=ImageOps.fit(Image.open(bgpath).convert('RGB'),(W,H)).filter(ImageFilter.GaussianBlur(9))
    bg=ImageEnhance.Brightness(bg).enhance(0.26)
    im=Image.alpha_composite(bg.convert('RGBA'),Image.new('RGBA',(W,H),(7,9,15,120))); d=ImageDraw.Draw(im)
    for y,txt,f,col in blocks:
        for i,ln in enumerate(txt.split("\n")): d.text((W//2,y+i*66),ln,font=f,fill=col,anchor="mm")
    im.convert("RGB").save(out,quality=92)

def _dur(f): return float(subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",f]).strip())

def assemble(spec, bgpath, outdir, middle_mp4, V, INTRO=4.5):
    """Wrap a pre-rendered middle segment (bar race OR line chart) with the shared
    intro/outro cards and mux the voiceover + background music. The outro is sized so
    the total video length equals the voiceover length V (keeps audio/video in sync).
    _vo.mp3 must already exist in outdir (both formats generate it before pacing)."""
    make_card(spec,bgpath,[(430,spec['intro'][0],anton(66),(245,212,120,255)),(600,spec['intro'][1],bebas(42),(220,228,244,255))],f"{outdir}/_intro.png")
    make_card(spec,bgpath,[(430,spec['outro'][0],anton(78),(245,212,120,255)),(560,spec['outro'][1],osw(32),(230,238,248,255)),(660,spec['outro'][2],bebas(40),(143,217,182,255)),(850,spec['outro'][3],osw(30),(150,165,190,255))],f"{outdir}/_outro.png")
    R=_dur(middle_mp4); O=max(4.0,V-INTRO-R)   # keep total video length == voiceover length
    def clip(png,t,o): subprocess.run(["ffmpeg","-y","-loglevel","error","-loop","1","-i",png,"-t",str(t),"-r","30","-vf","scale=720:1280,format=yuv420p","-c:v","libx264",o])
    clip(f"{outdir}/_intro.png",INTRO,f"{outdir}/_i.mp4"); clip(f"{outdir}/_outro.png",O,f"{outdir}/_o.mp4")
    subprocess.run(["ffmpeg","-y","-loglevel","error","-i",middle_mp4,"-r","30","-vf","scale=720:1280,format=yuv420p","-c:v","libx264",f"{outdir}/_r.mp4"])
    open(f"{outdir}/_l.txt","w").write(f"file '_i.mp4'\nfile '_r.mp4'\nfile '_o.mp4'\n")
    subprocess.run(["ffmpeg","-y","-loglevel","error","-f","concat","-safe","0","-i","_l.txt","-c:v","libx264","-pix_fmt","yuv420p","-r","30","_s.mp4"],cwd=outdir)
    subprocess.run(["ffmpeg","-y","-loglevel","error","-i",f"{outdir}/_s.mp4","-i",f"{outdir}/_vo.mp3","-i","assets/money_race/music.mp3","-filter_complex","[1:a]volume=1.0[vo];[2:a]afade=t=in:st=0:d=1,volume=0.19[bg];[vo][bg]amix=inputs=2:duration=first:dropout_transition=0[a]","-map","0:v","-map","[a]","-c:v","libx264","-crf","20","-c:a","aac","-b:a","192k","-shortest",spec['out']])
    print("VIDEO DONE:",spec['out'])

def make_video(spec, bgpath, outdir):
    # Voiceover FIRST, so the race animation can be paced to match the narration.
    asyncio.run(edge_tts.Communicate(spec['vo'],'en-US-ChristopherNeural',rate='+6%').save(f"{outdir}/_vo.mp3"))
    V=_dur(f"{outdir}/_vo.mp3")
    INTRO=4.5                                # intro card (voice sets the scene over it)
    OUTRO=max(4.0,min(6.0,V*0.16))           # closing CTA card
    race_target=max(6.0,V-INTRO-OUTRO)       # race fills the middle span of the voiceover
    render_race(spec,bgpath,f"{outdir}/_race.mp4",duration=race_target)
    assemble(spec,bgpath,outdir,f"{outdir}/_race.mp4",V,INTRO)

if __name__=="__main__":
    spec=json.load(open(sys.argv[1]))
    import os; os.makedirs("output/money_races",exist_ok=True); make_video(spec,"assets/money_race/bg.jpg","output/money_races")
