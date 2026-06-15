#!/usr/bin/env python3
"""Generalized Lakeerein renderer. Input: a story JSON spec. Output: final mp4.
  python render_story.py story.json
Self-contained: per-line Chem narration (eleven_v3) -> render locked stickman
over premium library backgrounds with correct emotion+motion -> mux voice+music.
No captions. Standalone, touches nothing else."""
import math, sys, subprocess, shutil, json, os
from pathlib import Path
from PIL import Image, ImageDraw, ImageEnhance, ImageChops, ImageFilter

OUT=Path(__file__).parent
ENV=Path.home()/"Documents/Vishal Projects/bhakti-reels/.env"
if ENV.exists():  # local only; on CI secrets are already in os.environ
    for l in ENV.read_text().splitlines():
        if "=" in l and not l.strip().startswith("#"):
            k,v=l.split("=",1); os.environ.setdefault(k.strip(),v.strip())
import requests
W,H,FPS=720,1280,30
DARK=(28,28,36); WHITE=(252,252,254)
VOICE_ID="g66sJwhqbl8rk5CtPVKH"; MODEL="eleven_v3"; EL=os.environ["ELEVENLABS_API_KEY"]

def adur(p):
    o=subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0",str(p)],capture_output=True,text=True)
    return float(o.stdout.strip() or 0)

def line(d,pts,w): d.line(pts,fill=DARK,width=w+6,joint="curve"); d.line(pts,fill=WHITE,width=w,joint="curve")
def dot(d,p,r,col=WHITE): d.ellipse([p[0]-r-2,p[1]-r-2,p[0]+r+2,p[1]+r+2],fill=DARK); d.ellipse([p[0]-r,p[1]-r,p[0]+r,p[1]+r],fill=col)
def face(d,hc,r,emo):
    ex=0.34*r; ey=hc[1]-0.12*r; ew=max(2,int(0.07*r))
    if emo=="happy":
        for sx in(-1,1): line(d,[(hc[0]+sx*ex-0.18*r,ey+0.05*r),(hc[0]+sx*ex,ey-0.12*r),(hc[0]+sx*ex+0.18*r,ey+0.05*r)],ew)
    elif emo=="excited":
        for sx in(-1,1): dot(d,(hc[0]+sx*ex,ey),max(3,int(0.14*r)))
        line(d,[(hc[0]-0.55*r,ey-0.4*r),(hc[0]-0.18*r,ey-0.5*r)],ew); line(d,[(hc[0]+0.18*r,ey-0.5*r),(hc[0]+0.55*r,ey-0.4*r)],ew)
    else:
        for sx in(-1,1): dot(d,(hc[0]+sx*ex,ey),max(2,int(0.1*r)))
    if emo in("sad","wistful"):
        line(d,[(hc[0]-0.55*r,ey-0.12*r),(hc[0]-0.16*r,ey-0.4*r)],ew); line(d,[(hc[0]+0.16*r,ey-0.4*r),(hc[0]+0.55*r,ey-0.12*r)],ew)
    my=hc[1]+0.42*r; mw=0.3*r
    if emo in("happy","excited"): d.arc([hc[0]-mw,my-0.3*r,hc[0]+mw,my+0.3*r],10,170,fill=WHITE,width=max(3,int(0.09*r)))
    elif emo=="sad":
        d.arc([hc[0]-mw,my+0.05*r,hc[0]+mw,my+0.5*r],190,350,fill=WHITE,width=max(3,int(0.09*r)))
        d.ellipse([hc[0]-ex-0.04*r,ey+0.3*r,hc[0]-ex+0.05*r,ey+0.55*r],fill=(120,180,235))
    else: d.line([(hc[0]-0.2*r,my),(hc[0]+0.2*r,my)],fill=WHITE,width=max(3,int(0.08*r)))
def stick(d,cx,hy,s,pose,emo,col=WHITE):
    A=lambda j:(cx+pose[j][0]*s,hy+pose[j][1]*s); w=max(4,int(12*s/110))
    hip=(cx,hy); neck=A("neck")
    for seg in([hip,neck],[hip,A("lk"),A("lf")],[hip,A("rk"),A("rf")],[neck,A("le"),A("lh")],[neck,A("re"),A("rh")]):
        if col!=WHITE: d.line(seg,fill=col,width=w,joint="curve")
        else: line(d,seg,w)
    for h in("lh","rh"): dot(d,A(h),max(3,int(0.06*s)),col)
    hc=A("head"); r=int(0.7*s)
    if col!=WHITE: d.ellipse([hc[0]-r,hc[1]-r,hc[0]+r,hc[1]+r],outline=col,width=w)
    else:
        d.ellipse([hc[0]-r-3,hc[1]-r-3,hc[0]+r+3,hc[1]+r+3],outline=DARK,width=w+4)
        d.ellipse([hc[0]-r,hc[1]-r,hc[0]+r,hc[1]+r],outline=WHITE,width=w); face(d,hc,r,emo)
def P(neck,head,le,lh,re,rh,lk=(-0.42,1.25),lf=(-0.6,2.6),rk=(0.42,1.25),rf=(0.6,2.6)):
    return {"neck":neck,"head":head,"le":le,"lh":lh,"re":re,"rh":rh,"lk":lk,"lf":lf,"rk":rk,"rf":rf}
def eio(t): t=max(0,min(1,t)); return t*t*(3-2*t)
def bl(a,b,t):
    t=eio(t); return {k:(a[k][0]+(b[k][0]-a[k][0])*t,a[k][1]+(b[k][1]-a[k][1])*t) for k in a}
CROUCH=P((0,-1.7),(0.05,-2.6),(-0.5,-0.9),(-0.55,0.05),(0.45,-0.85),(0.7,0.45),lk=(-0.55,0.55),lf=(-0.95,1.2),rk=(0.55,0.55),rf=(0.95,1.2))
BOOK =P((0,-2.6),(0.05,-3.45),(-0.55,-1.7),(-0.2,-1.45),(0.55,-1.7),(0.2,-1.45))
BATU =P((0,-2.6),(0.1,-3.5),(0.4,-2.1),(1.0,-2.95),(0.85,-1.9),(1.3,-2.55),lf=(-0.95,2.6),rf=(0.8,2.6))
BATD =P((0,-2.6),(0.1,-3.4),(0.3,-1.6),(0.95,-0.55),(0.8,-1.5),(1.25,-0.45),lf=(-0.95,2.6),rf=(0.8,2.6))
EAT_A=P((0,-2.6),(0,-3.5),(-0.7,-1.6),(-1.0,-0.85),(0.45,-2.7),(0.12,-3.15))
EAT_B=P((0,-2.6),(0,-3.5),(-0.7,-1.6),(-1.0,-0.85),(0.4,-2.4),(0.25,-2.75))
TIRED=P((0,-2.25),(0.18,-2.95),(-0.55,-1.35),(-0.55,-0.2),(0.5,-2.45),(0.2,-3.05))
WIST =P((0,-2.6),(0.02,-3.5),(-1.0,-0.95),(-0.7,-1.5),(0.5,-1.9),(0.13,-1.85))
WAVE_A=P((0,-2.6),(-0.05,-3.5),(-0.8,-2.2),(-1.15,-2.95),(0.7,-1.6),(1.0,-0.9))
WAVE_B=P((0,-2.6),(-0.05,-3.5),(-0.8,-2.3),(-1.05,-3.15),(0.7,-1.6),(1.0,-0.9))
JOY  =P((0,-2.65),(0,-3.55),(-0.8,-2.6),(-1.25,-3.5),(0.8,-2.6),(1.25,-3.5),lf=(-0.85,2.6),rf=(0.85,2.6))
EXC  =P((0,-2.6),(0,-3.5),(-0.8,-2.4),(-1.0,-3.2),(0.8,-2.4),(1.0,-3.2))
LOOKUP=P((0,-2.6),(0.0,-3.55),(-0.6,-2.4),(-0.95,-3.15),(0.6,-1.8),(0.2,-1.7))

def render_char(d,motion,emo,hy,s,t):
    bob=math.sin(t*3.6); cx=360
    if motion=="crouch": stick(d,300,hy+bob*3,s,CROUCH,emo)
    elif motion=="book": stick(d,cx,hy+abs(bob)*5,s,BOOK,emo)
    elif motion=="bat":  stick(d,cx,hy,s,bl(BATU,BATD,(math.sin(t*3.0)+1)/2),"excited")
    elif motion=="eat":  stick(d,cx,hy+abs(bob)*4,s,bl(EAT_A,EAT_B,(math.sin(t*4.2)+1)/2),"happy")
    elif motion=="jump": stick(d,cx,hy-abs(math.sin(t*3.0))*26,s,EXC,"excited")
    elif motion=="wave": stick(d,cx,hy+abs(bob)*4,s,bl(WAVE_A,WAVE_B,(math.sin(t*6)+1)/2),emo)
    elif motion=="lookup": stick(d,cx,hy+math.sin(t*1.6)*4,s,LOOKUP,"wistful")
    elif motion=="tired":
        sl=math.sin(t*1.4)*0.04; p=dict(TIRED); p["head"]=(0.18+sl,-2.95+abs(sl)); stick(d,cx,hy,s,p,"sad")
    else:  # dream / dream2
        stick(d,300,hy+math.sin(t*1.6)*4,s,WIST,"wistful")
        gx=470+(10 if motion=="dream2" else 0)
        stick(d,gx,hy+40,int(s*0.5),bl(WAVE_A,JOY,(math.sin(t*4.5)+1)/2),"happy",col=(255,214,140))

def main(spec_path):
    spec=json.loads(Path(spec_path).read_text())
    sid=spec["id"]; scenes=spec["scenes"]; music=spec.get("music","lk_music.mp3")
    durs=[]
    for i,sc in enumerate(scenes,1):
        vp=OUT/f"v_{sid}_{i}.mp3"
        r=requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}",
            headers={"xi-api-key":EL,"Content-Type":"application/json","Accept":"audio/mpeg"},
            json={"text":sc["line"],"model_id":MODEL,"voice_settings":{"stability":0.32,"similarity_boost":0.82,"style":0.45,"use_speaker_boost":True}},timeout=180)
        if r.status_code!=200: print("VOICE ERR",i,r.status_code,r.text[:160]); sys.exit(1)
        vp.write_bytes(r.content); durs.append(adur(vp)); print(f"  v{i} {durs[-1]:.2f}s")
    START=[sum(durs[:i]) for i in range(len(durs))]; TOTAL=sum(durs); N=int(TOTAL*FPS)
    BW,BH=int(W*1.12),int(H*1.12)
    def prep(n,b=0.82):
        im=Image.open(OUT/f"{n}.jpg").convert("RGB"); sc=max(BW/im.width,BH/im.height)
        im=im.resize((int(im.width*sc),int(im.height*sc)))
        im=im.crop(((im.width-BW)//2,(im.height-BH)//2,(im.width-BW)//2+BW,(im.height-BH)//2+BH))
        return ImageEnhance.Brightness(im).enhance(b)
    BGS={sc["img"]:prep(sc["img"]) for sc in scenes}
    import random; random.seed(7)
    GR=[Image.effect_noise((W,H),20).convert("RGB") for _ in range(14)]
    VIG=Image.new("L",(W,H),0); _vd=ImageDraw.Draw(VIG)
    _vd.ellipse([-W*0.25,-H*0.18,W*1.25,H*1.18],fill=255); VIG=VIG.filter(ImageFilter.GaussianBlur(180))
    def kb(img,frac):
        z=0.06; cw=min(int(W*(1+z*(1-frac))),BW); ch=min(int(H*(1+z*(1-frac))),BH)
        return img.crop(((BW-cw)//2,(BH-ch)//2,(BW-cw)//2+cw,(BH-ch)//2+ch)).resize((W,H))
    def grade(img,mode,f):
        if mode=="cold": img=Image.blend(img,Image.new("RGB",img.size,(90,130,210)),0.16); img=ImageEnhance.Color(img).enhance(0.78)
        elif mode=="dream": img=Image.blend(img,Image.new("RGB",img.size,(120,120,210)),0.10)
        else: img=Image.blend(img,Image.new("RGB",img.size,(255,180,110)),0.10); img=ImageEnhance.Color(img).enhance(0.95)
        img=ImageChops.screen(img,ImageEnhance.Brightness(GR[f%14]).enhance(0.08))
        return Image.composite(img,Image.new("RGB",(W,H),(0,0,0)),VIG)
    def sidx(t):
        for i in range(len(scenes)-1,-1,-1):
            if t>=START[i]: return i
        return 0
    FR=OUT/f"fr_{sid}"
    if FR.exists(): shutil.rmtree(FR)
    FR.mkdir()
    for f in range(N):
        t=f/FPS; i=sidx(t); sc=scenes[i]; lt=t-START[i]; seg=max(0.1,durs[i]); frac=lt/seg
        mode="cold" if sc["motion"]=="tired" else ("dream" if "dream" in sc["motion"] else "warm")
        bg=grade(kb(BGS[sc["img"]],frac).copy(),mode,f); d=ImageDraw.Draw(bg)
        render_char(d,sc["motion"],sc.get("emo","happy"),sc["hy"],sc["s"],t)
        fin=eio(min(1,lt/0.5))
        if fin<1: bg=Image.blend(bg,Image.new("RGB",(W,H),(0,0,0)),(1-fin)*0.9)
        bg.save(FR/f"f_{f:04d}.png")
    sil=OUT/f"sil_{sid}.mp4"
    subprocess.run(["ffmpeg","-y","-framerate",str(FPS),"-i",str(FR/"f_%04d.png"),"-c:v","libx264","-pix_fmt","yuv420p","-movflags","+faststart",str(sil)],check=True,capture_output=True)
    vl=OUT/f"vl_{sid}.txt"; vl.write_text("".join(f"file 'v_{sid}_{i}.mp3'\n" for i in range(1,len(scenes)+1)))
    voice=OUT/f"voice_{sid}.mp3"
    subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(vl),"-c","copy",str(voice)],check=True,capture_output=True)
    fade_st=max(1,TOTAL-2.5); final=OUT/f"final_{sid}.mp4"
    subprocess.run(["ffmpeg","-y","-i",str(sil),"-i",str(voice),"-i",str(OUT/music),"-filter_complex",
        f"[1:a]volume=1.35,adelay=150|150[v];[2:a]volume=0.13,afade=t=in:st=0:d=2,afade=t=out:st={fade_st:.1f}:d=2.5[m];[v][m]amix=inputs=2:duration=first:normalize=0[a]",
        "-map","0:v","-map","[a]","-c:v","copy","-c:a","aac","-b:a","192k","-shortest",str(final)],check=True,capture_output=True)
    shutil.rmtree(FR)
    print(f"FINAL {final}  ({TOTAL:.1f}s)")

if __name__=="__main__":
    main(sys.argv[1])
