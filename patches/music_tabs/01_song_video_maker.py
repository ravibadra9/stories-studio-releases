"""
13_song_video_maker.py — 🎬 Song Video Maker + ✂ Audio Splitter
tabs/ folder mein daalo → Music tab ke andar sub-tab ban jayega.
"""

TAB_TITLE = "✂️  Audio Splitter & Video"
TAB_ORDER = 3
TAB_GROUP = ""
TAB_COLOR = ("#1d4ed8", "#2563eb")
TAB_ICON  = "✂️"
LAZY_LOAD = True

# ══════════════════════════════════════════════════════════════
# 📌 Song Video Maker v4 — FINAL POLISHED Edition
# ══════════════════════════════════════════════════════════════
#
# v4 FIXES:
#   ✅ Button WIDTH slider added
#   ✅ 16:9 LOCKED — grid computed at 1920×1080, preview scales exactly
#   ✅ Visualizer bars drawn BEHIND text (text always on top)
#   ✅ Bar opacity slider
#   ✅ Button text color + font picker
#   ✅ Header animation effects (Wave, Fade In, Slide Up, Glow Pulse)
#   ✅ Button shadow / depth for premium look
#   ✅ All previous features retained
# ══════════════════════════════════════════════════════════════

import os,sys,re,json,math,shutil,tempfile,threading,glob
import collections,platform,subprocess,time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog,messagebox,colorchooser
import lazy_menu  # Win32 / TCL native menu limit fix

def _ensure(p,i=None):
    import importlib
    try: importlib.import_module(i or p)
    except ImportError:
        if getattr(sys, "frozen", False): return
        try: subprocess.check_call([sys.executable,"-m","pip","install",p,"-q"])
        except Exception: pass
_ensure("customtkinter"); _ensure("Pillow","PIL")
import customtkinter as ctk
import colorsys
import math as _math
from PIL import Image,ImageDraw,ImageFont,ImageFilter,ImageChops
import preset_manager

_APP_DATA_DIR=Path(os.environ.get("LOCALAPPDATA",os.path.expanduser("~")))/"StoriesStudio"
TEMP_DIR=_APP_DATA_DIR/"temp_work"/"song_video_maker"
OUTPUT_DIR=Path(os.path.expanduser("~"))/"Downloads"/"StoriesStudio_Output"/"SongVideoMaker"
CONFIG_FILE=_APP_DATA_DIR/"svm_config.json"
PRESETS_FILE=_APP_DATA_DIR/"svm_presets.json"
# Symbol font: DejaVuSans has good cross/dagger coverage
import glob as _gl
_DVPATHS=_gl.glob('/usr/local/lib*/python*/site-packages/matplotlib/mpl-data/fonts/ttf/DejaVuSans.ttf')
SYMBOL_FONT=_DVPATHS[0] if _DVPATHS else None
for _d in (TEMP_DIR, OUTPUT_DIR, _APP_DATA_DIR):
    try: _d.mkdir(parents=True, exist_ok=True)
    except Exception: pass
_W=platform.system()=="Windows"; _E=".exe" if _W else ""
_CANDIDATES=[
    getattr(sys, "_MEIPASS", ""),
    os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else "",
    str(_APP_DATA_DIR/"bin"),
    str(Path(__file__).resolve().parent/"bin"),
    str(Path.cwd()/"bin"),
    str(Path.cwd()),
]
FF="ffmpeg"
FP="ffprobe"
for _c in _CANDIDATES:
    if _c and os.path.isdir(_c):
        _ff = os.path.join(_c, f"ffmpeg{_E}")
        _fp = os.path.join(_c, f"ffprobe{_E}")
        if os.path.isfile(_ff) and FF == "ffmpeg":
            FF = _ff
            if _c not in os.environ["PATH"]:
                os.environ["PATH"] = _c + os.pathsep + os.environ["PATH"]
        if os.path.isfile(_fp) and FP == "ffprobe":
            FP = _fp
_NW=subprocess.CREATE_NO_WINDOW if _W else 0; _T=str(os.cpu_count() or 4)
A_EXT={".mp3",".wav",".aac",".flac",".ogg",".m4a",".opus",".wma"}
A_Q=["-c:a","aac","-b:a","320k","-ar","48000","-ac","2"]
VW,VH=1920,1080

BG_M="#0a0a0a"; BG_C="#141414"; BG_I="#0d0d0d"
AR="#e63946"; AP="#c0392b"; AG="#4ade80"; AO="#e74c3c"
AX="#ff1744"; AB="#e63946"; AY="#ff4444"; AC="#ff6b6b"
T1="#ffffff"; T2="#cccccc"; TM="#888888"; BC="#2a0a0a"

PAL=[(220,53,69),(37,99,235),(22,163,74),(147,51,234),(234,136,12),(6,162,192),
     (219,39,119),(202,138,4),(79,70,229),(13,148,136),(225,29,72),(101,163,13),
     (0,122,204),(168,85,247),(239,68,68),(16,185,129)]

def load_cfg():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE,encoding="utf-8") as f: return json.load(f)
        except: pass
    return {}
def save_cfg(d):
    try:
        with open(CONFIG_FILE,"w",encoding="utf-8") as f: json.dump(d,f,indent=2)
    except: pass

def load_presets():
    """Load all saved presets from presets file."""
    if PRESETS_FILE.exists():
        try:
            with open(PRESETS_FILE,encoding="utf-8") as f: return json.load(f)
        except: pass
    return {}

def save_presets(d):
    """Save all presets dict to file."""
    try:
        with open(PRESETS_FILE,"w",encoding="utf-8") as f: json.dump(d,f,indent=2)
    except: pass

# ═══════════════════ HELPERS ═══════════════════

def _rq(a, **k):
    if "text" in k and "encoding" not in k:
        k["encoding"] = "utf-8"
        k["errors"] = "replace"
    return subprocess.run(a, creationflags=_NW, **k)
def nsk(s): return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)',s)]
def ctn(p):
    n=os.path.splitext(os.path.basename(p))[0]
    s=re.sub(r'^(?:track\s*)?\d+[\s.\-_)]+\s*','',n,flags=re.IGNORECASE)
    s=re.sub(r'\([^)]*\)','',s); s=re.sub(r'\[[^\]]*\]','',s)
    s=re.sub(r'[_\-]+',' ',s); s=re.sub(r'\s{2,}',' ',s).strip(" .-_")
    return s if s else re.sub(r'[_\-]+',' ',n).strip(" .-_") or n
def sdt(t): return str(t).replace("\\","/").replace(":","- ").replace("'","\u2019").replace('"',"\u201C").replace("%"," pct").strip()
def ffe(p): return str(p).replace("\\","/").replace(":","\\:")

# ═══ FONT SYSTEM ═══

_FONT_PATHS={}
def _scan_fonts():
    if _FONT_PATHS: return
    dirs=[]
    if _W: dirs=[r"C:\Windows\Fonts"]
    elif platform.system()=="Darwin": dirs=["/Library/Fonts","/System/Library/Fonts"]
    else: dirs=["/usr/share/fonts"]
    for d in dirs:
        if not os.path.isdir(d): continue
        for f in glob.glob(d+"/**/*.ttf",recursive=True)+glob.glob(d+"/**/*.otf",recursive=True):
            name=os.path.splitext(os.path.basename(f))[0].lower()
            _FONT_PATHS[name]=f

def list_fonts():
    _scan_fonts()
    nice={}
    for key,path in _FONT_PATHS.items():
        display=os.path.splitext(os.path.basename(path))[0]
        nice[display]=path
    return nice

_DT_CACHE = {}

def ff_fontpath(p):
    r"""Escape a font path for use INSIDE an ffmpeg filtergraph.

    ffmpeg splits filter options on ':' before quote handling, so a Windows
    path like C:/Windows/Fonts/arialbd.ttf makes it think '/Windows/...' is a
    new option -> "No option name near '/Windows/Fonts/arialbd.ttf'".
    The drive colon must be backslash-escaped: C\:/Windows/Fonts/arialbd.ttf
    """
    if not p:
        return p
    p = str(p).replace(chr(92), "/")
    p = p.replace(":", chr(92) + ":")
    return p

def ff_text(v):
    """Make arbitrary text safe inside drawtext text='...'.

    Inside single quotes everything is literal except the quote itself, so we
    swap ASCII apostrophes for the typographic one instead of fighting
    ffmpeg's multi-level escaping.
    """
    return str(v).replace(chr(92), "/").replace("'", chr(0x2019))

def _ytdlp_base():
    """yt-dlp as a binary, or via the current interpreter if only the module exists."""
    exe = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if not exe:
        for c in [
            os.path.join(os.path.dirname(sys.executable), "yt-dlp.exe"),
            os.path.join(os.path.dirname(sys.executable), "bin", "yt-dlp.exe"),
            os.path.join(os.path.dirname(__file__), "..", "bin", "yt-dlp.exe"),
            os.path.join(os.path.dirname(__file__), "..", "yt-dlp.exe"),
        ]:
            if os.path.isfile(c):
                exe = c
                break
    if exe:
        cmd = [exe]
    elif not getattr(sys, "frozen", False):
        cmd = [sys.executable, "-m", "yt_dlp"]
    else:
        cmd = []
    node_exe = shutil.which("node") or shutil.which("node.exe")
    if not node_exe and os.path.exists(r"C:\Program Files\nodejs\node.exe"):
        node_exe = r"C:\Program Files\nodejs\node.exe"
    if node_exe and cmd:
        cmd += ["--js-runtimes", f"node:{node_exe}"]
    return cmd

def set_ff(path):
    """Point the app at a user-picked ffmpeg binary; find ffprobe beside it."""
    global FF, FP
    if not path or not os.path.isfile(path):
        return False
    FF = path
    _DT_CACHE.clear()
    d = os.path.dirname(path)
    b = os.path.basename(path).lower()
    cand = os.path.join(d, "ffprobe.exe" if b.endswith(".exe") else "ffprobe")
    if os.path.isfile(cand):
        FP = cand
    return True

def has_drawtext():
    """True if the current ffmpeg was built with the drawtext filter."""
    if FF in _DT_CACHE:
        return _DT_CACHE[FF]
    ok = False
    try:
        r = _rq([FF, "-hide_banner", "-filters"], capture_output=True,
                text=True, timeout=25)
        ok = bool(re.search(r"^\s*\S+\s+drawtext\s", r.stdout or "", re.M))
    except Exception:
        ok = False
    _DT_CACHE[FF] = ok
    return ok

def probe_ff():
    """Return (ok, human message) for the currently selected ffmpeg."""
    try:
        r = _rq([FF, "-hide_banner", "-version"], capture_output=True,
                text=True, timeout=25)
        if r.returncode != 0:
            return False, "ffmpeg found but failed to run"
        ver = (r.stdout or "").splitlines()[0].replace("ffmpeg version ", "")[:34]
    except Exception as e:
        return False, "Not found: " + str(e)[:60]
    dt = "drawtext OK" if has_drawtext() else "NO drawtext (song name off)"
    return True, "OK " + chr(0xB7) + " " + ver + " " + chr(0xB7) + " " + dt

def find_font(name=None):
    _scan_fonts()
    if name and name!="Default":
        key=name.lower()
        # Exact match first. An uploaded font called "comic" must not lose to a
        # system "comicbd", which is what the loose substring scan used to do.
        v=_FONT_PATHS.get(key)
        if v and os.path.isfile(v): return v
        # Allow a full path to be used directly.
        if os.path.isfile(name): return name
        for k,v in _FONT_PATHS.items():
            if key in k and os.path.isfile(v): return v
    for c in [r"C:\Windows\Fonts\arialbd.ttf",r"C:\Windows\Fonts\arial.ttf",
              r"C:\Windows\Fonts\segoeui.ttf","/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "/System/Library/Fonts/Supplemental/Arial Bold.ttf"]:
        if os.path.isfile(c): return c
    # Last resort: any scanned system font. Distros put fonts in different
    # places, and if this returns None the ffmpeg drawtext layer silently
    # switches off, which stops the active song name from scrolling.
    for pref in ("arialbd","arial","dejavusans-bold","dejavusans",
                 "liberationsans-bold","liberationsans","notosans",
                 "droidsans-bold","droidsans","freesansbold","freesans"):
        for k,v in sorted(_FONT_PATHS.items()):
            if k.startswith(pref) and os.path.isfile(v): return v
    for k,v in sorted(_FONT_PATHS.items()):
        if os.path.isfile(v): return v
    _sf=globals().get("SYMBOL_FONT")
    if _sf and os.path.isfile(_sf): return _sf
    return None

def pil_font(sz=18,name=None):
    fp=find_font(name)
    if fp:
        try: return ImageFont.truetype(fp,sz)
        except: pass
    return ImageFont.load_default()

def fit_px(text,fs,mx,fn=None):
    text=str(text);
    if mx<=0: return text
    f=pil_font(int(fs),fn)
    def _w(s):
        try: return f.getbbox(s)[2]
        except: return int(len(s)*fs*0.5)
    if _w(text)<=mx: return text
    lo,hi=0,len(text)
    while lo<hi:
        mid=(lo+hi+1)//2
        if _w(text[:mid]+"\u2026")<=mx: lo=mid
        else: hi=mid-1
    return (text[:lo].rstrip()+"\u2026") if lo>0 else "\u2026"

def get_dur(p):
    try:
        r=_rq([FP,"-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1",str(p)],
              capture_output=True,text=True,timeout=15)
        return float(r.stdout.strip())
    except: return 0.0

def detect_gpu():
    tmp=os.path.join(tempfile.gettempdir(),"svm_g.mp4")
    base=[FF,"-y","-f","lavfi","-i","color=black:s=256x256:r=30","-t","1","-pix_fmt","yuv420p"]
    for enc in ["h264_nvenc","hevc_nvenc","h264_amf","h264_qsv","h264_mf","h264_videotoolbox"]:
        try:
            r=_rq(base+["-c:v",enc]+qf(enc)+[tmp],capture_output=True,timeout=20)
            if r.returncode==0 and os.path.exists(tmp) and os.path.getsize(tmp)>0:
                try: os.remove(tmp)
                except: pass
                return enc
        except: pass
    try:
        if os.path.exists(tmp): os.remove(tmp)
    except: pass
    return "libx264"

def qf(enc,sf=False):
    if enc=="libx264": return ["-preset","ultrafast" if sf else "veryfast","-crf","23" if sf else "20","-bf","0","-threads",_T]
    if "nvenc" in enc:
        if sf: return ["-preset","p1","-tune","ll","-cq","27","-b:v","0","-bf","0","-rc-lookahead","0"]
        return ["-preset","p4","-tune","hq","-cq","21","-b:v","0","-bf","0","-rc-lookahead","8"]
    if enc=="h264_mf": return ["-b:v","8M"]
    if "qsv" in enc: return ["-preset","veryfast" if sf else "faster","-global_quality","26" if sf else "21","-bf","0"]
    if "amf" in enc: q="27" if sf else "21"; return ["-quality","speed","-rc","cqp","-qp_i",q,"-qp_p",str(int(q)+1),"-bf","0"]
    if "videotoolbox" in enc: return ["-q:v","58" if sf else "75","-allow_sw","1"]
    return []


def prep_logo(p,sz,rm=False):
    img=Image.open(p).convert("RGBA")
    if rm: img=_rmbg(img)
    img.thumbnail((sz,sz),Image.LANCZOS); return img

def _rmbg(img,tol=38):
    img=img.convert("RGBA")
    if img.getchannel("A").getextrema()[0]<250: return img
    w,h=img.size
    px=list(img.get_flattened_data()) if hasattr(img,"get_flattened_data") else list(img.getdata())
    cs=[px[0],px[w-1],px[(h-1)*w],px[w*h-1]]
    br,bg_,bb=sum(c[0] for c in cs)//4,sum(c[1] for c in cs)//4,sum(c[2] for c in cs)//4
    if max(abs(c[0]-br)+abs(c[1]-bg_)+abs(c[2]-bb) for c in cs)>60: return img
    img.putdata([((r,g,b,0) if abs(r-br)+abs(g-bg_)+abs(b-bb)<=tol*3 else (r,g,b,a)) for r,g,b,a in px])
    return img

def mk_ring(sz,col=(255,255,255),segs=28):
    S=4; big=Image.new("RGBA",(sz*S,sz*S),(0,0,0,0)); d=ImageDraw.Draw(big)
    cx=cy=sz*S/2; ro=sz*S*0.48
    for i in range(segs):
        a0=(360.0/segs)*i; a1=a0+(360.0/segs)*0.55; rr=ro if i%4 else ro*1.06
        d.arc([cx-rr,cy-rr,cx+rr,cy+rr],a0,a1,fill=(*col,235),width=max(2,int(sz*S*0.045)))
    return big.resize((sz,sz),Image.LANCZOS)

def fhms(s):
    s=int(s); h,s=divmod(s,3600); m,s=divmod(s,60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

def gen_ts(ps,ds,lp=1):
    """Build a YouTube-ready chapter list.

    YouTube needs the first chapter at 00:00, at least 3 chapters, and every
    chapter at least 10 seconds long, so we emit one flat list and flag any
    track that breaks the 10s rule."""
    rows=[]; cum=0.0
    for li in range(lp):
        for i,sp in enumerate(ps):
            nm=ctn(sp)
            if lp>1: nm=f"{nm} (Loop {li+1})"
            rows.append((cum,nm,ds[i]))
            cum+=ds[i]
    body="\n".join(f"{fhms(t)} {nm}" for t,nm,_ in rows)
    h=f"\U0001F3B6 Playlist Timestamps\nTotal: {fhms(cum)} | {len(ps)} tracks"
    if lp>1: h+=f" | {lp}x loop"
    tips=["","Copy the list below straight into your YouTube description."]
    if len(rows)<3:
        tips.append("! YouTube needs at least 3 chapters to show a chapter list.")
    shorts=[nm for _,nm,d in rows if d<10]
    if shorts:
        tips.append("! Under 10s, so YouTube will ignore these: "+", ".join(shorts[:5]))
    return h+"\n"+"\n".join(tips)+"\n\n"+body+"\n"

def _beep():
    try:
        if _W: import winsound; winsound.Beep(880,220); winsound.Beep(1320,260)
        else: sys.stdout.write("\a")
    except: pass

# ═══ EMOJI ═══
def find_efont():
    for c in [r"C:\Windows\Fonts\seguiemj.ttf","/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
              "/System/Library/Fonts/Apple Color Emoji.ttc","/usr/share/fonts/noto/NotoColorEmoji.ttf"]:
        if os.path.isfile(c): return c
    for d in ["/usr/share/fonts",os.path.expanduser("~/.fonts")]:
        for f in glob.glob(d+"/**/*Emoji*.ttf",recursive=True): return f
    return None
def _isem(cp): return (0x1F300<=cp<=0x1FAFF or 0x2600<=cp<=0x27BF or 0x2B00<=cp<=0x2BFF or 0x1F000<=cp<=0x1F1FF or cp in (0x2640,0x2642,0x2764,0x271D) or 0xFE00<=cp<=0xFE0F)
def _seg(s):
    t=[]; i=0; n=len(s)
    while i<n:
        if _isem(ord(s[i])):
            j=i+1
            while j<n and (_isem(ord(s[j])) or ord(s[j]) in (0x200D,0xFE0F,0xFE0E) or 0x1F3FB<=ord(s[j])<=0x1F3FF): j+=1
            t.append((s[i:j],True)); i=j
        else: t.append((s[i],False)); i+=1
    return t
def _lef(p,sz):
    if not p: return None
    try: return ImageFont.truetype(p,sz)
    except:
        try: return ImageFont.truetype(p,109)
        except: return None
def _eimg(tok,ef,tgt):
    if not ef: return None
    im=Image.new("RGBA",(180,180),(0,0,0,0)); d=ImageDraw.Draw(im)
    try: d.text((4,4),tok,font=ef,embedded_color=True)
    except:
        try: d.text((4,4),tok,font=ef,fill=(255,210,60,255))
        except: return None
    bb=im.getbbox()
    if not bb: return None
    im=im.crop(bb); h=max(1,tgt); w=max(1,int(im.width*tgt/max(1,im.height)))
    return im.resize((w,h),Image.LANCZOS)

# ═══════════════════ GRID (always at 1920×1080) ═══════════════════

def auto_grid(n,co=0):
    if n<=0: return (1,1)
    if co>0: return (co,math.ceil(n/co))
    if n==1: return (1,1)
    if n==2: return (2,1)
    if n<=4: return (2,2)
    if n<=6: return (3,2)
    if n<=8: return (4,2)
    if n<=12: return (4,3)
    if n<=16: return (4,4)
    if n<=20: return (5,4)
    cols=min(6,math.ceil(n/4)); return (cols,math.ceil(n/cols))

def compute_grid(n,ax,ay,aw,ah,outer_pad=20,row_gap=16,col_gap=None,bh_max=None,bw_max=None,co=0):
    """Compute grid at FULL resolution (1920x1080).
    row_gap = vertical gap between button rows
    col_gap = horizontal gap between button columns (defaults to row_gap)

    bh_max/bw_max are treated as the TARGET button size the user asked for
    (via the Height/Width sliders), not just an upper cap. If that size
    doesn't fit the available area at the requested gap, the gap is shrunk
    toward a small minimum first — only if it still doesn't fit at minimum
    gap do the buttons themselves shrink. This is what makes the sliders
    feel responsive: raising Height/Width reliably makes buttons bigger
    instead of silently being capped by whatever the gap happened to leave.
    """
    if n<=0: return []
    if col_gap is None: col_gap=row_gap
    cols,rows=auto_grid(n,co)
    avail_w=max(1,aw-outer_pad*2); avail_h=max(1,ah-outer_pad*2)
    min_gap=2

    def _fit(want,avail,count,gap,min_size):
        """Return (size,gap) that best honours `want`, shrinking gap (then
        size) only as much as needed to stay inside `avail`."""
        if count<=1:
            return (max(min_size,min(want,avail)) if want else avail),gap
        gap=max(0,gap)
        needed=want*count+gap*(count-1)
        if needed<=avail:
            return want,gap
        gap2=max(min_gap,(avail-want*count)/(count-1))
        if gap2<gap:
            needed2=want*count+gap2*(count-1)
            if needed2<=avail+0.5:
                return want,gap2
            gap=gap2
        size2=max(min_size,(avail-gap*(count-1))/count)
        return size2,gap

    fit_bw=(avail_w-col_gap*(cols-1))/cols
    fit_bh=(avail_h-row_gap*(rows-1))/rows
    want_bw=bw_max if (bw_max and bw_max>0) else fit_bw
    want_bh=bh_max if (bh_max and bh_max>0) else fit_bh
    bw,col_gap=_fit(want_bw,avail_w,cols,col_gap,80)
    bh,row_gap=_fit(want_bh,avail_h,rows,row_gap,30)
    bh=max(bh,30); bw=max(bw,80)
    tw=cols*bw+col_gap*(cols-1); th=rows*bh+row_gap*(rows-1)
    # Center the whole grid block
    ox=ax+outer_pad+(aw-outer_pad*2-tw)/2
    oy=ay+outer_pad+(ah-outer_pad*2-th)/2
    out=[]
    for i in range(n):
        r,c=divmod(i,cols)
        out.append((int(ox+c*(bw+col_gap)),int(oy+r*(bh+row_gap)),int(bw),int(bh),i,PAL[i%len(PAL)]))
    return out

def scale_grid(grid,scale):
    """Scale grid from full-res to preview."""
    return [(int(x*scale),int(y*scale),int(w*scale),int(h*scale),i,c) for x,y,w,h,i,c in grid]

# ═══════════════════ BUTTON RENDERER ═══════════════════


_GIF_CACHE={}

def gif_frames(path,maxf=60):
    """Decode an animated GIF/WebP into RGBA frames + per-frame delays (ms)."""
    key=(path,maxf)
    if key in _GIF_CACHE: return _GIF_CACHE[key]
    frames=[]; delays=[]
    try:
        im=Image.open(path)
        while True:
            frames.append(im.convert("RGBA").copy())
            delays.append(max(20,int(im.info.get("duration",80) or 80)))
            if len(frames)>=maxf: break
            im.seek(im.tell()+1)
    except EOFError:
        pass
    except Exception:
        pass
    if not frames:
        try:
            frames=[Image.open(path).convert("RGBA")]; delays=[100]
        except Exception:
            frames=[]; delays=[]
    _GIF_CACHE[key]=(frames,delays)
    return frames,delays

def gif_frame_at(frames,delays,t):
    """Frame for time t, looping forever."""
    if not frames: return None
    total=sum(delays)/1000.0
    if total<=0: return frames[0]
    tt=(t%total)*1000.0
    acc=0.0
    for f,d in zip(frames,delays):
        acc+=d
        if tt<acc: return f
    return frames[-1]

def gif_size_at(path,w):
    """Height for a GIF scaled to width w (keeps aspect)."""
    try:
        fr,_=gif_frames(path)
        if fr: return max(4,int(fr[0].height*w/max(1,fr[0].width)))
    except Exception:
        pass
    return w

def chroma_key(img,hexcol="#00FF00",sim=30,blend=10):
    """Knock the background colour out of a GIF frame (green-screen removal).

    Matches ffmpeg's colorkey filter, which measures the largest per-channel
    difference, so the live preview and the rendered video agree. Implemented
    with plain PIL so no extra packages are needed on the user's machine.
    """
    try:
        im=img.convert("RGBA")
        h=(hexcol or "#00FF00").lstrip("#").strip()
        if len(h)==3: h="".join(ch*2 for ch in h)
        try: kr,kg,kb=int(h[0:2],16),int(h[2:4],16),int(h[4:6],16)
        except Exception: kr,kg,kb=0,255,0
        base=Image.new("RGB",im.size,(kr,kg,kb))
        diff=ImageChops.difference(im.convert("RGB"),base)
        r,g,b=diff.split()
        m=ImageChops.lighter(ImageChops.lighter(r,g),b)   # max channel delta
        s_=max(0.0,min(1.0,float(sim)/100.0))*255.0
        b_=max(0.0,min(1.0,float(blend)/100.0))*255.0
        if b_<=0.5:
            tbl=[0 if v<=s_ else 255 for v in range(256)]
        else:
            tbl=[int(max(0.0,min(255.0,(v-s_)*255.0/b_))) for v in range(256)]
        mask=m.point(tbl)
        im.putalpha(ImageChops.multiply(im.getchannel("A"),mask))
        return im
    except Exception:
        return img

def ff_colorkey(g):
    """ffmpeg colorkey fragment for a GIF entry, or "" when disabled."""
    if not g.get("ck"): return ""
    hx=(g.get("ckc") or "#00FF00").lstrip("#").strip()
    if len(hx)==3: hx="".join(c*2 for c in hx)
    try: int(hx,16)
    except Exception: hx="00FF00"
    sim=max(0.01,min(1.0,float(g.get("cks",30))/100.0))
    bl=max(0.0,min(1.0,float(g.get("ckb",10))/100.0))
    return ",colorkey=0x%s:%.3f:%.3f"%(hx.upper()[:6],sim,bl)

def hex_rgb(h,dflt=(255,255,255)):
    """#RRGGBB / #RGB -> (r,g,b), falling back to dflt."""
    try:
        h=str(h).lstrip("#").strip()
        if len(h)==3: h="".join(c*2 for c in h)
        return (int(h[0:2],16),int(h[2:4],16),int(h[4:6],16))
    except Exception:
        return dflt

def wrap_px(text,font,max_w,max_lines=3):
    """Word-wrap text to max_w pixels using the REAL font metrics.

    Long single words are hard-split, and anything that still does not fit in
    max_lines is truncated with an ellipsis, so the caller can rely on the
    result never being wider than max_w.
    """
    def W(x):
        try: return int(font.getlength(x))
        except Exception:
            try: return int(font.getbbox(x)[2])
            except Exception: return int(len(x)*8)
    txt=" ".join(str(text).split())
    if not txt: return []
    if max_w<=0: return [txt]

    def _hard(word):
        out=[]; rest=word
        while rest and W(rest)>max_w:
            lo,hi=1,len(rest)
            while lo<hi:
                mid=(lo+hi+1)//2
                if W(rest[:mid])<=max_w: lo=mid
                else: hi=mid-1
            out.append(rest[:lo]); rest=rest[lo:]
        if rest: out.append(rest)
        return out

    lines=[]; cur=""
    for wd in txt.split(" "):
        cand=(cur+" "+wd).strip()
        if W(cand)<=max_w:
            cur=cand; continue
        if cur: lines.append(cur); cur=""
        if W(wd)<=max_w:
            cur=wd
        else:
            parts=_hard(wd)
            if parts:
                lines.extend(parts[:-1]); cur=parts[-1]
    if cur: lines.append(cur)
    if max_lines and len(lines)>max_lines:
        lines=lines[:max_lines]
        last=lines[-1]
        while last and W(last+"\u2026")>max_w: last=last[:-1]
        lines[-1]=(last.rstrip()+"\u2026") if last else "\u2026"
    return lines

def extract_thumb(video,out_jpg,mode="last",at=0.0):
    """Save a single frame of `video` as a JPEG. mode: last | first | at."""
    if not FF or not os.path.isfile(video): return None
    if mode=="first": pre=["-ss","0"]
    elif mode=="at":  pre=["-ss",str(max(0.0,float(at or 0)))]
    else:             pre=["-sseof","-1.0"]
    def _go(a):
        try: _rq(a,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        except Exception: return False
        return os.path.isfile(out_jpg) and os.path.getsize(out_jpg)>0
    if _go([FF,"-y","-v","error"]+pre+["-i",video,"-frames:v","1","-q:v","2",out_jpg]):
        return out_jpg
    # -sseof / a seek past the end can miss on some containers; take frame 1.
    if _go([FF,"-y","-v","error","-i",video,"-frames:v","1","-q:v","2",out_jpg]):
        return out_jpg
    return None

def _hdr_font_path(stl,fp):
    n=(stl or {}).get("font")
    if n and n!="Default":
        p=find_font(n)
        if p: return p
    return fp

def _hdr_para_rows(text,fs,fp,w):
    """Roughly how many wrapped rows a header paragraph needs."""
    if not str(text).strip(): return 1
    try: f=ImageFont.truetype(fp,fs) if fp else pil_font(fs)
    except Exception: f=pil_font(fs)
    mw=max(1,int(w*0.88))
    try: tot=f.getlength(str(text))
    except Exception: tot=len(str(text))*fs*0.5
    return max(1,int(tot//mw)+1)

def draw_header_multi(img,text,ay,ah,fs,color,fp=None,efp=None,border_stroke=2,
                      border_color=(0,0,0),alpha=255,line_styles=None,
                      shadow=False,shadow_blur=8,shadow_opacity=160,shadow_off=(4,4),shadow_color=(0,0,0)):
    """Draw the header, giving every typed line its own font / size / colour.

    line_styles maps the line index (0-based) to {"size":int,"color":"#RRGGBB",
    "font":name}. Missing entries inherit the global header settings.
    """
    paras=str(text).replace("\r","").split("\n")
    if not any(p.strip() for p in paras): return
    ls=line_styles or {}
    def _st(i): return ls.get(i) or ls.get(str(i)) or {}
    heights=[]
    for i,p in enumerate(paras):
        stl=_st(i); sz=max(4,int(stl.get("size") or fs))
        rows=_hdr_para_rows(p,sz,_hdr_font_path(stl,fp),img.width)
        heights.append(int(sz*1.34)*rows)
    y=ay+(ah-sum(heights))//2
    for i,p in enumerate(paras):
        if p.strip():
            stl=_st(i); sz=max(4,int(stl.get("size") or fs))
            col=hex_rgb(stl.get("color"),color) if stl.get("color") else color
            draw_header(img,p,y,heights[i],sz,col,_hdr_font_path(stl,fp),efp,
                        border_stroke=border_stroke,border_color=border_color,
                        alpha=alpha,shadow=shadow,shadow_blur=shadow_blur,
                        shadow_opacity=shadow_opacity,shadow_off=shadow_off,
                        shadow_color=shadow_color)
        y+=heights[i]


# ═══════════ COLOUR THEMES ═══════════
#
# The proportions below are taken from the reference thumbnails: a near-white
# button body, a mid-tone border in the background's own hue, a strongly
# saturated number badge, near-black button text, and a header that flips
# between black and white depending on how bright the background is.

def _hx(rgb):
    return "#%02X%02X%02X" % tuple(max(0, min(255, int(v))) for v in rgb)


def _hsv_hex(h, sat, val):
    return _hx(tuple(c * 255 for c in colorsys.hsv_to_rgb((h % 360) / 360.0, sat, val)))


def make_theme(name, hue):
    """Build a full palette from a single hue."""
    return {
        "name": name, "hue": hue,
        "btn_bg": _hsv_hex(hue, 0.07, 1.00),
        "btn_border": _hsv_hex(hue, 0.45, 1.00),
        "btn_text": _hsv_hex(hue, 0.80, 0.13),
        "badge": _hsv_hex(hue, 0.88, 0.88),
        "badge_txt": "#FFFFFF",
        "hdr_on_light": "#111111", "hdr_on_dark": "#FFFFFF",
        "hdr_border_on_light": _hsv_hex(hue, 0.30, 1.00),
        "hdr_border_on_dark": _hsv_hex(hue, 0.90, 0.25),
        "btn_alpha": 225, "btn_border_alpha": 210,
    }


THEMES = [make_theme(_n_, _h_) for _n_, _h_ in [
    ("Red Fire", 2), ("Deep Orange", 16), ("Sunset Orange", 28), ("Amber Gold", 40),
    ("Yellow Glory", 50), ("Lime", 80), ("Green Grace", 130), ("Teal", 170),
    ("Sky Blue", 200), ("Royal Blue", 225), ("Indigo", 255), ("Purple Praise", 280),
    ("Magenta", 310), ("Hot Pink", 330), ("Rose Pink", 345),
]]
THEMES.append({
    "name": "Neutral Mono", "hue": -1,
    "btn_bg": "#F7F7F7", "btn_border": "#FFFFFF", "btn_text": "#101010",
    "badge": "#222222", "badge_txt": "#FFFFFF",
    "hdr_on_light": "#111111", "hdr_on_dark": "#FFFFFF",
    "hdr_border_on_light": "#DDDDDD", "hdr_border_on_dark": "#000000",
    "btn_alpha": 225, "btn_border_alpha": 210,
})
THEME_NAMES = [t["name"] for t in THEMES]


def get_theme(name):
    for t in THEMES:
        if t["name"] == name:
            return t
    return THEMES[0]


def bg_stats(img):
    """Dominant hue plus mean saturation / brightness of a background.

    Hue is averaged on the colour circle (so red near 0/360 does not cancel
    itself out) and each pixel is weighted by saturation*value, which keeps
    grey and near-black pixels from dragging the result around.
    """
    try:
        im = img.convert("RGB").resize((64, 36))
    except Exception:
        return None
    xs = ys = sat = val = 0.0
    cnt = 0
    for r, g, b in im.getdata():
        h, sa, va = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        w = sa * va
        a = h * 2 * _math.pi
        xs += _math.cos(a) * w
        ys += _math.sin(a) * w
        sat += sa
        val += va
        cnt += 1
    if not cnt:
        return None
    return {"hue": _math.degrees(_math.atan2(ys, xs)) % 360,
            "sat": sat / cnt, "val": val / cnt}


def suggest_theme(img):
    """Pick the theme whose hue is closest to the background's dominant hue."""
    stt = bg_stats(img)
    if not stt:
        return get_theme("Neutral Mono"), None
    if stt["sat"] < 0.12:
        return get_theme("Neutral Mono"), stt
    best, bd = None, 1e9
    for t in THEMES:
        if t["hue"] < 0:
            continue
        d = abs(t["hue"] - stt["hue"])
        d = min(d, 360 - d)
        if d < bd:
            bd, best = d, t
    return (best or THEMES[0]), stt


def draw_btn(img,x,y,w,h,num,name,color,active=False,
             corner=25,txt_color=(0,0,0),
             font_name=None,t_anim=0.0,
             border_color=(0,230,255),border_width=2,
             border_alpha=200,scroll_offset=0,font_size=0,
             btn_bg_alpha=90,show_name=True,scroll_text=True,
             wrap_text=True,scroll_active=True,badge_color=None,badge_txt=(255,255,255)):
    """Draw a pink-style button matching reference image.
    - Semi-transparent colored background (pill/rounded rect)
    - Colored number badge (circle) on left
    - Song title text right of badge
    - Cyan/custom border
    - Active: scrolling name + glow
    """
    d=ImageDraw.Draw(img); r,g,b=color; rad=int(h*corner/100)
    br,bg_,bb=border_color
    bg_a = min(255, max(0, btn_bg_alpha + (50 if active else 0)))
    SS=3  # supersample factor — draw crisp geometry big, then shrink for smooth anti-aliased edges
    bpad=max(12,int(h*0.14))  # room for the glow halo + drop shadow around the button

    big=Image.new("RGBA",((w+2*bpad)*SS,(h+2*bpad)*SS),(0,0,0,0))
    bd=ImageDraw.Draw(big)
    ox,oy=bpad*SS,bpad*SS; rad_ss=max(1,rad*SS)

    # 0. Soft drop shadow beneath the button for depth
    sh=Image.new("RGBA",big.size,(0,0,0,0)); shd=ImageDraw.Draw(sh)
    shoff=int(h*0.06)*SS
    shd.rounded_rectangle([ox-shoff,oy+shoff*2,ox+w*SS-shoff,oy+h*SS+shoff*3],
                           radius=rad_ss,fill=(0,0,0,90))
    sh=sh.filter(ImageFilter.GaussianBlur(max(2,int(h*0.05))*SS//2))
    big.alpha_composite(sh,(0,0))

    # 1. Glow halo for active button, drawn softly then blurred (no hard rings)
    if active:
        glow=Image.new("RGBA",big.size,(0,0,0,0)); gd=ImageDraw.Draw(glow)
        gd.rounded_rectangle([ox-6*SS,oy-6*SS,ox+w*SS+6*SS,oy+h*SS+6*SS],
                              radius=rad_ss+6*SS,fill=(br,bg_,bb,140))
        glow=glow.filter(ImageFilter.GaussianBlur(max(2,int(h*0.06))*SS))
        big.alpha_composite(glow,(0,0))

    # 2. Pill background — soft vertical gradient (lighter top -> base colour)
    #    for a smooth "buttery" body instead of a flat tint.
    top_c=tuple(min(255,int(cc+(255-cc)*0.22)) for cc in (r,g,b))
    grad=Image.new("RGB",(1,max(1,h*SS)))
    for yy in range(h*SS):
        t=yy/max(1,h*SS-1)
        grad.putpixel((0,yy),tuple(int(top_c[k]+((r,g,b)[k]-top_c[k])*t) for k in range(3)))
    grad=grad.resize((w*SS,h*SS)).convert("RGBA")
    amask=Image.new("L",(w*SS,h*SS),0)
    ImageDraw.Draw(amask).rounded_rectangle([0,0,w*SS-1,h*SS-1],radius=rad_ss,fill=bg_a)
    grad.putalpha(amask)
    big.alpha_composite(grad,(ox,oy))

    # 3. Border (single clean pass, supersampled)
    bdr_a=border_alpha if not active else min(255,border_alpha+75)
    bd.rounded_rectangle([ox,oy,ox+w*SS-1,oy+h*SS-1],radius=rad_ss,
                          outline=(br,bg_,bb,bdr_a),width=max(1,border_width*SS))

    small=big.resize((w+2*bpad,h+2*bpad),Image.LANCZOS)
    img.alpha_composite(small,(x-bpad,y-bpad))

    # 4. Number badge (colored pill on left) — number auto-shrinks and the
    # pill auto-widens for double/triple-digit indices so "10.", "11." etc.
    # never poke outside the badge.
    badge_h=int(h*0.62)
    nt=f"{num}."
    nfs=max(9,int(badge_h*0.52))
    badge_w=max(int(badge_h*1.0),int(nfs*0.62*len(nt))+int(badge_h*0.36))
    badge_x=x+int(h*0.16); badge_y=y+(h-badge_h)//2; badge_r=int(badge_h*0.25)
    _bc=badge_color if badge_color else (r,g,b)
    badge_col=(_bc[0],_bc[1],_bc[2],230 if active else 180)
    _bbig=Image.new("RGBA",(max(1,badge_w*SS),max(1,badge_h*SS)),(0,0,0,0))
    ImageDraw.Draw(_bbig).rounded_rectangle([0,0,badge_w*SS-1,badge_h*SS-1],
                          radius=badge_r*SS,fill=badge_col)
    img.alpha_composite(_bbig.resize((badge_w,badge_h),Image.LANCZOS),(badge_x,badge_y))
    # badge number — shrink-to-fit inside the pill with side padding, so it
    # can never visually spill past the badge edge.
    nf=pil_font(nfs)
    npad=max(2,int(badge_w*0.14))
    for _ in range(10):
        try: nb=nf.getbbox(nt); nw_=nb[2]-nb[0]
        except Exception: nw_=int(len(nt)*nfs*0.6)
        if nw_<=badge_w-2*npad or nfs<=8: break
        nfs=max(8,int(nfs*0.88)); nf=pil_font(nfs)
    try: nb=nf.getbbox(nt); nw_=nb[2]-nb[0]; nh_=nb[3]-nb[1]; ny_o=nb[1]
    except Exception: nw_=nfs; nh_=nfs; ny_o=0
    d.text((badge_x+(badge_w-nw_)//2,badge_y+(badge_h-nh_)//2-ny_o),
           nt,fill=(badge_txt[0],badge_txt[1],badge_txt[2],255),font=nf)

    # 5. Song name text area
    #
    # Everything below is drawn into a layer exactly the size of the text area
    # and then composited, so the name can NEVER escape the button box - no
    # matter which font, font size or song title is used.
    tx=badge_x+badge_w+int(h*0.14); tw_avail=x+w-tx-int(h*0.12)
    tfs=max(9,font_size if font_size>0 else int(h*0.30)); tf=pil_font(tfs,font_name)
    ty=y+(h-tfs)//2
    tc_col=(*txt_color,255)
    shadow_col=(255,255,255,100) if sum(txt_color)<200 else (0,0,0,80)

    # When ffmpeg draws the names itself we skip them here, otherwise the
    # baked-in static name would sit underneath the scrolling one.
    if not show_name: return

    # The marquee wins for the song that is playing; every other button
    # wraps.  v16 tested wrap first, which is why the scroll disappeared.
    if wrap_text and not (active and scroll_active):
        clip_w=max(1,tw_avail); clip_h=max(1,h)
        pad=max(1,int(h*0.08))
        box_w=max(1,clip_w); box_h=max(1,clip_h-2*pad)
        # Shrink until the whole title fits the box on at most 3 lines.
        cfs=tfs; cf=tf
        for _ in range(14):
            lh_=max(1,int(cfs*1.18))
            ml_=max(1,min(3,box_h//lh_))
            rows=wrap_px(name,cf,box_w,0)
            if len(rows)<=ml_ and len(rows)*lh_<=box_h: break
            if cfs<=8: break
            cfs=max(8,int(cfs*0.9)); cf=pil_font(cfs,font_name)
        lh=max(1,int(cfs*1.18))
        ml=max(1,min(3,box_h//lh))
        rows=wrap_px(name,cf,box_w,ml)
        layer=Image.new("RGBA",(clip_w,clip_h),(0,0,0,0))
        ld=ImageDraw.Draw(layer)
        y0=max(0,(clip_h-len(rows)*lh)//2)
        for ri,row in enumerate(rows):
            ry=y0+ri*lh
            ld.text((1,ry+1),row,fill=shadow_col,font=cf)
            ld.text((0,ry),row,fill=tc_col,font=cf)
        img.alpha_composite(layer,(tx,y))
    elif active:
        # ── Active song name ──
        # Everything is rendered into a layer exactly the size of the text
        # area, so the name can never bleed outside the button.
        full_name=name
        try: fw=int(tf.getlength(full_name))
        except: fw=len(full_name)*int(tfs*0.55)
        clip_w=max(1,tw_avail); clip_h=max(1,h)

        # The active name ALWAYS scrolls, no matter how short it is.
        gap=int(tfs*3)
        cycle=max(1,fw+gap)
        txt_layer=Image.new("RGBA",(clip_w,clip_h),(0,0,0,0))
        tld=ImageDraw.Draw(txt_layer)
        if scroll_text:
            # Enter from the right edge, travel left, repeat seamlessly.
            # Enough repeats to keep the strip full even for short names.
            off=int(scroll_offset)%cycle
            start=clip_w-off
            reps=max(2,int(clip_w/cycle)+3)
        else:
            # Single baked frame (no-drawtext fallback): centre it instead of
            # freezing the scroll half-way off the button.
            start=(clip_w-fw)//2 if fw<=clip_w else 0
            reps=1
        for repeat in range(reps):
            dx=start-repeat*cycle
            if dx+fw<0: break
            tld.text((dx+1,ty-y+1),full_name,fill=shadow_col,font=tf)
            tld.text((dx,ty-y),full_name,fill=tc_col,font=tf)
        img.alpha_composite(txt_layer,(tx,y))
    else:
        # ── Static truncated text for inactive buttons ──
        # fit_px must measure with the SAME font we draw with, otherwise the
        # truncation is computed for the wrong glyph widths and the text
        # spills outside the button.
        dn=fit_px(name,tfs,tw_avail,font_name)
        _lay=Image.new("RGBA",(max(1,tw_avail),max(1,h)),(0,0,0,0))
        _ld=ImageDraw.Draw(_lay)
        _ld.text((1,ty-y+1),dn,fill=shadow_col,font=tf)
        _ld.text((0,ty-y),dn,fill=tc_col,font=tf)
        img.alpha_composite(_lay,(tx,y))


# ═══════════════════ HEADER TEXT ═══════════════════

def draw_header(img,text,ay,ah,fs,color,fp=None,efp=None,border_stroke=2,border_color=(0,0,0),alpha=255,
                shadow=False,shadow_blur=8,shadow_opacity=160,shadow_off=(4,4),shadow_color=(0,0,0)):
    if not text.strip(): return
    w=img.width
    try: font=ImageFont.truetype(fp,fs) if fp else pil_font(fs)
    except: font=pil_font(fs)
    ef=_lef(efp,fs) if efp else None; emh=int(fs*1.1); ec={}
    tokens=_seg(text); mw=int(w*0.88)
    def _tw(t,e): return emh if e else (font.getlength(t) if hasattr(font,'getlength') else fs*0.5)
    lines=[]; cl=[]; cw=0; wd=[]; ww=0
    def flush():
        nonlocal cl,cw,wd,ww
        if cw+ww>mw and cl: lines.append(cl); cl=[]; cw=0
        cl+=wd; cw+=ww; wd=[]; ww=0
    for t,e in tokens:
        tw=_tw(t,e)
        if t==" ": flush(); cl.append((t,e,tw)); cw+=tw
        else: wd.append((t,e,tw)); ww+=tw
    flush()
    if cl: lines.append(cl)
    if not lines: return
    try: asc,desc=font.getmetrics(); lh=int((asc+desc)*1.3)
    except: lh=int(fs*1.3)
    sy=ay+(ah-len(lines)*lh)//2
    if shadow:
        sox,soy=shadow_off; scr,scg,scb=shadow_color
        shl=Image.new("RGBA",img.size,(0,0,0,0)); shd=ImageDraw.Draw(shl)
        for li,line in enumerate(lines):
            lw=sum(tw for _,_,tw in line); lx=(w-lw)/2; ly=sy+li*lh; x_=lx
            for t,e,tw in line:
                if not e:
                    shd.text((x_+sox,ly+soy),t,fill=(scr,scg,scb,shadow_opacity),font=font)
                x_+=tw
        if shadow_blur>0: shl=shl.filter(ImageFilter.GaussianBlur(shadow_blur))
        img.alpha_composite(shl,(0,0))
    d=ImageDraw.Draw(img); rc,gc,bc=color; sw=max(0,border_stroke)
    for li,line in enumerate(lines):
        lw=sum(tw for _,_,tw in line); lx=(w-lw)/2; ly=sy+li*lh; x_=lx
        for t,e,tw in line:
            if e:
                if t not in ec: ec[t]=_eimg(t,ef,emh)
                ei=ec[t]
                if ei:
                    try: img.alpha_composite(ei,(int(x_),int(ly)))
                    except: pass
            else:
                bcr2,bcg2,bcb2=border_color
                if sw>0:
                    d.text((x_,ly),t,fill=(rc,gc,bc,alpha),font=font,stroke_width=sw,stroke_fill=(bcr2,bcg2,bcb2,200))
                else:
                    d.text((x_+1,ly+1),t,fill=(0,0,0,120),font=font)
                    d.text((x_,ly),t,fill=(rc,gc,bc,alpha),font=font)
            x_+=tw

# ═══════════════════ MAIN UI ═══════════════════

def _build_video_maker(frame):
    try: frame.configure(fg_color=BG_M)
    except: pass
    cfg=load_cfg()
    try: ctk.set_appearance_mode("dark")
    except: pass
    EF=find_efont(); SYS_FONTS=list_fonts()
    FONT_NAMES=["Default"]+sorted(SYS_FONTS.keys(),key=str.lower)[:60]

    st={"enc":"libx264","run":False,"bg":None,"bgp":None,"songs":[],"lp":None,
        "lnx":0.03,"lny":0.03,"at":0.0,"od":cfg.get("od",str(OUTPUT_DIR)),
        # drag positions (normalised 0-1 or pixel offsets)
        "hdr_ny":0.0,   # header Y normalised offset (0=top)
        "btn_ox":0,"btn_oy":0,  # button group pixel offset (full-res)
        "drag_el":None, # currently dragged element: "logo"|"header"|"buttons"
        "bgv":None,"bgv_paths":[],"bgv_prev":[],"bgv_fps":12,
        "gifs":[],      # [{path,nx,ny,sz}] overlay GIFs
        "cfonts":[],    # user-uploaded font files
        "hdr_styles":{},  # per-header-line {idx:{size,color,font}}
        }
    ui={}

    # ─ Global Font ─
    gfnv=tk.StringVar(value="Default")
    # ─ Header ─
    henv=tk.BooleanVar(value=True)
    hv=tk.StringVar(value=""); hsv=tk.IntVar(value=52); hcv=tk.StringVar(value="#FFFFFF")
    hspv=tk.IntVar(value=42); hfxv=tk.StringVar(value="None")
    hbor_wv=tk.IntVar(value=2); hborcv=tk.StringVar(value="#000000")
    HFX=["None","Wave","Fade In","Slide Up","Glow Pulse"]
    # ─ Header drop shadow ─
    hdshenv=tk.BooleanVar(value=False)
    hdshblv=tk.IntVar(value=8); hdshopv=tk.IntVar(value=160)
    hdshoxv=tk.IntVar(value=4); hdshoyv=tk.IntVar(value=4)
    hdshcv=tk.StringVar(value="#000000")
    # ─ Logo ─
    le=tk.BooleanVar(value=False); lsv=tk.IntVar(value=120)
    lrv=tk.BooleanVar(value=False); lfv=tk.StringVar(value="None")
    LFX=["None","Spin","Orbit","Spin + Orbit","Ring Spin"]
    # ─ Buttons ─
    benv=tk.BooleanVar(value=True)
    bhv=tk.IntVar(value=72); bwv=tk.IntVar(value=420); bpv=tk.IntVar(value=20)
    bgpv=tk.IntVar(value=16)
    bcv=tk.IntVar(value=25); bcolv=tk.StringVar(value="Auto")
    bbgv=tk.StringVar(value="#FFF8F3"); btcv=tk.StringVar(value="#000000")
    bfnv=tk.StringVar(value="Default"); bov=tk.IntVar(value=60)
    bborcv=tk.StringVar(value="#FFFFFF")
    bbor_wv=tk.IntVar(value=2); bbor_av=tk.IntVar(value=180)
    bfsv=tk.IntVar(value=0)
    # ─ GIF overlays ─
    genv=tk.BooleanVar(value=False)
    gszv=tk.IntVar(value=180)
    gselv=tk.StringVar(value="")
    gckv=tk.BooleanVar(value=False)
    gckcv=tk.StringVar(value="#00FF00")
    gcksv=tk.IntVar(value=30); gckbv=tk.IntVar(value=10)
    bwrapv=tk.BooleanVar(value=True)
    bscrollv=tk.BooleanVar(value=True)     # marquee on the playing song
    thmv=tk.StringVar(value="Auto (from background)")
    thautov=tk.BooleanVar(value=True)      # re-theme when a background loads
    bnbautov=tk.BooleanVar(value=True)
    bnbcv=tk.StringVar(value="#E63946"); bntcv=tk.StringVar(value="#FFFFFF")
    hlselv=tk.StringVar(value=""); hlszv=tk.IntVar(value=0)
    hlcv=tk.StringVar(value="#FFFFFF"); hlfv=tk.StringVar(value="Default")
    thenv=tk.BooleanVar(value=True); thmodev=tk.StringVar(value="Last frame")
    thatv=tk.IntVar(value=0)
    # ─ Visualizer ─
    vsenv=tk.BooleanVar(value=True)
    # ─ Button gap (row + col) ─
    bgpv_col=tk.IntVar(value=16)   # column gap
    bgvenv=tk.BooleanVar(value=True)
    bgvfpsv=tk.IntVar(value=12)
    bgvmaxv=tk.IntVar(value=60)
    btn_bgalphav=tk.IntVar(value=90)  # button bg alpha
    # ─ Overlay (falling symbols) ─
    ovenv=tk.BooleanVar(value=False)
    ovspdv=tk.IntVar(value=5)   # fall speed 1-20
    ovopv=tk.IntVar(value=80)   # opacity 10-220
    ovsymv=tk.StringVar(value="Christian")
    OV_SYMS={"Christian":["✝","✞","✟","☦","☧","☩","☪","✡"],
              "Cross Only":["✝","✞","✟","☨","☩"],
              "Stars & Cross":["✡","✝","✦","★","✟","✶","✞"]}

    vsv=tk.StringVar(value="Bars Cyan")
    VS=[("Bars Cyan","fbar","0x00e5ff|0xfb7185"),("Bars Fire","fbar","0xff5e00|0xffd000"),
        ("Bars Purple","fbar","0xa855f7|0xec4899"),("Bars Neon","fbar","0x39ff14|0x00e5ff"),
        ("Bars Gold","fbar","0xffd700|0xff9500"),("Bars Rose","fbar","0xfb7185|0xffd700")]
    VSN=[s[0] for s in VS]; VSM={s[0]:s for s in VS}

    lpv=tk.IntVar(value=1); sfv=tk.BooleanVar(value=False)
    ov=tk.StringVar(value="song_video_output"); odv=tk.StringVar(value=st["od"])
    PW,PH=600,338; SC=PW/VW  # scale factor for preview

    # One source of truth for logo size so preview == output exactly.
    def _logo_sz_full(): return max(40,int(lsv.get()*VW/1280.0))
    def _logo_sz_prev(): return max(4,int(_logo_sz_full()*SC))

    def _card(p,t):
        o=ctk.CTkFrame(p,fg_color=BG_C,corner_radius=10,border_width=1,border_color=BC)
        o.pack(fill="x",padx=6,pady=5)
        ctk.CTkLabel(o,text=t,font=ctk.CTkFont(size=13,weight="bold"),text_color=AR).pack(anchor="w",padx=14,pady=(10,2))
        i=ctk.CTkFrame(o,fg_color="transparent"); i.pack(fill="x",padx=14,pady=(0,10)); return i

    def _lg(w,m):
        ts=time.strftime("%H:%M:%S"); w.configure(state="normal"); w.insert("end",f"[{ts}] {m}\n"); w.see("end"); w.configure(state="disabled")

    def _h2r(h):
        h=h.lstrip("#")
        try: return (int(h[0:2],16),int(h[2:4],16),int(h[4:6],16))
        except: return (255,248,243)
    def _il(h):
        try: h=h.lstrip("#"); return (int(h[0:2],16)*299+int(h[2:4],16)*587+int(h[4:6],16)*114)/1000>128
        except: return True
    def _ci():
        v=bcolv.get()
        try: return int(v)
        except: return 0

    # ═══ PREVIEW (16:9 LOCKED) ═══
    def _compose(t=0.0):
        # ALL grid computed at 1920×1080, then SCALED to preview
        canvas=Image.new("RGBA",(PW,PH),(40,15,20,255))
        hf=hspv.get()/100.0; hh_full=int(VH*hf)

        bg=None
        _bvp=st.get("bgv_prev") or []
        if bgvenv.get() and _bvp:
            _bi=_bgv_frame_index(t,len(_bvp),st.get("bgv_fps",12))
            bg=_bvp[_bi]
        if bg is None: bg=st.get("bgp")
        if bg: canvas.paste(bg.resize((PW,PH),Image.LANCZOS),(0,0))
        else:
            d=ImageDraw.Draw(canvas)
            d.text((PW//2,PH//2),"Upload a background image or video",fill=(200,140,150,200),font=pil_font(16),anchor="mm",align="center")

        fn=find_font(gfnv.get())  # global font
        htxt=hv.get().strip()
        if htxt and henv.get():
            hfs=max(2,int(max(16,hsv.get())*SC)); hh_pv=int(hh_full*SC)
            hdr_dy_pv=int(st.get("hdr_ny",0.0)*VH*SC)
            hcol=_h2r(hcv.get()); hbsw=hbor_wv.get(); hbc=_h2r(hborcv.get())
            hfx=hfxv.get()
            if hfx=="None":
                draw_header_multi(canvas,htxt,hdr_dy_pv,hh_pv,hfs,hcol,fn,EF,border_stroke=hbsw,border_color=hbc,line_styles=_hdr_styles_preview(),**_hdr_shadow_kw())
            elif hfx=="Wave":
                oy=hdr_dy_pv+int(8*math.sin(t*1.8))
                draw_header_multi(canvas,htxt,oy,hh_pv,hfs,hcol,fn,EF,border_stroke=hbsw,border_color=hbc,line_styles=_hdr_styles_preview(),**_hdr_shadow_kw())
            elif hfx=="Fade In":
                alp=min(255,int(255*min(1.0,t/2.5)))
                draw_header_multi(canvas,htxt,hdr_dy_pv,hh_pv,hfs,hcol,fn,EF,border_stroke=hbsw,border_color=hbc,alpha=alp,line_styles=_hdr_styles_preview(),**_hdr_shadow_kw())
            elif hfx=="Slide Up":
                oy=hdr_dy_pv+max(-hh_pv,int(PH*(1-min(1.0,t/2.0))))
                draw_header_multi(canvas,htxt,oy,hh_pv,hfs,hcol,fn,EF,border_stroke=hbsw,border_color=hbc,line_styles=_hdr_styles_preview(),**_hdr_shadow_kw())
            elif hfx=="Glow Pulse":
                pulse=0.55+0.45*math.sin(t*2.5)
                gc_=tuple(min(255,int(c*pulse+255*(1-pulse))) for c in hcol)
                draw_header_multi(canvas,htxt,hdr_dy_pv,hh_pv,hfs,gc_,fn,EF,border_stroke=hbsw,border_color=hbc,line_styles=_hdr_styles_preview(),**_hdr_shadow_kw())

        songs=st.get("songs",[])
        if songs and benv.get():
            gox=int(st.get("btn_ox",0)); goy=int(st.get("btn_oy",0))
            grid_full=compute_grid(len(songs),int(VW*0.03),hh_full+goy,int(VW*0.94),VH-hh_full,
                                   bpv.get(),bgpv.get(),bgpv_col.get(),bhv.get(),bwv.get(),_ci())
            # Apply button group drag offset
            grid_full=[(x+gox,y,w,h,i,c) for x,y,w,h,i,c in grid_full]
            grid_prev=scale_grid(grid_full,SC)
            cr=bcv.get(); tc=_h2r(btcv.get())
            bo=bov.get()/100.0
            bborc=_h2r(bborcv.get()); bborw=bbor_wv.get(); bbora=bbor_av.get()
            bfs=bfsv.get()
            for gx,gy,gw,gh,idx,col in grid_prev:
                is_act=(idx==0)
                scroll_off=int(t*80)
                draw_btn(canvas,gx,gy,gw,gh,idx+1,ctn(songs[idx]),col,
                         active=is_act,corner=cr,
                         txt_color=tc,font_name=gfnv.get(),t_anim=t,
                         border_color=bborc,border_width=bborw,border_alpha=bbora,
                         scroll_offset=scroll_off if is_act else 0,
                         font_size=int(bfs*SC) if bfs>0 else 0,
                         btn_bg_alpha=btn_bgalphav.get(),
                         wrap_text=bwrapv.get(),scroll_active=bscrollv.get(),badge_color=None if bnbautov.get() else _h2r(bnbcv.get()),badge_txt=_h2r(bntcv.get()))

        if le.get() and st.get("lp") and os.path.isfile(st["lp"]):
            try:
                lsz=_logo_sz_prev(); limg=prep_logo(st["lp"],lsz,rm=lrv.get())
                fx=lfv.get()
                lx=int((PW-limg.width)*st["lnx"]); ly=int((PH-limg.height)*st["lny"])
                if fx=="Ring Spin":
                    try:
                        ring=mk_ring(int(lsz*1.5),(255,90,120)).rotate((t*70)%360,resample=Image.BICUBIC)
                        canvas.alpha_composite(ring,(lx+limg.width//2-ring.width//2,ly+limg.height//2-ring.height//2))
                    except: pass
                if fx in ("Spin","Spin + Orbit"): limg=limg.rotate(-(t*92)%360,resample=Image.BICUBIC,expand=False)
                if fx in ("Orbit","Spin + Orbit"):
                    R=max(10,int(lsz*0.55))
                    lx+=int(R*math.cos(2*math.pi*t/5)); ly+=int(R*math.sin(2*math.pi*t/5))
                lx=max(0,min(PW-limg.width,lx)); ly=max(0,min(PH-limg.height,ly))
                canvas.alpha_composite(limg,(lx,ly))
            except: pass
        # ── GIF overlays (animate live in the preview) ──
        if genv.get():
            _gif_sync_sel()
            for g in st.get("gifs",[]):
                try:
                    fr,dl=gif_frames(g.get("path",""))
                    im_=gif_frame_at(fr,dl,t)
                    if im_ is None: continue
                    gw=max(4,int(g.get("sz",180)*SC))
                    gh_=max(4,int(im_.height*gw/max(1,im_.width)))
                    im_=im_.resize((gw,gh_),Image.LANCZOS)
                    if g.get("ck"):
                        im_=chroma_key(im_,g.get("ckc","#00FF00"),
                                       g.get("cks",30),g.get("ckb",10))
                    gx_=int((PW-gw)*g.get("nx",0.5)); gy_=int((PH-gh_)*g.get("ny",0.5))
                    canvas.alpha_composite(im_,(max(0,min(PW-gw,gx_)),max(0,min(PH-gh_,gy_))))
                except Exception: pass
        _draw_falling_symbols(canvas,st.get("at",0.0),PW,PH)
        return canvas

    def _ref():
        if "plbl" not in ui: return
        try:
            img=_compose(st.get("at",0.0))
            tki=ctk.CTkImage(light_image=img,dark_image=img,size=(PW,PH))
            ui["plbl"].configure(image=tki,text=""); ui["plbl"]._i=tki
        except Exception as e: ui["plbl"].configure(text=str(e)[:80])

    def _sym_font(sz):
        """Return a font that renders cross/dagger unicode chars."""
        if SYMBOL_FONT:
            try: return ImageFont.truetype(SYMBOL_FONT,sz)
            except: pass
        return pil_font(sz)

    def _draw_falling_symbols(canvas,t,pw,ph):
        """Draw falling Christian symbols overlay on preview canvas."""
        if not ovenv.get(): return
        syms=OV_SYMS.get(ovsymv.get(),OV_SYMS["Christian"])
        spd=ovspdv.get()*30.0  # pixels per second
        op=min(255,max(10,ovopv.get()))
        count=16  # number of falling symbols
        import hashlib
        fsz=max(14,int(ph*0.055))
        ov_layer=Image.new("RGBA",(pw,ph),(0,0,0,0))
        od=ImageDraw.Draw(ov_layer)
        for i in range(count):
            h_=int(hashlib.md5(str(i).encode()).hexdigest(),16)
            sym=syms[i%len(syms)]
            sx=int((h_%997)/997.0*pw)
            phase=(h_>>10)%100/100.0
            sz_factor=0.6+0.8*(i%4)/4.0
            fsz_i=max(10,int(fsz*sz_factor))
            sf_i=_sym_font(fsz_i)
            cycle=ph+fsz_i
            pos_y=int((t*spd+phase*cycle)%cycle)-fsz_i
            # opacity varies per symbol for depth effect
            op_i=min(255,max(30,int(op*(0.5+0.5*sz_factor))))
            col=(255,255,255,op_i)
            try: od.text((sx,pos_y),sym,fill=col,font=sf_i)
            except: pass
        canvas.alpha_composite(ov_layer,(0,0))

    def _tick():
        try:
            if not st.get("run") and "plbl" in ui:
                need=(le.get() and lfv.get()!="None") or st.get("songs")
                if need: st["at"]=st.get("at",0.0)+0.09; _ref()
        except: pass
        frame.after(100,_tick)

    def _ar(*_): frame.after(40,_ref)

    def _identify_drag(e):
        """Identify which element is near click position for drag."""
        # GIFs sit on top, so hit-test them first (last added = topmost)
        if genv.get():
            gl=st.get("gifs",[])
            for i in range(len(gl)-1,-1,-1):
                g=gl[i]
                gw=max(4,int(g.get("sz",180)*SC))
                gh_=max(4,int(gif_size_at(g.get("path",""),g.get("sz",180))*SC))
                gx_=int((PW-gw)*g.get("nx",0.5)); gy_=int((PH-gh_)*g.get("ny",0.5))
                if gx_<=e.x<=gx_+gw and gy_<=e.y<=gy_+gh_:
                    return "gif:%d"%i
        hh_pv=int(int(VH*hspv.get()/100)*SC)
        # Header zone: top area
        if henv.get() and e.y < hh_pv + 30:
            return "header"
        # Logo zone: near logo
        if le.get() and st.get("lp"):
            lsz=_logo_sz_prev()
            lx_=int((PW-lsz)*st["lnx"]); ly_=int((PH-lsz)*st["lny"])
            if abs(e.x-lx_-lsz//2)<lsz and abs(e.y-ly_-lsz//2)<lsz:
                return "logo"
        # Buttons zone
        if st.get("songs") and benv.get():
            return "buttons"
        return None

    def _drag_start(e):
        st["drag_el"]=_identify_drag(e)
        st["drag_sx"]=e.x; st["drag_sy"]=e.y
        st["drag_ox"]=st.get("btn_ox",0); st["drag_oy"]=st.get("btn_oy",0)
        el=st["drag_el"]
        if isinstance(el,str) and el.startswith("gif:"):
            try: gi=int(el.split(":")[1])
            except Exception: gi=-1
            gl=st.get("gifs",[])
            if 0<=gi<len(gl):
                g=gl[gi]
                st["gif_drag_nx0"]=g.get("nx",0.5); st["gif_drag_ny0"]=g.get("ny",0.5)
                st["gif_drag_gw"]=max(4,int(g.get("sz",180)*SC))
                st["gif_drag_gh"]=max(4,int(gif_size_at(g.get("path",""),g.get("sz",180))*SC))

    def _drag(e):
        el=st.get("drag_el")
        if el is None: el=_identify_drag(e)
        if isinstance(el,str) and el.startswith("gif:"):
            try: gi=int(el.split(":")[1])
            except Exception: gi=-1
            gl=st.get("gifs",[])
            if 0<=gi<len(gl):
                g=gl[gi]
                gw=st.get("gif_drag_gw") or max(4,int(g.get("sz",180)*SC))
                gh_=st.get("gif_drag_gh") or max(4,int(gif_size_at(g.get("path",""),g.get("sz",180))*SC))
                nx0=st.get("gif_drag_nx0",g.get("nx",0.5)); ny0=st.get("gif_drag_ny0",g.get("ny",0.5))
                dx=e.x-st.get("drag_sx",e.x); dy=e.y-st.get("drag_sy",e.y)
                rangex=max(1,PW-gw); rangey=max(1,PH-gh_)
                g["nx"]=max(0.0,min(1.0,nx0+dx/rangex))
                g["ny"]=max(0.0,min(1.0,ny0+dy/rangey))
            _ref(); return
        if el=="logo":
            lsz=_logo_sz_prev()
            nx=max(0,min(1,(e.x-lsz/2)/max(1,PW-lsz))); ny=max(0,min(1,(e.y-lsz/2)/max(1,PH-lsz)))
            st["lnx"]=nx; st["lny"]=ny
            if "lpos" in ui: ui["lpos"].configure(text=f"x:{nx:.2f} y:{ny:.2f}")
        elif el=="header":
            ny=max(0.0,min(0.5,e.y/max(1,PH)))
            st["hdr_ny"]=ny
        elif el=="buttons":
            dx=int((e.x-st.get("drag_sx",e.x))/SC); dy=int((e.y-st.get("drag_sy",e.y))/SC)
            st["btn_ox"]=st.get("drag_ox",0)+dx
            st["btn_oy"]=st.get("drag_oy",0)+dy
        _ref()

    # ══ custom font upload ══
    def _reg_font(p):
        """Register an uploaded font so find_font()/the dropdown can use it."""
        if not p or not os.path.isfile(p): return None
        try: ImageFont.truetype(p,20)
        except Exception: return None
        disp=os.path.splitext(os.path.basename(p))[0]
        _FONT_PATHS[disp.lower()]=p
        SYS_FONTS[disp]=p
        if disp not in FONT_NAMES: FONT_NAMES.append(disp)
        if p not in st.setdefault("cfonts",[]): st["cfonts"].append(p)
        if "fontdd" in ui:
            try: ui["fontdd"].configure(values=FONT_NAMES)
            except Exception: pass
        return disp

    def _ufont():
        fs=filedialog.askopenfilenames(title="Upload font(s)",
                                       filetypes=[("Fonts","*.ttf *.otf *.ttc"),("All","*.*")])
        if not fs: return
        last=None
        for f in fs:
            d_=_reg_font(f)
            if d_: last=d_
        if not last:
            messagebox.showerror("Font","Could not load that font file.")
            return
        gfnv.set(last)
        if "fontup" in ui:
            ui["fontup"].configure(text="✔ "+last)
        _ar()

    # ══ GIF overlays ══
    def _gif_names():
        out=[]
        for i,g in enumerate(st.get("gifs",[])):
            out.append("%d. %s"%(i+1,os.path.basename(g.get("path",""))))
        return out

    def _gif_sel_index():
        v=gselv.get()
        if not v: return -1
        try: return int(v.split(".")[0])-1
        except Exception: return -1

    def _refresh_gifs():
        names=_gif_names()
        if "gif_lb" in ui:
            ui["gif_lb"].configure(text=("\n".join(names) if names else "No GIFs added"))
        if "gif_dd" in ui:
            try:
                ui["gif_dd"].configure(values=names if names else [""])
            except Exception: pass
            if names and gselv.get() not in names: gselv.set(names[0])
            if not names: gselv.set("")
        _ar()

    def _add_gif():
        fs=filedialog.askopenfilenames(title="Choose GIF(s)",
                                       filetypes=[("Animated / images","*.gif *.webp *.png"),("All","*.*")])
        if not fs: return
        for f in fs:
            st.setdefault("gifs",[]).append(
                {"path":f,"nx":0.5,"ny":0.5,"sz":gszv.get(),
                 "ck":bool(gckv.get()),"ckc":gckcv.get(),
                 "cks":gcksv.get(),"ckb":gckbv.get()})
        genv.set(True)
        _refresh_gifs()

    def _hdr_lines():
        return str(hv.get()).replace("\r","").split("\n")

    def _hdr_styles():
        return st.setdefault("hdr_styles",{})

    def _hdr_styles_preview():
        """Per-line styles scaled for the small preview canvas.

        Size overrides are stored as full-resolution (1920x1080) pixel
        values — the same numbers used at export time — so they must be
        scaled by SC for the preview canvas, exactly like the global header
        size already is. Without this, a custom line size looks correct in
        the compact preview box but ends up a completely different
        proportion of the real 1920x1080 frame.
        """
        out={}
        for k,v in _hdr_styles().items():
            v2=dict(v)
            if v2.get("size"): v2["size"]=max(2,int(v2["size"]*SC))
            out[k]=v2
        return out

    def _hdr_shadow_kw():
        return dict(shadow=hdshenv.get(),shadow_blur=hdshblv.get(),
                    shadow_opacity=hdshopv.get(),
                    shadow_off=(hdshoxv.get(),hdshoyv.get()),
                    shadow_color=_h2r(hdshcv.get()))

    _hdr_loading=[False]

    def _hdr_line_labels():
        out=[]
        for i,l in enumerate(_hdr_lines()):
            t=l.strip() or "(empty)"
            out.append("%d: %s"%(i+1,t[:28]))
        return out or ["1: (empty)"]

    def _hdr_sel_index():
        try: return int(str(hlselv.get()).split(":")[0])-1
        except Exception: return -1

    def _hdr_load_line(*_a):
        _hdr_loading[0]=True
        try:
            i=_hdr_sel_index(); stl=_hdr_styles().get(str(i),{})
            hlszv.set(int(stl.get("size") or 0))
            hlcv.set(stl.get("color") or hcv.get())
            hlfv.set(stl.get("font") or "Default")
            cvv=hlcv.get()
            if "hlcb" in ui:
                try: ui["hlcb"].configure(text="\u25A0 "+cvv,fg_color=cvv,
                                          text_color="#000" if _il(cvv) else "#fff")
                except Exception: pass
        finally:
            _hdr_loading[0]=False
        _ar()

    def _hdr_fetch(*_a):
        """Re-read the header lines and refresh the per-line dropdown."""
        vals=_hdr_line_labels()
        if "hdr_dd" in ui:
            try: ui["hdr_dd"].configure(values=vals)
            except Exception: pass
        if hlselv.get() not in vals: hlselv.set(vals[0])
        _hdr_load_line()

    def _hdr_apply_line(*_a):
        if _hdr_loading[0]: return
        i=_hdr_sel_index()
        if i<0: return
        e=_hdr_styles().setdefault(str(i),{})
        e["size"]=int(hlszv.get()) or None
        e["color"]=hlcv.get()
        e["font"]=hlfv.get()
        _ar()

    def _hdr_reset_line():
        _hdr_styles().pop(str(_hdr_sel_index()),None)
        _hdr_load_line()

    def _hdr_reset_all():
        st["hdr_styles"]={}
        _hdr_load_line()

    def _th_browse():
        p=filedialog.askopenfilename(title="Choose a video",
            filetypes=[("Video","*.mp4 *.mkv *.mov *.avi *.webm"),("All","*.*")])
        if not p: return
        o=os.path.splitext(p)[0]+"_thumbnail.jpg"
        r=extract_thumb(p,o,thmodev.get().split()[0].lower(),thatv.get())
        if r: messagebox.showinfo("Thumbnail","Saved:\n"+r)
        else: messagebox.showerror("Thumbnail","Could not extract a frame from that file.")

    def _gif_size_apply():
        """Push size + chroma-key controls onto the selected GIF."""
        i=_gif_sel_index(); gl=st.get("gifs",[])
        if 0<=i<len(gl):
            g=gl[i]
            g["sz"]=gszv.get()
            g["ck"]=bool(gckv.get()); g["ckc"]=gckcv.get()
            g["cks"]=gcksv.get(); g["ckb"]=gckbv.get()
        _refresh_gifs()

    def _gif_sync_sel():
        """Live-apply the editor controls to the selected GIF (realtime preview)."""
        i=_gif_sel_index(); gl=st.get("gifs",[])
        if 0<=i<len(gl):
            g=gl[i]
            g["sz"]=gszv.get()
            g["ck"]=bool(gckv.get()); g["ckc"]=gckcv.get()
            g["cks"]=gcksv.get(); g["ckb"]=gckbv.get()

    def _gif_sel_changed(*_a):
        """Load the newly selected GIF's settings into the editor controls."""
        i=_gif_sel_index(); gl=st.get("gifs",[])
        if 0<=i<len(gl):
            g=gl[i]
            gszv.set(int(g.get("sz",180)))
            gckv.set(bool(g.get("ck",False)))
            gckcv.set(g.get("ckc","#00FF00"))
            gcksv.set(int(g.get("cks",30)))
            gckbv.set(int(g.get("ckb",10)))
            cvv=gckcv.get()
            if "gifck" in ui:
                try: ui["gifck"].configure(text="\u25A0 "+cvv,fg_color=cvv,
                                           text_color="#000" if _il(cvv) else "#fff")
                except Exception: pass
        _ar()

    def _del_gif_sel():
        i=_gif_sel_index(); gl=st.get("gifs",[])
        if 0<=i<len(gl):
            gl.pop(i)
        _refresh_gifs()

    def _clear_gifs():
        st["gifs"]=[]
        _refresh_gifs()

    def _swatch(var,key):
        """Repaint a colour-picker button after a theme changes its value."""
        b=ui.get(key)
        if b is None: return
        try: b.configure(text="\u25A0 "+var.get(),fg_color=var.get())
        except Exception: pass

    def _theme_bg_image():
        """Whatever the user is actually using as the backdrop right now."""
        if bgvenv.get() and st.get("bgv_prev"): return st["bgv_prev"][0]
        return st.get("bgp")

    def _theme_status(msg,col):
        lb=ui.get("theme_lbl")
        if lb is None: return
        try: lb.configure(text=msg,text_color=col)
        except Exception: pass

    def _apply_theme(name=None,announce=True):
        """Apply a palette. name=None means 'work it out from the background'."""
        img=_theme_bg_image()
        if name in (None,"","Auto (from background)"):
            if img is None:
                if announce: _theme_status("Load a background image or video first",AY)
                return None
            th,stt=suggest_theme(img)
        else:
            th=get_theme(name); stt=bg_stats(img) if img is not None else None
        dark=bool(stt and stt["val"]<0.55)
        bbgv.set(th["btn_bg"]); bborcv.set(th["btn_border"]); btcv.set(th["btn_text"])
        bnbautov.set(False); bnbcv.set(th["badge"]); bntcv.set(th["badge_txt"])
        hcv.set(th["hdr_on_dark"] if dark else th["hdr_on_light"])
        hborcv.set(th["hdr_border_on_dark"] if dark else th["hdr_border_on_light"])
        btn_bgalphav.set(th["btn_alpha"]); bbor_av.set(th["btn_border_alpha"])
        for _v,_k in [(bbgv,"bbg"),(bborcv,"bborc"),(btcv,"btc"),(bnbcv,"bnbc"),
                      (bntcv,"bntc"),(hcv,"hcb"),(hborcv,"hborc")]:
            _swatch(_v,_k)
        # Remember what was actually applied, so a preset saved now
        # stores this palette and not a stale dropdown value.
        try: thmv.set(th["name"])
        except Exception: pass
        if announce:
            _theme_status("Applied: %s   (%s background)"%(th["name"],"dark" if dark else "light"),AG)
        _ar()
        return th

    def _auto_theme_from_bg():
        """Called whenever a new background image / video is loaded."""
        if not thautov.get(): return
        th=_apply_theme(None,announce=True)
        if th is not None:
            try: thmv.set(th["name"])
            except Exception: pass

    def _theme_pick(choice):
        _apply_theme(None if str(choice).startswith("Auto") else choice)

    def _bbg():
        f=filedialog.askopenfilename(title="Background",filetypes=[("Images","*.png *.jpg *.jpeg *.webp *.bmp"),("All","*.*")])
        if not f: return
        st["bg"]=f
        try: st["bgp"]=Image.open(f).convert("RGBA")
        except: st["bgp"]=None
        ui["bgl"].configure(text=os.path.basename(f),text_color=T1)
        _auto_theme_from_bg()
        _ref()

    def _bbgv():
        f=filedialog.askopenfilename(title="Background Video",
            filetypes=[("Videos","*.mp4 *.mov *.mkv *.avi *.webm *.m4v *.flv"),("All","*.*")])
        if not f: return
        ui["bgvl"].configure(text="Extracting frames... please wait",text_color=AY)
        def _w():
            try:
                d=TEMP_DIR/"bgv_frames"
                shutil.rmtree(d,ignore_errors=True); d.mkdir(parents=True,exist_ok=True)
                fps=max(4,int(bgvfpsv.get())); cap=max(8,int(bgvmaxv.get()))
                pat=str(d/"f%05d.jpg")
                vf="fps=%d,scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d"%(fps,VW,VH,VW,VH)
                _rq([FF,"-y","-i",f,"-vf",vf,"-frames:v",str(cap),"-q:v","3",pat],capture_output=True)
                paths=sorted(str(p) for p in d.glob("f*.jpg"))
                if not paths: raise RuntimeError("no frames extracted")
                prev=[]
                for p in paths:
                    im=Image.open(p).convert("RGBA"); im=im.resize((PW,PH),Image.LANCZOS); prev.append(im)
                st["bgv"]=f; st["bgv_paths"]=paths; st["bgv_prev"]=prev; st["bgv_fps"]=fps
                nm=os.path.basename(f); cnt=len(paths); cyc=(2*cnt-2)/float(fps) if cnt>1 else 0
                def _done():
                    ui["bgvl"].configure(text="%s  (%d frames, %.1fs boomerang)"%(nm,cnt,cyc),text_color=T1)
                    _auto_theme_from_bg()
                    _ref()
                frame.after(0,_done)
            except Exception as ex:
                msg=str(ex)[:60]
                frame.after(0,lambda: ui["bgvl"].configure(text="Failed: "+msg,text_color=AX))
        threading.Thread(target=_w,daemon=True).start()

    def _clr_bgv():
        st["bgv"]=None; st["bgv_paths"]=[]; st["bgv_prev"]=[]
        ui["bgvl"].configure(text="No video (using image)",text_color=T2); _ref()

    def _bgv_frame_index(t,total,fps):
        """Boomerang (forward+reverse) index for time t."""
        if total<=1: return 0
        cyc=2*total-2
        k=int(t*fps)%cyc
        return k if k<total else cyc-k

    def _bsn():
        d=filedialog.askdirectory(title="Songs Folder")
        if not d: return
        fs=[os.path.join(d,f) for f in os.listdir(d) if os.path.splitext(f)[1].lower() in A_EXT]
        fs.sort(key=lambda p:nsk(os.path.basename(p))); st["songs"]=fs
        ui["sb"].configure(state="normal"); ui["sb"].delete("1.0","end")
        if fs:
            for i,fp in enumerate(fs,1): ui["sb"].insert("end",f"{i:>2}. {ctn(fp)}\n")
            c,r=auto_grid(len(fs),_ci()); ui["sc"].configure(text=f"{len(fs)} songs \u2022 {c}\u00D7{r}",text_color=AG)
        else: ui["sb"].insert("end","No audio.\n"); ui["sc"].configure(text="No songs",text_color=AX)
        ui["sb"].configure(state="disabled"); _ref()

    def _ulo():
        f=filedialog.askopenfilename(title="Logo",filetypes=[("Images","*.png *.jpg *.jpeg *.webp *.bmp *.gif"),("All","*.*")])
        if not f: return
        st["lp"]=f; le.set(True); ui["ll"].configure(text=os.path.basename(f),text_color=T1); _ref()

    # ═══ PROGRESS ═══
    SR=[(0,0.12),(0.12,0.45),(0.45,0.95),(0.95,1.0)]
    def _bl(m): frame.after(0,lambda:_lg(ui["log"],m))
    def _pr(f,l=None):
        f=max(0,min(1,f))
        if l: frame.after(0,lambda:(ui["pb"].set(f),ui["pl"].configure(text=l)))
        else: frame.after(0,lambda:ui["pb"].set(f))
    def _su(t): frame.after(0,lambda:ui["sl"].configure(text=t))
    def _ss(i,a=True,d=False,done=False):
        d = d or done
        def _():
            if i>=len(ui["steps"]): return
            f,l=ui["steps"][i]
            if d: f.configure(fg_color=AG); l.configure(text_color="#0a2a14")
            elif a: f.configure(fg_color=AR); l.configure(text_color="#fff")
            else: f.configure(fg_color=BG_I); l.configure(text_color=TM)
        frame.after(0,_)
    def _sp(si,sf,l=None): lo,hi=SR[si]; _pr(lo+(hi-lo)*max(0,min(1,sf)),l)

    def _rff(args,dur,si,label):
        _ss(si,True)
        ra=args[:-1]+["-progress","pipe:1","-nostats",args[-1]]
        proc=subprocess.Popen(ra,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                              universal_newlines=True,encoding="utf-8",errors="replace",creationflags=_NW)
        tail=collections.deque(maxlen=20); cur=0.0
        ot=re.compile(r"out_time=(\d+):(\d+):(\d+\.\d+)"); tm=re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
        fr="0"; fps="0"; spd=""
        for line in proc.stdout:
            line=line.strip()
            if not line: continue
            if line.startswith("frame="): fr=line.split("=",1)[1].strip()
            elif line.startswith("fps="): fps=line.split("=",1)[1].strip()
            elif line.startswith("speed="): spd=line.split("=",1)[1].strip()
            elif line.startswith("out_time="):
                m=ot.search(line)
                if m: cur=int(m.group(1))*3600+int(m.group(2))*60+float(m.group(3))
            else:
                tail.append(line); m=tm.search(line)
                if m: cur=int(m.group(1))*3600+int(m.group(2))*60+float(m.group(3))
            if dur>0:
                _sp(si,cur/dur,f"{label} {max(0,min(100,int(cur/dur*100)))}%")
                _su(f"{label}: frame {fr} \u2022 {fps} fps \u2022 {spd}")
        proc.wait()
        if proc.returncode!=0: raise RuntimeError(f"FFmpeg fail ({label}):\n"+"\n".join(tail))
        _sp(si,1.0,label)

    # ═══ RENDER ═══
    # === PRESET SYSTEM ===
    def _collect_settings():
        return {
            "global_font":gfnv.get(),
            "hdr_en":henv.get(),"hdr_txt":hv.get(),"hdr_size":hsv.get(),
            "hdr_styles":dict(st.get("hdr_styles",{})),
            "hdr_col":hcv.get(),"hdr_area":hspv.get(),"hdr_fx":hfxv.get(),
            "hdr_bw":hbor_wv.get(),"hdr_bc":hborcv.get(),
            "hdr_sh_en":hdshenv.get(),"hdr_sh_blur":hdshblv.get(),"hdr_sh_op":hdshopv.get(),
            "hdr_sh_ox":hdshoxv.get(),"hdr_sh_oy":hdshoyv.get(),"hdr_sh_col":hdshcv.get(),
            "btn_en":benv.get(),"btn_h":bhv.get(),"btn_w":bwv.get(),
            "btn_wrap":bwrapv.get(),"badge_auto":bnbautov.get(),
            "btn_scroll":bscrollv.get(),
            "theme":thmv.get(),"theme_auto":thautov.get(),
            "badge_col":bnbcv.get(),"badge_txt":bntcv.get(),
            "thumb_en":thenv.get(),"thumb_mode":thmodev.get(),"thumb_at":thatv.get(),
            "btn_pad":bpv.get(),"btn_rgap":bgpv.get(),"btn_cgap":bgpv_col.get(),
            "btn_corner":bcv.get(),"btn_cols":bcolv.get(),
            "btn_tc":btcv.get(),"btn_op":bov.get(),
            "btn_borc":bborcv.get(),"btn_borw":bbor_wv.get(),"btn_bora":bbor_av.get(),
            "btn_fs":bfsv.get(),"btn_bga":btn_bgalphav.get(),
            "btn_bg":bbgv.get(),"btn_font":bfnv.get(),
            "logo_en":le.get(),"logo_sz":lsv.get(),"logo_rm":lrv.get(),
            "logo_fx":lfv.get(),"logo_nx":st.get("lnx",0.03),"logo_ny":st.get("lny",0.03),
            "vs_en":vsenv.get(),"vs_style":vsv.get(),
            "ov_en":ovenv.get(),"ov_spd":ovspdv.get(),"ov_op":ovopv.get(),"ov_sym":ovsymv.get(),
            "out_name":ov.get(),"out_dir":odv.get(),
            "hdr_ny":st.get("hdr_ny",0.0),"btn_ox":st.get("btn_ox",0),"btn_oy":st.get("btn_oy",0),
            "loop":lpv.get(),"superfast":sfv.get(),
            "bgv_en":bgvenv.get(),"bgv_fps":bgvfpsv.get(),"bgv_max":bgvmaxv.get(),
            "gif_en":genv.get(),"gif_sz":gszv.get(),
            "gif_ck":gckv.get(),"gif_ckc":gckcv.get(),
            "gif_cks":gcksv.get(),"gif_ckb":gckbv.get(),
            "gif_items":[{"path":g.get("path"),"nx":g.get("nx",0.5),"ny":g.get("ny",0.5),
                          "sz":g.get("sz",180),"ck":g.get("ck",False),
                          "ckc":g.get("ckc","#00FF00"),"cks":g.get("cks",30),
                          "ckb":g.get("ckb",10)} for g in st.get("gifs",[])],
            "logo_path":st.get("lp"),
            "custom_fonts":list(st.get("cfonts",[])),
        }

    def _apply_settings(d):
        def _sv(var,key):
            if key in d:
                try: var.set(d[key])
                except: pass
        _sv(gfnv,"global_font")
        _sv(henv,"hdr_en"); _sv(hv,"hdr_txt"); _sv(hsv,"hdr_size")
        if isinstance(d.get("hdr_styles"),dict):
            st["hdr_styles"]={str(k):v for k,v in d["hdr_styles"].items()}
        if "hdr_tb" in ui:
            try:
                ui["hdr_tb"].delete("1.0","end"); ui["hdr_tb"].insert("1.0",hv.get())
            except Exception: pass
        try: _hdr_fetch()
        except Exception: pass
        _sv(hcv,"hdr_col"); _sv(hspv,"hdr_area"); _sv(hfxv,"hdr_fx")
        _sv(hbor_wv,"hdr_bw"); _sv(hborcv,"hdr_bc")
        _sv(hdshenv,"hdr_sh_en"); _sv(hdshblv,"hdr_sh_blur"); _sv(hdshopv,"hdr_sh_op")
        _sv(hdshoxv,"hdr_sh_ox"); _sv(hdshoyv,"hdr_sh_oy"); _sv(hdshcv,"hdr_sh_col")
        _sv(benv,"btn_en"); _sv(bhv,"btn_h"); _sv(bwv,"btn_w")
        _sv(bwrapv,"btn_wrap"); _sv(bnbautov,"badge_auto")
        _sv(bscrollv,"btn_scroll")
        _sv(thmv,"theme"); _sv(thautov,"theme_auto")
        _sv(bnbcv,"badge_col"); _sv(bntcv,"badge_txt")
        _sv(thenv,"thumb_en"); _sv(thmodev,"thumb_mode"); _sv(thatv,"thumb_at")
        _sv(bpv,"btn_pad"); _sv(bgpv,"btn_rgap"); _sv(bgpv_col,"btn_cgap")
        _sv(bcv,"btn_corner"); _sv(bcolv,"btn_cols")
        _sv(btcv,"btn_tc"); _sv(bov,"btn_op")
        _sv(bborcv,"btn_borc"); _sv(bbor_wv,"btn_borw"); _sv(bbor_av,"btn_bora")
        _sv(bfsv,"btn_fs"); _sv(btn_bgalphav,"btn_bga")
        _sv(bbgv,"btn_bg"); _sv(bfnv,"btn_font")
        _sv(bgvenv,"bgv_en"); _sv(bgvfpsv,"bgv_fps"); _sv(bgvmaxv,"bgv_max")
        _sv(le,"logo_en"); _sv(lsv,"logo_sz"); _sv(lrv,"logo_rm"); _sv(lfv,"logo_fx")
        if "logo_nx" in d: st["lnx"]=d["logo_nx"]
        if "logo_ny" in d: st["lny"]=d["logo_ny"]
        _sv(vsenv,"vs_en"); _sv(vsv,"vs_style")
        _sv(ovenv,"ov_en"); _sv(ovspdv,"ov_spd"); _sv(ovopv,"ov_op"); _sv(ovsymv,"ov_sym")
        _sv(ov,"out_name"); _sv(odv,"out_dir")
        if "hdr_ny" in d: st["hdr_ny"]=d["hdr_ny"]
        if "btn_ox" in d: st["btn_ox"]=d["btn_ox"]
        if "btn_oy" in d: st["btn_oy"]=d["btn_oy"]
        _sv(genv,"gif_en"); _sv(gszv,"gif_sz")
        _sv(gckv,"gif_ck"); _sv(gckcv,"gif_ckc")
        _sv(gcksv,"gif_cks"); _sv(gckbv,"gif_ckb")
        # The logo image is part of the look, so presets restore it too.
        _lp=d.get("logo_path")
        if _lp and os.path.isfile(_lp):
            st["lp"]=_lp
            if "ll" in ui:
                try: ui["ll"].configure(text=os.path.basename(_lp),text_color=T1)
                except Exception: pass
        for _p in (d.get("custom_fonts") or []):
            _reg_font(_p)
        if "gif_items" in d:
            # Rebuild the GIF list from the preset, keeping any file that is
            # still on disk. Older presets stored no path, so fall back to
            # patching the current list positionally.
            _items=d["gif_items"] or []
            if any(_it.get("path") for _it in _items):
                _new=[]
                for _it in _items:
                    _p=_it.get("path")
                    if not _p or not os.path.isfile(_p): continue
                    _new.append({"path":_p,"nx":_it.get("nx",0.5),"ny":_it.get("ny",0.5),
                                 "sz":_it.get("sz",180),"ck":_it.get("ck",False),
                                 "ckc":_it.get("ckc","#00FF00"),"cks":_it.get("cks",30),
                                 "ckb":_it.get("ckb",10)})
                st["gifs"]=_new
            else:
                _gl=st.get("gifs",[])
                for _i,_it in enumerate(_items):
                    if _i<len(_gl):
                        _gl[_i]["nx"]=_it.get("nx",0.5)
                        _gl[_i]["ny"]=_it.get("ny",0.5)
                        _gl[_i]["sz"]=_it.get("sz",180)
            try:
                _refresh_gifs(); _gif_sel_changed()
            except Exception: pass
        _sv(lpv,"loop"); _sv(sfv,"superfast")
        for vr,bk in [(hcv,"hcb"),(hborcv,"hborc"),(bborcv,"bborc"),(btcv,"btc"),
                      (bnbcv,"bnbc"),(bntcv,"bntc")]:
            try:
                v=vr.get()
                if bk in ui:
                    ui[bk].configure(text=f"■ {v}",fg_color=v,
                        text_color="#000" if _il(v) else "#fff")
            except: pass
        _ar()

    def _save_preset():
        name=ui["pname_e"].get().strip()
        if not name:
            messagebox.showwarning("Name Required","Enter a preset name."); return
        prst=load_presets(); prst[name]=_collect_settings()
        save_presets(prst); _refresh_preset_list()
        ui["pname_e"].delete(0,"end")
        messagebox.showinfo("Saved",f"Preset saved: {name}")

    def _load_preset_by_name(name):
        if not name or name=="(no presets)": return
        prst=load_presets()
        if name in prst: _apply_settings(prst[name]); messagebox.showinfo("Loaded",f"Loaded: {name}")
        else: messagebox.showwarning("Not Found",f"Preset not found: {name}")

    def _delete_preset(name):
        if not name or name=="(no presets)": return
        if not messagebox.askyesno("Delete?",f"Delete preset: {name}?"): return
        prst=load_presets(); prst.pop(name,None)
        save_presets(prst); _refresh_preset_list()

    def _refresh_preset_list():
        if "preset_lb" not in ui: return
        prst=load_presets(); names=list(prst.keys())
        ui["preset_names"]=names
        ui["preset_lb"].configure(state="normal"); ui["preset_lb"].delete("1.0","end")
        if not names:
            ui["preset_lb"].insert("end","  No presets saved yet.\n")
        else:
            for nm in names:
                ui["preset_lb"].insert("end",f"  • {nm}\n")
        ui["preset_lb"].configure(state="disabled")
        if "preset_dd" in ui:
            dd_vals=names if names else ["(no presets)"]
            ui["preset_dd"].configure(values=dd_vals)
            if names: ui["preset_selvar"].set(names[0])

    def _has_bg():
        """True if EITHER a background image OR an enabled background video exists."""
        if bgvenv.get() and (st.get("bgv_paths") or []): return True
        return bool(st.get("bg") and os.path.isfile(st["bg"]))

    def _go():
        if st["run"]: return
        if not _has_bg(): messagebox.showwarning("Missing","Select a background image OR a background video."); return
        if not st["songs"]: messagebox.showwarning("Missing","Select songs folder."); return
        on=(ov.get().strip() or "song_video_output")
        if not on.lower().endswith(".mp4"): on+=".mp4"
        od=odv.get().strip() or str(OUTPUT_DIR); Path(od).mkdir(parents=True,exist_ok=True)
        op=os.path.join(od,on); save_cfg({"od":od})
        st["run"]=True; ui["btn"].configure(state="disabled",text="\u23F3 Processing...")
        for i in range(4): _ss(i,False)
        ui["log"].configure(state="normal"); ui["log"].delete("1.0","end"); ui["log"].configure(state="disabled")
        threading.Thread(target=_render,args=(list(st["songs"]),op),daemon=True).start()

    def _rst():
        frame.after(0,lambda:(st.__setitem__("run",False),ui["btn"].configure(state="normal",text="\U0001F680   Start Rendering")))

    # ═══ QUEUE SYSTEM ═══
    _queue = []          # list of dicts: {songs, out_path, name}
    _q_running = False

    def _snapshot_settings():
        """Capture current settings for queue entry."""
        on = (ov.get().strip() or "song_video_output")
        if not on.lower().endswith(".mp4"): on += ".mp4"
        od = odv.get().strip() or str(OUTPUT_DIR)
        Path(od).mkdir(parents=True, exist_ok=True)
        op = os.path.join(od, on)
        return {
            "songs": list(st["songs"]),
            "out_path": op,
            "name": on,
        }

    def _add_queue():
        if not _has_bg():
            messagebox.showwarning("Missing", "Select a background image OR a background video."); return
        if not st["songs"]:
            messagebox.showwarning("Missing", "Select songs folder."); return
        entry = _snapshot_settings()
        _queue.append(entry)
        _refresh_queue_ui()
        nm=entry["name"]; qs=len(_queue)
        messagebox.showinfo("Queued", f"Added to queue: {nm}\nQueue size: {qs}")

    def _refresh_queue_ui():
        if "qlb" not in ui: return
        ui["qlb"].configure(state="normal")
        ui["qlb"].delete("1.0", "end")
        if not _queue:
            ui["qlb"].insert("end", "  Queue is empty.\n")
        else:
            for i, e in enumerate(_queue):
                nm=e["name"]; ns=len(e["songs"])
                ui["qlb"].insert("end", f"  {i+1}. {nm}  ({ns} songs)\n")
        ui["qlb"].configure(state="disabled")
        lbl = f"Queue  ({len(_queue)} items)"
        if "qtab" in ui: ui["qtab"].configure(text=lbl)

    def _clear_queue():
        _queue.clear()
        _refresh_queue_ui()

    def _run_queue_seq():
        """Run queue one by one in background thread."""
        def _worker():
            nonlocal _q_running
            _q_running = True
            total = len(_queue)
            while _queue:
                entry = _queue.pop(0)
                frame.after(0, _refresh_queue_ui)
                frame.after(0, lambda n=entry["name"]: ui["pl"].configure(text=f"Queue: {n}"))
                _render(entry["songs"], entry["out_path"])
            _q_running = False
            frame.after(0, lambda: messagebox.showinfo("Queue Done 🎉", f"All {total} video(s) rendered!"))
            frame.after(0, _refresh_queue_ui)
        if _q_running:
            messagebox.showwarning("Busy", "Queue already running."); return
        if not _queue:
            messagebox.showwarning("Empty", "Queue is empty."); return
        threading.Thread(target=_worker, daemon=True).start()

    def _run_queue_par():
        """Run all queue items in parallel."""
        def _worker():
            nonlocal _q_running
            _q_running = True
            items = list(_queue)
            _queue.clear()
            frame.after(0, _refresh_queue_ui)
            threads = []
            for entry in items:
                t = threading.Thread(target=_render, args=(entry["songs"], entry["out_path"]), daemon=True)
                threads.append(t); t.start()
            for t in threads: t.join()
            _q_running = False
            frame.after(0, lambda: messagebox.showinfo("Queue Done 🎉", f"All {len(items)} video(s) rendered (parallel)!"))
        if _q_running:
            messagebox.showwarning("Busy", "Queue already running."); return
        if not _queue:
            messagebox.showwarning("Empty", "Queue is empty."); return
        threading.Thread(target=_worker, daemon=True).start()


    def _render(songs,out_path):
        work=tempfile.mkdtemp(prefix="svm_",dir=str(TEMP_DIR))
        t0=time.time(); enc=st["enc"]; sf_=sfv.get()
        font=find_font(gfnv.get()); hf=hspv.get()/100.0; lp=lpv.get()
        try:
            _bl(f"Encoder: {enc} | Loop: {lp}x"); _ss(0,True); _su("Analyzing...")
            durs=[get_dur(s) for s in songs]; durs=[d if d>0 else 1.0 for d in durs]
            t1=sum(durs); ta=t1*lp
            _bl(f"{len(songs)} songs \u2022 {fhms(t1)} \u2022 {lp}x = {fhms(ta)}")
            cum=[0.0]
            for d in durs: cum.append(cum[-1]+d)

            hh=int(VH*hf); bay=hh; bah=VH-hh
            gox_r=int(st.get("btn_ox",0)); goy_r=int(st.get("btn_oy",0))
            grid_full_raw=compute_grid(len(songs),int(VW*0.03),bay+goy_r,int(VW*0.94),bah,
                                   bpv.get(),bgpv.get(),bgpv_col.get(),bhv.get(),bwv.get(),_ci())
            grid_full=[(x+gox_r,y,w,h,i,c) for x,y,w,h,i,c in grid_full_raw]
            cr=bcv.get(); tc=_h2r(btcv.get())
            bo=bov.get()/100.0; bfs=bfsv.get()
            bborc=_h2r(bborcv.get()); bborw=bbor_wv.get(); bbora=bbor_av.get()
            hbsw=hbor_wv.get(); hbc=_h2r(hborcv.get())

            # ── base ──
            _su("Compositing base...")
            # base is now a TRANSPARENT overlay layer; background pasted at flatten time
            base=Image.new("RGBA",(VW,VH),(0,0,0,0))
            # When ffmpeg can draw text, it owns every song name so the
            # baked-in static name never sits under the scrolling one.
            # When the marquee is on, ffmpeg draws EVERY song name: the
            # resting wrapped title and the scrolling one are emitted as
            # two mutually exclusive layers per button, so nothing is
            # baked underneath them.  With the marquee off we bake the
            # wrapped titles straight into the base image instead.
            _ff_names=bool(has_drawtext() and font and benv.get()
                           and bscrollv.get())

            # header on base OR separate (if animated)
            hfx=hfxv.get(); htxt=hv.get().strip()
            header_png=None
            hdr_dy_full=int(st.get("hdr_ny",0.0)*VH)
            if htxt and henv.get():
                if hfx=="None":
                    draw_header_multi(base,htxt,hdr_dy_full,hh,max(16,hsv.get()),_h2r(hcv.get()),font,EF,border_stroke=hbsw,border_color=hbc,line_styles=_hdr_styles(),**_hdr_shadow_kw())
                else:
                    hdr_layer=Image.new("RGBA",(VW,VH),(0,0,0,0))
                    draw_header_multi(hdr_layer,htxt,hdr_dy_full,hh,max(16,hsv.get()),_h2r(hcv.get()),font,EF,border_stroke=hbsw,border_color=hbc,line_styles=_hdr_styles(),**_hdr_shadow_kw())
                    header_png=os.path.join(work,"header.png"); hdr_layer.save(header_png)

            # buttons on base
            if benv.get():
             for gx,gy,gw,gh,idx,col in grid_full:
                draw_btn(base,gx,gy,gw,gh,idx+1,ctn(songs[idx]),col,corner=cr,
                         txt_color=tc,font_name=gfnv.get(),
                         border_color=bborc,border_width=bborw,border_alpha=bbora,font_size=bfs,
                         btn_bg_alpha=btn_bgalphav.get(),show_name=not _ff_names,
                         wrap_text=bwrapv.get(),scroll_active=bscrollv.get(),badge_color=None if bnbautov.get() else _h2r(bnbcv.get()),badge_txt=_h2r(bntcv.get()))
            # logo (no-fx)
            fx=lfv.get(); have_l=bool(le.get() and st.get("lp") and os.path.isfile(st["lp"]))
            lsz=_logo_sz_full(); lx=ly=0
            if have_l:
                lx=int((VW-lsz)*st["lnx"]); ly=int((VH-lsz)*st["lny"])
                if fx=="None": base.alpha_composite(prep_logo(st["lp"],lsz,rm=lrv.get()),(lx,ly))

            # Bake falling symbols onto base (frame 0 = t=0 static for base)
            if ovenv.get():
                syms=OV_SYMS.get(ovsymv.get(),OV_SYMS["Christian"])
                op_ov=min(255,max(10,ovopv.get()))
                import hashlib as _hs
                count=12; fsz=max(18,int(VH*0.045))
                ov_lay=Image.new("RGBA",(VW,VH),(0,0,0,0))
                od=ImageDraw.Draw(ov_lay)
                for i in range(count):
                    h_=int(_hs.md5(str(i).encode()).hexdigest(),16)
                    sym=syms[i%len(syms)]; sz_f=0.7+0.6*(i%3)/3.0
                    sf_i=(ImageFont.truetype(SYMBOL_FONT,max(12,int(fsz*sz_f))) if SYMBOL_FONT else pil_font(max(12,int(fsz*sz_f))))
                    sx=int((h_%1000)/1000.0*VW)
                    od.text((sx,int(VH*0.1*i/count)),sym,fill=(255,255,255,op_ov),font=sf_i)
                base.alpha_composite(ov_lay,(0,0))
            # ── flatten overlay onto background (image or video boomerang) ──
            _vpaths=st.get("bgv_paths") or []
            _use_vid=bool(bgvenv.get() and _vpaths)
            bgseq_pat=None; bgv_fps_out=int(st.get("bgv_fps",12))

            _still=Image.new("RGBA",(VW,VH),(0,0,0,255))
            _bgsrc=None
            if st.get("bg") and os.path.isfile(st["bg"]):
                _bgsrc=st["bg"]
            elif _vpaths:
                _bgsrc=_vpaths[0]
            if _bgsrc:
                _still.paste(Image.open(_bgsrc).convert("RGBA").resize((VW,VH),Image.LANCZOS),(0,0))
            _still.alpha_composite(base,(0,0))
            bp=os.path.join(work,"base.png"); _still.convert("RGB").save(bp,quality=95)

            if _use_vid:
                _su("Building boomerang background...")
                _nf=len(_vpaths)
                _order=list(range(_nf))+list(range(_nf-2,0,-1)) if _nf>1 else [0]
                _bl("Background video: %d frames -> %d boomerang frames @ %dfps"%(_nf,len(_order),bgv_fps_out))
                for _oi,_fi in enumerate(_order):
                    _fr=Image.open(_vpaths[_fi]).convert("RGBA")
                    if _fr.size!=(VW,VH): _fr=_fr.resize((VW,VH),Image.LANCZOS)
                    _fr.alpha_composite(base,(0,0))
                    _fr.convert("RGB").save(os.path.join(work,"bgseq%05d.jpg"%_oi),quality=90)
                    _fr.close()
                    if _oi%15==0: _su("Boomerang frames %d/%d"%(_oi+1,len(_order)))
                bgseq_pat=os.path.join(work,"bgseq%05d.jpg")

            # ── active overlays ──
            _su("Active overlays..."); gp=10; ai=[]
            if benv.get():
             for gx,gy,gw,gh,idx,col in grid_full:
                ov_=Image.new("RGBA",(gw+2*gp,gh+2*gp),(0,0,0,0))
                draw_btn(ov_,gp,gp,gw,gh,idx+1,ctn(songs[idx]),col,active=True,
                         corner=cr,txt_color=tc,font_name=gfnv.get(),t_anim=0.5,
                         border_color=bborc,border_width=bborw,border_alpha=bbora,
                         scroll_offset=0,font_size=bfs,btn_bg_alpha=btn_bgalphav.get(),
                         show_name=not _ff_names,scroll_text=False,
                         wrap_text=bwrapv.get(),scroll_active=bscrollv.get(),badge_color=None if bnbautov.get() else _h2r(bnbcv.get()),badge_txt=_h2r(bntcv.get()))
                op_=os.path.join(work,f"a{idx}.png"); ov_.save(op_)
                ai.append((op_,gx-gp,gy-gp))
            _ss(0,done=True)

            # ── audio (parallel) ──
            _ss(1,True); _su("Audio merge...")
            ap=os.path.join(work,"audio.m4a"); ar_={}
            def _aw():
                try:
                    sl=songs*lp
                    if len(sl)==1: aa=[FF,"-y","-i",sl[0]]+A_Q+[ap]
                    else:
                        ins=[]; [ins.extend(["-i",s]) for s in sl]
                        afc="".join(f"[{i}:a]" for i in range(len(sl)))+f"concat=n={len(sl)}:v=0:a=1[a]"
                        aa=[FF,"-y"]+ins+["-filter_complex",afc,"-map","[a]"]+A_Q+[ap]
                    r=_rq(aa,capture_output=True)
                    ar_["e"]=None if r.returncode==0 else RuntimeError("Audio fail")
                except Exception as e: ar_["e"]=e
            at=threading.Thread(target=_aw,daemon=True); at.start()

            # ── filter graph ──
            _su("Filters..."); ei=[]; io=2
            for a,_,_ in ai: ei+=["-loop","1","-i",a]

            # header overlay input (if animated)
            hi_=None
            if header_png:
                ei+=["-loop","1","-i",header_png]; hi_=io+len(ai)

            # logo inputs
            li_=None; ri_=None; rsz=0
            if have_l and fx!="None":
                lpp=os.path.join(work,"logo.png"); prep_logo(st["lp"],lsz,rm=lrv.get()).save(lpp)
                ei+=["-loop","1","-i",lpp]; li_=io+len(ai)+(1 if header_png else 0)
                if fx=="Ring Spin":
                    rsz=int(lsz*1.7); rpp=os.path.join(work,"ring.png"); mk_ring(rsz,(255,90,120)).save(rpp)
                    ei+=["-loop","1","-i",rpp]; ri_=li_+1

            # GIF overlay inputs (loop forever with -ignore_loop 0)
            gifs_r=[]
            if genv.get() and st.get("gifs"):
                _nin=io+len(ai)+(1 if header_png else 0)
                if li_ is not None: _nin=li_+1
                if ri_ is not None: _nin=ri_+1
                for g in st["gifs"]:
                    p_=g.get("path")
                    if not p_ or not os.path.isfile(p_): continue
                    gsz_=max(8,int(g.get("sz",180)))
                    gh_=max(8,int(gif_size_at(p_,gsz_)))
                    gx_=max(0,min(VW-gsz_,int((VW-gsz_)*g.get("nx",0.5))))
                    gy_=max(0,min(VH-gh_,int((VH-gh_)*g.get("ny",0.5))))
                    ei+=["-ignore_loop","0","-i",p_]
                    gifs_r.append((_nin,gsz_,gx_,gy_,ff_colorkey(g))); _nin+=1

            segs=[]; cv="[0:v]"; nl=[0]
            def _n(): nl[0]+=1; return f"[v{nl[0]}]"

            # header animation
            if hi_ is not None:
                if hfx=="Wave":
                    pe=f"x=0:y='{int(8*math.sin(0))}+8*sin(t*1.8)'"
                elif hfx=="Fade In":
                    segs.append(f"[{hi_}:v]format=rgba,colorchannelmixer=aa='min(1,t/2.5)'[hfade]")
                    o=_n(); segs.append(f"{cv}[hfade]overlay=0:0{o}"); cv=o; hi_=None
                elif hfx=="Slide Up":
                    pe=f"x=0:y='max(0,{VH}-({VH})*min(1,t/2.0))'"
                elif hfx=="Glow Pulse":
                    pe=f"x=0:y='{int(4*math.sin(0))}+4*sin(t*2.5)'"
                else: pe="x=0:y=0"
                if hi_ is not None:
                    o=_n(); segs.append(f"{cv}[{hi_}:v]overlay={pe}{o}"); cv=o

            # fluid fill + active overlays per loop
            for loop_i in range(lp):
                for i,(gx,gy,gw,gh,idx,col) in enumerate(grid_full):
                    r_,g_,b_=col; s=cum[i]+loop_i*t1; e=cum[i+1]+loop_i*t1; dur_=e-s
                    o=_n()
                    segs.append(f"{cv}drawbox=x={gx}:y='{gy}+{gh}*(1-min(1,(t-{s:.3f})/{dur_:.3f}))'"
                                f":w={gw}:h='{gh}*min(1,(t-{s:.3f})/{dur_:.3f})'"
                                f":color=0x{r_:02x}{g_:02x}{b_:02x}@{bo*0.35:.2f}:t=fill"
                                f":enable='between(t,{s:.3f},{e:.3f})'{o}")
                    cv=o
                for i,(a,ox,oy) in enumerate(ai):
                    inp=i+io; s=cum[i]+loop_i*t1; e=cum[i+1]+loop_i*t1
                    o=_n()
                    segs.append(f"{cv}[{inp}:v]overlay={ox}:{oy}:enable='between(t,{s:.3f},{e:.3f})'{o}")
                    cv=o

            # ring/logo
            if ri_ is not None:
                rx=lx-(rsz-lsz)//2; ry=ly-(rsz-lsz)//2
                segs.append(f"[{ri_}:v]rotate=a='t*1.1':c=none:ow={rsz}:oh={rsz}[ring]")
                o=_n(); segs.append(f"{cv}[ring]overlay={rx}:{ry}{o}"); cv=o
            if li_ is not None:
                bi=f"[{li_}:v]"
                if fx in ("Spin","Spin + Orbit"):
                    segs.append(f"{bi}rotate=a='t*1.6':c=none:ow={lsz}:oh={lsz}[lsp]"); bi="[lsp]"
                if fx in ("Orbit","Spin + Orbit"):
                    R=max(16,int(lsz*0.55)); pe=f"x='max(0,min(W-w,{lx}+{R}*cos(2*PI*t/5)))':y='max(0,min(H-h,{ly}+{R}*sin(2*PI*t/5)))'"
                else: pe=f"x={lx}:y={ly}"
                o=_n(); segs.append(f"{cv}{bi}overlay={pe}{o}"); cv=o

            # GIF overlays
            for _gi,_gsz,_gx,_gy,_gck in gifs_r:
                _gtag="[gif%d]"%_gi
                segs.append("[%d:v]format=rgba,scale=%d:-1%s%s"%(_gi,_gsz,_gck,_gtag))
                o=_n(); segs.append(f"{cv}{_gtag}overlay={_gx}:{_gy}{o}"); cv=o

            # per-button visualizer REMOVED
            _cv_notext = cv; _n_notext = len(segs)
            # ── Scrolling song name on active button ──
            if grid_full and _ff_names:
                font_path_ff=font  # global font, already resolved above
                # Song name colour follows the Button Text Colour picker.
                # This used to be hardcoded to black, so picking yellow in
                # the preview still rendered a black name in the output.
                try: tc_ff="0x%02X%02X%02X"%(tc[0],tc[1],tc[2])
                except Exception: tc_ff="0xFFFFFF"
                if font_path_ff: font_path_ff=ff_fontpath(font_path_ff)
                badge_off_ff=int(grid_full[0][3]*0.68)+int(grid_full[0][3]*0.3)+int(grid_full[0][3]*0.14)
                tfs_ff=max(9,bfs if bfs>0 else int(grid_full[0][3]*0.30))
                if font_path_ff:
                    # One chain per button (not per button per loop): the text is
                    # drawn onto a CROP of just that button's text area and then
                    # overlaid back, so it is physically impossible for the name
                    # to scroll outside the button.
                    for i,(gx,gy,gw,gh,idx,col) in enumerate(grid_full):
                        tx_=gx+badge_off_ff
                        tw_=gw-badge_off_ff-int(gh*0.12)
                        if tw_<8 or gh<8: continue
                        s_=cum[i]; e_=cum[i+1]
                        ty_in=max(0,(gh-tfs_ff)//2)
                        raw_name=ctn(songs[idx])
                        song_label=ff_text(raw_name)
                        # time position inside one pass, so a single chain covers every loop
                        lt=f"mod(t,{t1:.3f})" if lp>1 else "t"
                        win=f"between({lt},{s_:.3f},{e_:.3f})"
                        dts=[]
                        # (a) RESTING: the wrapped title, shown whenever this
                        # song is not the one playing. Every button therefore
                        # keeps its text, exactly like the reference artwork.
                        rows=[]
                        if bwrapv.get():
                            try: rows=[r for r in wrap_px(raw_name,pil_font(tfs_ff,gfnv.get()),tw_,3) if r]
                            except Exception: rows=[]
                        if not rows: rows=[fit_px(raw_name,tfs_ff,tw_,gfnv.get())]
                        lh_ff=max(1,int(tfs_ff*1.18))
                        y0_ff=max(0,(gh-len(rows)*lh_ff)//2)
                        for ri,row in enumerate(rows):
                            dts.append(f"drawtext=text='{ff_text(row)}':expansion=none:"
                                       f"fontfile='{font_path_ff}':"
                                       f"fontsize={tfs_ff}:fontcolor={tc_ff}:"
                                       f"x=0:y={y0_ff+ri*lh_ff}:enable='not({win})'")
                        # (b) PLAYING: the single-line marquee, scrolling in
                        # from the right. Mutually exclusive with (a), so the
                        # two can never be drawn on top of each other.
                        scroll=f"{tw_}-mod(({lt}-{s_:.3f})*80,{tw_}+tw)"
                        dts.append(f"drawtext=text='{song_label}':expansion=none:"
                                   f"fontfile='{font_path_ff}':"
                                   f"fontsize={tfs_ff}:fontcolor={tc_ff}:"
                                   f"x='{scroll}':y={ty_in}:enable='{win}'")
                        m_=_n(); sb=_n()
                        segs.append(f"{cv}split=2{m_}{sb}")
                        tl=_n()
                        segs.append(f"{sb}crop={tw_}:{gh}:{tx_}:{gy},"+",".join(dts)+tl)
                        o=_n()
                        segs.append(f"{m_}{tl}overlay={tx_}:{gy}{o}")
                        cv=o

            fc=";".join(segs); ufc=bool(segs); vm=cv if ufc else "0:v"
            _su("Waiting audio..."); at.join()
            if ar_.get("e"): raise ar_["e"]
            _ss(1,done=True)

            _ss(2,True); _su("Rendering...")
            if bgseq_pat:
                args=[FF,"-y","-stream_loop","-1","-framerate",str(bgv_fps_out),"-i",bgseq_pat,"-i",ap]+ei
            else:
                args=[FF,"-y","-loop","1","-framerate","30","-i",bp,"-i",ap]+ei
            if ufc: args+=["-filter_complex",fc,"-map",vm]
            else: args+=["-map","0:v"]
            args+=["-map","1:a","-c:v",enc]+qf(enc,sf_)
            args+=["-pix_fmt","yuv420p","-c:a","copy","-t",f"{ta:.3f}",
                   "-fflags","+genpts","-movflags","+faststart","-shortest",out_path]
            try:
                _rff(args,ta,2,"Render")
            except Exception as _fe:
                # Most common cause is the drawtext song-name layer.
                # Retry once with that layer dropped so the user still gets a video.
                if not (ufc and len(segs) > _n_notext):
                    raise
                _bl("⚠ Text layer failed, retrying without scrolling song name...")
                _fc2 = ";".join(segs[:_n_notext])
                _a2 = list(args)
                if _fc2:
                    _a2[_a2.index("-filter_complex")+1] = _fc2
                    _a2[_a2.index("-map")+1] = _cv_notext
                else:
                    _i = _a2.index("-filter_complex")
                    del _a2[_i:_i+2]
                    _a2[_a2.index("-map")+1] = "0:v"
                _rff(_a2,ta,2,"Render")
            _ss(2,done=True)

            try:
                ts_=gen_ts(songs,durs,lp)
                tp=os.path.splitext(out_path)[0]+"_timestamps.txt"
                with open(tp,"w",encoding="utf-8") as f: f.write(ts_)
                _bl(f"\U0001F4CB Timestamps: {tp}")
            except: pass

            thumb_path=None
            try:
                if thenv.get():
                    _tj=os.path.splitext(out_path)[0]+"_thumbnail.jpg"
                    thumb_path=extract_thumb(out_path,_tj,
                                             thmodev.get().split()[0].lower(),thatv.get())
                    if thumb_path: _bl(f"\U0001F5BC Thumbnail: {thumb_path}")
                    else: _bl("\u26A0 Thumbnail could not be extracted")
            except Exception: pass

            _ss(3,done=True); _pr(1.0,"Done \u2713")
            el=time.time()-t0; mm,ss=divmod(int(el),60); took=f"{mm}m {ss}s" if mm else f"{ss}s"
            _su(f"Completed in {took}")
            _bl(f"\u2705 {out_path}"); _bl(f"\u23F1 {took} | {fhms(ta)} | {len(songs)} songs | {lp}x")
            try:
                import auth_manager
                auth_manager.record_video_export(tool_name="Song Video Maker", file_path=out_path)
            except Exception:
                pass
            _beep()

            def _show_done():
                try:
                    import master_queue
                    title_txt = os.path.splitext(os.path.basename(out_path))[0]
                    master_queue.register_rendered_video(
                        video_path=out_path, title=f"Song Video: {title_txt}", tool_name="Song Video Maker"
                    )
                except Exception:
                    messagebox.showinfo("Done \U0001F389",
                        f"\u2705 Video created!\n\n\u23F1 {took}\n\U0001F3AC {fhms(ta)}\n\u26A1 {enc}\n"
                        f"\U0001F3B5 {len(songs)} songs\n\U0001F501 {lp}x loop\n\n{out_path}"
                        +(f"\n\U0001F5BC {thumb_path}" if thumb_path else ""))
            frame.after(0, _show_done)
        except Exception as e:
            m=str(e); _bl(f"\u274C {m}"); frame.after(0,lambda m_=m:messagebox.showerror("Error",m_))
        finally:
            try: shutil.rmtree(work,ignore_errors=True)
            except: pass
            _rst()

    # ═══ UI CARDS ═══
    def _slr(p,lbl,var,mn,mx,unit,key,col=AP,extra_cb=None):
        r=ctk.CTkFrame(p,fg_color="transparent"); r.pack(fill="x",pady=2)
        ctk.CTkLabel(r,text=lbl,text_color=T2,font=ctk.CTkFont(size=11)).pack(side="left")
        ctk.CTkSlider(r,from_=mn,to=mx,variable=var,progress_color=col,button_color=col,width=110).pack(side="left",padx=6)
        ui[key]=ctk.CTkLabel(r,text=f"{var.get()}{unit}",text_color=T1,font=ctk.CTkFont(size=11)); ui[key].pack(side="left")
        def _w(*_a):
            ui[key].configure(text=f"{var.get()}{unit}")
            if extra_cb: extra_cb()
            _ar()
        var.trace_add("write",_w)

    def _pc(var,bk):
        res=colorchooser.askcolor(color=var.get(),title="Color")
        if res and res[1]: _sc(var,bk,res[1].upper())
    def _sc(var,bk,c):
        var.set(c)
        if bk in ui: ui[bk].configure(text=f"\u25A0 {c}",fg_color=c,text_color="#000" if _il(c) else "#fff")
        _ar()

    def C0(p):
        c=_card(p,"🔠  Global Font  (Header + Buttons)")
        fnr=ctk.CTkFrame(c,fg_color="transparent"); fnr.pack(fill="x",pady=4)
        ctk.CTkLabel(fnr,text="Font:",text_color=T2,font=ctk.CTkFont(size=12,weight="bold")).pack(side="left")
        ui["fontdd"]=ctk.CTkOptionMenu(fnr,values=FONT_NAMES,variable=gfnv,fg_color=BG_I,button_color=AR,
                          width=200,font=ctk.CTkFont(size=11),command=lambda *_:_ar())
        ui["fontdd"].pack(side="left",padx=8)
        fur=ctk.CTkFrame(c,fg_color="transparent"); fur.pack(fill="x",pady=4)
        ctk.CTkButton(fur,text="⬆  Upload font",width=130,fg_color=AB,hover_color="#2563eb",
                      font=ctk.CTkFont(size=11,weight="bold"),command=_ufont).pack(side="left")
        ui["fontup"]=ctk.CTkLabel(fur,text="",text_color=AG,font=ctk.CTkFont(size=10),
                                  wraplength=150,anchor="w")
        ui["fontup"].pack(side="left",padx=6)
        ctk.CTkLabel(c,text="ℹ .ttf / .otf — applies to Header + Buttons, preview updates instantly",
                     text_color=TM,font=ctk.CTkFont(size=9)).pack(anchor="w")

    def C1(p):
        c=_card(p,"\U0001F5BC  Background  \u2500 Image / Video")
        r=ctk.CTkFrame(c,fg_color="transparent"); r.pack(fill="x",pady=4)
        ui["bgl"]=ctk.CTkLabel(r,text="No image",text_color=T2,font=ctk.CTkFont(size=11),wraplength=200,anchor="w")
        ui["bgl"].pack(side="left",fill="x",expand=True)
        ctk.CTkButton(r,text="\U0001F4C2 Browse",width=110,fg_color=AB,hover_color="#2563eb",font=ctk.CTkFont(size=12,weight="bold"),command=_bbg).pack(side="right")

        ctk.CTkFrame(c,height=1,fg_color=BC).pack(fill="x",pady=6)
        ctk.CTkLabel(c,text="\U0001F3AC  Background Video  (optional \u2022 forward + reverse loop)",
                     text_color=AY,font=ctk.CTkFont(size=11,weight="bold")).pack(anchor="w")
        vsw=ctk.CTkFrame(c,fg_color="transparent"); vsw.pack(fill="x",pady=(2,2))
        ctk.CTkSwitch(vsw,text="Use Video Background",variable=bgvenv,progress_color=AR,
                      button_color="#fb7185",font=ctk.CTkFont(size=11),command=_ar).pack(side="left")
        vr=ctk.CTkFrame(c,fg_color="transparent"); vr.pack(fill="x",pady=2)
        ui["bgvl"]=ctk.CTkLabel(vr,text="No video (using image)",text_color=T2,
                                font=ctk.CTkFont(size=11),wraplength=175,anchor="w",justify="left")
        ui["bgvl"].pack(side="left",fill="x",expand=True)
        ctk.CTkButton(vr,text="\U0001F5D1",width=32,height=28,fg_color="#2a0a0a",hover_color="#3d0000",
                      text_color=T2,font=ctk.CTkFont(size=11),command=_clr_bgv).pack(side="right",padx=(4,0))
        ctk.CTkButton(vr,text="\U0001F3AC Video",width=88,height=28,fg_color="#e63946",hover_color="#c0392b",
                      font=ctk.CTkFont(size=11,weight="bold"),command=_bbgv).pack(side="right")
        _slr(c,"Video FPS:",bgvfpsv,4,30," fps","bgvfps",AC)
        _slr(c,"Max Frames:",bgvmaxv,10,200," fr","bgvmax",AO)
        ctk.CTkLabel(c,text="\u2139 Plays forward then reverse (seamless boomerang). Re-pick video after changing FPS/Frames.",
                     text_color=TM,font=ctk.CTkFont(size=9),wraplength=250,justify="left").pack(anchor="w",pady=(2,0))

    def C2(p):
        c=_card(p,"✍️  Header  (🔥 emoji + effects)")
        tr=ctk.CTkFrame(c,fg_color="transparent"); tr.pack(fill="x",pady=(0,4))
        ctk.CTkSwitch(tr,text="Enable Header",variable=henv,progress_color=AR,button_color="#fb7185",font=ctk.CTkFont(size=12),command=_ar).pack(side="left")
        ui["hdr_tb"]=ctk.CTkTextbox(c,height=74,fg_color=BG_I,border_color=BC,
                                    text_color=T1,font=ctk.CTkFont(size=12))
        ui["hdr_tb"].pack(fill="x",pady=4)
        try: ui["hdr_tb"].insert("1.0",hv.get())
        except Exception: pass
        def _hdr_tb_sync(*_a):
            try: hv.set(ui["hdr_tb"].get("1.0","end").rstrip("\n"))
            except Exception: pass
            _hdr_fetch()
        ui["hdr_tb"].bind("<KeyRelease>",_hdr_tb_sync)
        ctk.CTkLabel(c,text="\u21B5 Press Enter for a new line \u2014 each line can be styled below.",
                     text_color=TM,font=ctk.CTkFont(size=9)).pack(anchor="w")
        hv.trace_add("write",_ar)
        _slr(c,"Size:",hsv,24,120," px","hs",AR); _slr(c,"Area:",hspv,10,70,"%","hp",AO)
        cr2=ctk.CTkFrame(c,fg_color="transparent"); cr2.pack(fill="x",pady=2)
        ctk.CTkLabel(cr2,text="Color:",text_color=T2,font=ctk.CTkFont(size=11)).pack(side="left")
        ui["hcb"]=ctk.CTkButton(cr2,text="■ #FFF",width=80,height=24,fg_color="#FFF",text_color="#000",font=ctk.CTkFont(size=11),command=lambda:_pc(hcv,"hcb"))
        ui["hcb"].pack(side="left",padx=6)
        for cl in ["#FFFFFF","#FFD700","#FF6B8A","#00E5FF","#C084FC"]:
            ctk.CTkButton(cr2,text="",width=18,height=18,fg_color=cl,hover_color=cl,corner_radius=9,command=lambda c_=cl:_sc(hcv,"hcb",c_)).pack(side="left",padx=1)
        _slr(c,"Border Stroke:",hbor_wv,0,12," px","hborw",AC)
        hbr=ctk.CTkFrame(c,fg_color="transparent"); hbr.pack(fill="x",pady=2)
        ctk.CTkLabel(hbr,text="Border Color:",text_color=T2,font=ctk.CTkFont(size=11)).pack(side="left")
        ui["hborc"]=ctk.CTkButton(hbr,text="■ #000",width=76,height=22,fg_color="#000000",text_color="#fff",font=ctk.CTkFont(size=10),command=lambda:_pc(hborcv,"hborc"))
        ui["hborc"].pack(side="left",padx=6)
        for cl in ["#000000","#FFFFFF","#FF6B8A","#FFD700","#C084FC","#00E5FF"]:
            ctk.CTkButton(hbr,text="",width=18,height=18,fg_color=cl,hover_color=cl,corner_radius=9,command=lambda c_=cl:_sc(hborcv,"hborc",c_)).pack(side="left",padx=1)
        fr=ctk.CTkFrame(c,fg_color="transparent"); fr.pack(fill="x",pady=2)
        ctk.CTkLabel(fr,text="Effect:",text_color=T2,font=ctk.CTkFont(size=11)).pack(side="left")
        ctk.CTkOptionMenu(fr,values=HFX,variable=hfxv,fg_color=BG_I,button_color=AO,width=130,font=ctk.CTkFont(size=11),command=lambda *_:_ar()).pack(side="left",padx=6)
        ctk.CTkLabel(c,text="⚡ Effects animate live in preview!",text_color=AG,font=ctk.CTkFont(size=9)).pack(anchor="w")

        # ── header drop shadow ──
        ctk.CTkLabel(c,text="\u2500\u2500  Drop shadow  \u2500\u2500",text_color=T2,
                     font=ctk.CTkFont(size=11,weight="bold")).pack(anchor="w",pady=(8,2))
        ctk.CTkSwitch(c,text="Enable header shadow",variable=hdshenv,progress_color=AR,
                      button_color="#fb7185",font=ctk.CTkFont(size=12),command=_ar).pack(anchor="w")
        _slr(c,"Blur:",hdshblv,0,30," px","hdshbl",AC)
        _slr(c,"Opacity:",hdshopv,0,255,"","hdshop",AC)
        _slr(c,"Offset X:",hdshoxv,-30,30," px","hdshox",AC)
        _slr(c,"Offset Y:",hdshoyv,-30,30," px","hdshoy",AC)
        shr=ctk.CTkFrame(c,fg_color="transparent"); shr.pack(fill="x",pady=2)
        ctk.CTkLabel(shr,text="Shadow color:",text_color=T2,font=ctk.CTkFont(size=11)).pack(side="left")
        ui["hdshcb"]=ctk.CTkButton(shr,text="\u25A0 #000",width=76,height=22,fg_color="#000000",
                                   text_color="#fff",font=ctk.CTkFont(size=10),
                                   command=lambda:_pc(hdshcv,"hdshcb"))
        ui["hdshcb"].pack(side="left",padx=6)
        for cl in ["#000000","#4B0082","#7A0C0C","#1a1a2e"]:
            ctk.CTkButton(shr,text="",width=18,height=18,fg_color=cl,hover_color=cl,corner_radius=9,
                          command=lambda c_=cl:_sc(hdshcv,"hdshcb",c_)).pack(side="left",padx=1)

        # ── per-line styling ──
        ctk.CTkLabel(c,text="\u2500\u2500  Per-line style  \u2500\u2500",text_color=T2,
                     font=ctk.CTkFont(size=11,weight="bold")).pack(anchor="w",pady=(8,2))
        lr0=ctk.CTkFrame(c,fg_color="transparent"); lr0.pack(fill="x",pady=2)
        ctk.CTkButton(lr0,text="\u21BB Fetch lines",width=104,fg_color=AB,hover_color="#2563eb",
                      font=ctk.CTkFont(size=11,weight="bold"),command=_hdr_fetch).pack(side="left")
        ui["hdr_dd"]=ctk.CTkOptionMenu(lr0,values=["1: (empty)"],variable=hlselv,fg_color=BG_I,
                                       button_color=AR,width=170,font=ctk.CTkFont(size=10),
                                       command=lambda *_:_hdr_load_line())
        ui["hdr_dd"].pack(side="left",padx=6)
        lr1=ctk.CTkFrame(c,fg_color="transparent"); lr1.pack(fill="x",pady=2)
        ctk.CTkLabel(lr1,text="Line color:",text_color=T2,font=ctk.CTkFont(size=11)).pack(side="left")
        ui["hlcb"]=ctk.CTkButton(lr1,text="\u25A0 #FFFFFF",width=90,height=22,fg_color="#FFFFFF",
                                 text_color="#000",font=ctk.CTkFont(size=10),
                                 command=lambda:(_pc(hlcv,"hlcb"),_hdr_apply_line()))
        ui["hlcb"].pack(side="left",padx=6)
        for cl in ["#FFFFFF","#FFD700","#FF6B8A","#00E5FF","#C084FC","#4ADE80"]:
            ctk.CTkButton(lr1,text="",width=18,height=18,fg_color=cl,hover_color=cl,corner_radius=9,
                          command=lambda c_=cl:(_sc(hlcv,"hlcb",c_),_hdr_apply_line())
                          ).pack(side="left",padx=1)
        _slr(c,"Line size (0 = same as header)",hlszv,0,160," px","hlsz",AR,extra_cb=_hdr_apply_line)
        lr2=ctk.CTkFrame(c,fg_color="transparent"); lr2.pack(fill="x",pady=2)
        ctk.CTkLabel(lr2,text="Line font:",text_color=T2,font=ctk.CTkFont(size=11)).pack(side="left")
        ui["hlfd"]=ctk.CTkOptionMenu(lr2,values=FONT_NAMES,variable=hlfv,fg_color=BG_I,
                                     button_color=AR,width=150,font=ctk.CTkFont(size=10),
                                     command=lambda *_:_hdr_apply_line())
        ui["hlfd"].pack(side="left",padx=6)
        lr3=ctk.CTkFrame(c,fg_color="transparent"); lr3.pack(fill="x",pady=3)
        ctk.CTkButton(lr3,text="\u2714 Apply to line",width=110,fg_color=AP,
                      font=ctk.CTkFont(size=10),command=_hdr_apply_line).pack(side="left")
        ctk.CTkButton(lr3,text="Reset line",width=84,fg_color=AO,
                      font=ctk.CTkFont(size=10),command=_hdr_reset_line).pack(side="left",padx=4)
        ctk.CTkButton(lr3,text="Reset all",width=78,fg_color=BG_I,
                      font=ctk.CTkFont(size=10),command=_hdr_reset_all).pack(side="left")
        _hdr_fetch()

    def C3(p):
        c=_card(p,"\U0001F3B5  Songs Folder")
        r=ctk.CTkFrame(c,fg_color="transparent"); r.pack(fill="x",pady=4)
        ui["sc"]=ctk.CTkLabel(r,text="No folder",text_color=T2,font=ctk.CTkFont(size=11)); ui["sc"].pack(side="left",fill="x",expand=True)
        ctk.CTkButton(r,text="\U0001F4C2 Browse",width=100,fg_color=AB,hover_color="#2563eb",font=ctk.CTkFont(size=12,weight="bold"),command=_bsn).pack(side="right")
        ui["sb"]=ctk.CTkTextbox(c,height=100,fg_color=BG_I,text_color=T1,font=ctk.CTkFont(family="Consolas",size=10),border_color=BC)
        ui["sb"].pack(fill="x",pady=4); ui["sb"].configure(state="disabled")

    def C_THEME(p):
        c=_card(p,"\U0001F308  Colour Theme  \u2500 matched to your background")
        r0=ctk.CTkFrame(c,fg_color="transparent"); r0.pack(fill="x",pady=(0,4))
        ctk.CTkSwitch(r0,text="Auto-apply when a background is loaded",variable=thautov,
                      progress_color=AG,font=ctk.CTkFont(size=11)).pack(side="left")
        r1=ctk.CTkFrame(c,fg_color="transparent"); r1.pack(fill="x",pady=2)
        ctk.CTkLabel(r1,text="Theme:",text_color=T2,font=ctk.CTkFont(size=11)).pack(side="left")
        ui["theme_dd"]=ctk.CTkOptionMenu(r1,values=["Auto (from background)"]+THEME_NAMES,
                                         variable=thmv,width=178,font=ctk.CTkFont(size=11),
                                         fg_color=BG_I,button_color=AP,
                                         command=_theme_pick)
        ui["theme_dd"].pack(side="left",padx=6)
        r2=ctk.CTkFrame(c,fg_color="transparent"); r2.pack(fill="x",pady=4)
        ctk.CTkButton(r2,text="\U0001F3A8  Apply theme",width=128,height=28,fg_color=AP,
                      hover_color=AR,font=ctk.CTkFont(size=11,weight="bold"),
                      command=lambda:_theme_pick(thmv.get())).pack(side="left")
        ctk.CTkButton(r2,text="\u21BB  Re-detect",width=104,height=28,fg_color="#2a0a0a",
                      hover_color="#3d0000",text_color=T2,font=ctk.CTkFont(size=11),
                      command=lambda:_apply_theme(None)).pack(side="left",padx=6)
        ui["theme_lbl"]=ctk.CTkLabel(c,text="Load a background to get a suggestion",
                                     text_color=TM,font=ctk.CTkFont(size=10),
                                     wraplength=250,justify="left",anchor="w")
        ui["theme_lbl"].pack(anchor="w",pady=(2,0))
        ctk.CTkLabel(c,text="\u2139 A theme is only a starting point \u2500 button, border, badge, "
                            "number and header colours all stay editable below.",
                     text_color=TM,font=ctk.CTkFont(size=9),wraplength=250,
                     justify="left").pack(anchor="w")

    def C4(p):
        c=_card(p,"🎨  Button Style")
        tr4=ctk.CTkFrame(c,fg_color="transparent"); tr4.pack(fill="x",pady=(0,4))
        ctk.CTkSwitch(tr4,text="Enable Buttons",variable=benv,progress_color=AP,button_color="#c084fc",font=ctk.CTkFont(size=12),command=_ar).pack(side="left")
        _slr(c,"Height:",bhv,35,120," px","bh",AP)
        _slr(c,"Width:",bwv,150,800," px","bw",AP)
        _slr(c,"Outer Margin:",bpv,4,60," px","bp",AP)
        _slr(c,"Row Gap (↕ between rows):",bgpv,0,800," px","bgp",AY)
        _slr(c,"Col Gap (↔ between cols):",bgpv_col,0,800," px","bgpc",AY)
        _slr(c,"Button BG Opacity:",btn_bgalphav,0,255,"","bbga",AR)
        _slr(c,"Font Size:",bfsv,0,80," px (0=auto)","bfs",AY)
        _slr(c,"Corners:",bcv,5,50,"%","bc",AP)
        _slr(c,"Border Width:",bbor_wv,1,8," px","borw",AC)
        _slr(c,"Border Opacity:",bbor_av,20,255,"","bora",AC)
        gr=ctk.CTkFrame(c,fg_color="transparent"); gr.pack(fill="x",pady=2)
        ctk.CTkLabel(gr,text="Columns:",text_color=T2,font=ctk.CTkFont(size=11)).pack(side="left")
        ctk.CTkSegmentedButton(gr,values=["Auto","2","3","4","5"],variable=bcolv,selected_color=AP,
                               unselected_color=BG_I,font=ctk.CTkFont(size=11),command=lambda *_:_ar()).pack(side="left",padx=6)
        bcr2x=ctk.CTkFrame(c,fg_color="transparent"); bcr2x.pack(fill="x",pady=2)
        ctk.CTkLabel(bcr2x,text="Border color:",text_color=T2,font=ctk.CTkFont(size=11)).pack(side="left")
        ui["bborc"]=ctk.CTkButton(bcr2x,text="■ #FFFFFF",width=90,height=22,fg_color="#FFFFFF",text_color="#000",font=ctk.CTkFont(size=10),command=lambda:_pc(bborcv,"bborc"))
        ui["bborc"].pack(side="left",padx=6)
        for cl in ["#FFFFFF","#FFD700","#FF6B8A","#00E5FF","#C084FC","#4ADE80","#FF8C42"]:
            ctk.CTkButton(bcr2x,text="",width=18,height=18,fg_color=cl,hover_color=cl,corner_radius=9,command=lambda c_=cl:_sc(bborcv,"bborc",c_)).pack(side="left",padx=1)
        tcrx=ctk.CTkFrame(c,fg_color="transparent"); tcrx.pack(fill="x",pady=2)
        ctk.CTkLabel(tcrx,text="Text color:",text_color=T2,font=ctk.CTkFont(size=11)).pack(side="left")
        ui["btc"]=ctk.CTkButton(tcrx,text="■ #000000",width=90,height=22,fg_color="#000000",text_color="#fff",font=ctk.CTkFont(size=10),command=lambda:_pc(btcv,"btc"))
        ui["btc"].pack(side="left",padx=6)
        wrx=ctk.CTkFrame(c,fg_color="transparent"); wrx.pack(fill="x",pady=(8,2))
        ctk.CTkSwitch(wrx,text="Wrap song name inside the box",variable=bwrapv,
                      progress_color=AG,font=ctk.CTkFont(size=11),
                      command=_ar).pack(side="left")
        scx=ctk.CTkFrame(c,fg_color="transparent"); scx.pack(fill="x",pady=2)
        ctk.CTkSwitch(scx,text="Scroll the name of the song that is playing",
                      variable=bscrollv,progress_color=AY,
                      font=ctk.CTkFont(size=11),command=_ar).pack(side="left")
        nbx=ctk.CTkFrame(c,fg_color="transparent"); nbx.pack(fill="x",pady=2)
        ctk.CTkSwitch(nbx,text="Number badge matches background",variable=bnbautov,
                      progress_color=AP,font=ctk.CTkFont(size=11),
                      command=_ar).pack(side="left")
        nbr=ctk.CTkFrame(c,fg_color="transparent"); nbr.pack(fill="x",pady=2)
        ctk.CTkLabel(nbr,text="Badge color:",text_color=T2,font=ctk.CTkFont(size=11)).pack(side="left")
        ui["bnbc"]=ctk.CTkButton(nbr,text="\u25A0 #E63946",width=90,height=22,fg_color="#E63946",
                                 text_color="#fff",font=ctk.CTkFont(size=10),
                                 command=lambda:_pc(bnbcv,"bnbc"))
        ui["bnbc"].pack(side="left",padx=6)
        for cl in ["#E63946","#FFD700","#00E5FF","#4ADE80","#C084FC","#FFFFFF"]:
            ctk.CTkButton(nbr,text="",width=18,height=18,fg_color=cl,hover_color=cl,corner_radius=9,
                          command=lambda c_=cl:_sc(bnbcv,"bnbc",c_)).pack(side="left",padx=1)
        nbt=ctk.CTkFrame(c,fg_color="transparent"); nbt.pack(fill="x",pady=2)
        ctk.CTkLabel(nbt,text="Number color:",text_color=T2,font=ctk.CTkFont(size=11)).pack(side="left")
        ui["bntc"]=ctk.CTkButton(nbt,text="\u25A0 #FFFFFF",width=90,height=22,fg_color="#FFFFFF",
                                 text_color="#000",font=ctk.CTkFont(size=10),
                                 command=lambda:_pc(bntcv,"bntc"))
        ui["bntc"].pack(side="left",padx=6)
        for cl in ["#FFFFFF","#000000","#FFD700","#E63946"]:
            ctk.CTkButton(nbt,text="",width=18,height=18,fg_color=cl,hover_color=cl,corner_radius=9,
                          command=lambda c_=cl:_sc(bntcv,"bntc",c_)).pack(side="left",padx=1)
        for cl in ["#000000","#FFFFFF","#FFD700","#FF6B8A","#00E5FF"]:
            ctk.CTkButton(tcrx,text="",width=18,height=18,fg_color=cl,hover_color=cl,corner_radius=9,command=lambda c_=cl:_sc(btcv,"btc",c_)).pack(side="left",padx=1)
        ctk.CTkLabel(c,text="ℹ Font: see Global Font card above",text_color=TM,font=ctk.CTkFont(size=9)).pack(anchor="w")

    def C_OV(p):
        c=_card(p,"✝  Falling Symbols Overlay")
        tr=ctk.CTkFrame(c,fg_color="transparent"); tr.pack(fill="x",pady=(0,4))
        ctk.CTkSwitch(tr,text="Enable Overlay",variable=ovenv,progress_color="#e63946",
                      button_color="#ff6b6b",font=ctk.CTkFont(size=12),command=_ar).pack(side="left")
        sr=ctk.CTkFrame(c,fg_color="transparent"); sr.pack(fill="x",pady=2)
        ctk.CTkLabel(sr,text="Symbols:",text_color=T2,font=ctk.CTkFont(size=11)).pack(side="left")
        ctk.CTkOptionMenu(sr,values=list(OV_SYMS.keys()),variable=ovsymv,
                          fg_color=BG_I,button_color="#e63946",width=130,
                          font=ctk.CTkFont(size=11),command=lambda *_:_ar()).pack(side="left",padx=6)
        _slr(c,"Fall Speed:",ovspdv,1,20," x","ovspd","#e63946")
        _slr(c,"Opacity:",ovopv,10,220,"","ovop","#ff6b6b")
        ctk.CTkLabel(c,text="��� Symbols fall top→bottom in live preview + render",
                     text_color=TM,font=ctk.CTkFont(size=9)).pack(anchor="w")

    def C_FF(p):
        c=_card(p,"⚙  FFmpeg Binary  ─ browse if render fails")
        ui["ff_lbl"]=ctk.CTkLabel(c,text="Using: "+str(FF),text_color=T2,anchor="w",
                                  font=ctk.CTkFont(size=10),wraplength=250,justify="left")
        ui["ff_lbl"].pack(fill="x",pady=(0,4))

        def _test_ff():
            def _w():
                ok,msg=probe_ff()
                try:
                    frame.after(0,lambda: ui.get("ff_st") and ui["ff_st"].winfo_exists() and ui["ff_st"].configure(text=msg,text_color=AG if ok else AO))
                except Exception:
                    pass
            threading.Thread(target=_w,daemon=True).start()

        def _pick_ff():
            ftypes=[("ffmpeg executable","ffmpeg.exe")] if platform.system()=="Windows" else []
            ftypes.append(("All files","*.*"))
            p_=filedialog.askopenfilename(title="Select ffmpeg executable",filetypes=ftypes)
            if not p_: return
            if not set_ff(p_):
                messagebox.showwarning("Invalid","That file could not be used as ffmpeg."); return
            cfg=load_cfg(); cfg["ffmpeg_path"]=FF; save_cfg(cfg)
            ui["ff_lbl"].configure(text="Using: "+str(FF),text_color=AG)
            _bl("⚙ FFmpeg set to: "+str(FF))
            _test_ff()

        fr=ctk.CTkFrame(c,fg_color="transparent"); fr.pack(fill="x",pady=(0,4))
        ctk.CTkButton(fr,text="📂  Browse ffmpeg",height=32,
                      fg_color="#141414",hover_color="#2a0a0a",text_color="#e63946",
                      border_width=2,border_color="#e63946",
                      font=ctk.CTkFont(size=11,weight="bold"),
                      command=_pick_ff).pack(side="left",fill="x",expand=True,padx=(0,4))
        ctk.CTkButton(fr,text="✔ Test",width=62,height=32,
                      fg_color="#e63946",hover_color="#c0392b",text_color="#fff",
                      font=ctk.CTkFont(size=11,weight="bold"),
                      command=_test_ff).pack(side="left")
        ui["ff_st"]=ctk.CTkLabel(c,text="Testing...",text_color=TM,anchor="w",
                                 font=ctk.CTkFont(size=10),wraplength=250,justify="left")
        ui["ff_st"].pack(fill="x")
        _test_ff()

    def C_GIF(p):
        c=_card(p,"\U0001F39E  GIF Overlays  \u2500 upload / drag / loop")
        r0=ctk.CTkFrame(c,fg_color="transparent"); r0.pack(fill="x",pady=3)
        ctk.CTkSwitch(r0,text="Enable",variable=genv,command=lambda *_:_ar(),
                      progress_color=AR,font=ctk.CTkFont(size=11)).pack(side="left")
        ctk.CTkButton(r0,text="\u2795 Add GIF",width=110,fg_color=AB,hover_color="#2563eb",
                      font=ctk.CTkFont(size=11,weight="bold"),command=_add_gif).pack(side="right")
        ui["gif_lb"]=ctk.CTkLabel(c,text="No GIFs added",text_color=T2,justify="left",
                                  font=ctk.CTkFont(size=10),wraplength=250,anchor="w")
        ui["gif_lb"].pack(fill="x",pady=2)
        r1=ctk.CTkFrame(c,fg_color="transparent"); r1.pack(fill="x",pady=3)
        ctk.CTkLabel(r1,text="Selected:",text_color=T2,font=ctk.CTkFont(size=11)).pack(side="left")
        ui["gif_dd"]=ctk.CTkOptionMenu(r1,values=[""],variable=gselv,fg_color=BG_I,button_color=AR,
                                       width=150,font=ctk.CTkFont(size=10),
                                       command=lambda *_:_gif_sel_changed())
        ui["gif_dd"].pack(side="left",padx=6)
        _slr(c,"GIF size",gszv,40,1600,"px","gifsz")
        ck0=ctk.CTkFrame(c,fg_color="transparent"); ck0.pack(fill="x",pady=(6,2))
        ctk.CTkSwitch(ck0,text="Remove background (chroma key)",variable=gckv,
                      command=lambda *_:_ar(),progress_color=AR,
                      font=ctk.CTkFont(size=11)).pack(side="left")
        ck1=ctk.CTkFrame(c,fg_color="transparent"); ck1.pack(fill="x",pady=2)
        ctk.CTkLabel(ck1,text="Key colour:",text_color=T2,font=ctk.CTkFont(size=11)).pack(side="left")
        ui["gifck"]=ctk.CTkButton(ck1,text="\u25A0 #00FF00",width=90,height=22,fg_color="#00FF00",
                                  text_color="#000",font=ctk.CTkFont(size=10),
                                  command=lambda:_pc(gckcv,"gifck"))
        ui["gifck"].pack(side="left",padx=6)
        for cl in ("#00FF00","#0000FF","#FFFFFF","#000000","#FF00FF"):
            ctk.CTkButton(ck1,text="",width=18,height=18,fg_color=cl,hover_color=cl,
                          corner_radius=9,
                          command=lambda c_=cl:_sc(gckcv,"gifck",c_)).pack(side="left",padx=1)
        _slr(c,"Key strength",gcksv,1,100,"%","gifcks")
        _slr(c,"Edge softness",gckbv,0,100,"%","gifckb")
        r2=ctk.CTkFrame(c,fg_color="transparent"); r2.pack(fill="x",pady=3)
        ctk.CTkButton(r2,text="Apply size",width=90,fg_color=AP,
                      font=ctk.CTkFont(size=10),command=_gif_size_apply).pack(side="left")
        ctk.CTkButton(r2,text="\U0001F5D1 Remove",width=90,fg_color=AO,
                      font=ctk.CTkFont(size=10),command=_del_gif_sel).pack(side="left",padx=4)
        ctk.CTkButton(r2,text="Clear all",width=80,fg_color=BG_I,
                      font=ctk.CTkFont(size=10),command=_clear_gifs).pack(side="left")
        ctk.CTkLabel(c,text="\u2139 Drag a GIF in the preview to reposition. Loops forever.\n"
                            "Chroma key strips a solid background \u2014 pick the colour to remove.",
                     text_color=TM,justify="left",
                     font=ctk.CTkFont(size=9)).pack(anchor="w")

    def C_TH(p):
        c=_card(p,"\U0001F5BC  Thumbnail  \u2500 grab a frame as JPEG")
        r0=ctk.CTkFrame(c,fg_color="transparent"); r0.pack(fill="x",pady=3)
        ctk.CTkSwitch(r0,text="Save a thumbnail after every render",variable=thenv,
                      progress_color=AR,font=ctk.CTkFont(size=11)).pack(side="left")
        r1=ctk.CTkFrame(c,fg_color="transparent"); r1.pack(fill="x",pady=3)
        ctk.CTkLabel(r1,text="Frame:",text_color=T2,font=ctk.CTkFont(size=11)).pack(side="left")
        ctk.CTkOptionMenu(r1,values=["Last frame","First frame","At time"],variable=thmodev,
                          fg_color=BG_I,button_color=AR,width=130,
                          font=ctk.CTkFont(size=10)).pack(side="left",padx=6)
        _slr(c,"At time",thatv,0,600," s","that",AO)
        ctk.CTkButton(c,text="\U0001F4C2  Extract from a video\u2026",fg_color=AB,
                      hover_color="#2563eb",font=ctk.CTkFont(size=11,weight="bold"),
                      command=_th_browse).pack(fill="x",pady=4)
        ctk.CTkLabel(c,text="\u2139 Saved next to the video as <name>_thumbnail.jpg",
                     text_color=TM,font=ctk.CTkFont(size=9)).pack(anchor="w")

    def C_PRESET(p):
        c=_card(p,"💾  Presets  ─ Save & Load Settings")
        sr=ctk.CTkFrame(c,fg_color="transparent"); sr.pack(fill="x",pady=(0,4))
        ui["pname_e"]=ctk.CTkEntry(sr,placeholder_text="Preset name...",fg_color=BG_I,
                                    border_color=BC,text_color=T1,height=32,width=155)
        ui["pname_e"].pack(side="left",padx=(0,4))
        ctk.CTkButton(sr,text="💾  Save",width=75,height=32,
                      fg_color="#e63946",hover_color="#c0392b",text_color="#fff",
                      font=ctk.CTkFont(size=11,weight="bold"),command=_save_preset).pack(side="left")
        lr=ctk.CTkFrame(c,fg_color="transparent"); lr.pack(fill="x",pady=(0,4))
        ui["preset_selvar"]=tk.StringVar(value="(no presets)")
        ui["preset_dd"]=ctk.CTkOptionMenu(lr,values=["(no presets)"],variable=ui["preset_selvar"],
                           fg_color=BG_I,button_color="#e63946",width=155,
                           font=ctk.CTkFont(size=11))
        ui["preset_dd"].pack(side="left",padx=(0,4))
        ctk.CTkButton(lr,text="⏏ Load",width=65,height=32,
                      fg_color="#141414",hover_color="#2a0a0a",text_color="#e63946",
                      border_width=2,border_color="#e63946",
                      font=ctk.CTkFont(size=11,weight="bold"),
                      command=lambda:_load_preset_by_name(ui["preset_selvar"].get())).pack(side="left",padx=(0,4))
        ctk.CTkButton(lr,text="🗑",width=32,height=32,
                      fg_color="#2a0a0a",hover_color="#3d0000",text_color="#cccccc",
                      font=ctk.CTkFont(size=11),
                      command=lambda:_delete_preset(ui["preset_selvar"].get())).pack(side="left")
        ui["preset_lb"]=ctk.CTkTextbox(c,height=70,fg_color=BG_I,text_color=T2,
                                        font=ctk.CTkFont(family="Consolas",size=10),
                                        border_color=BC,corner_radius=6)
        ui["preset_lb"].pack(fill="x",pady=(0,4)); ui["preset_lb"].configure(state="disabled")
        ui["preset_names"]=[]; _refresh_preset_list()
        ctk.CTkLabel(c,text="ℹ Saves all settings (except songs folder)",
                     text_color=TM,font=ctk.CTkFont(size=9)).pack(anchor="w")

    def C5(p):
        c=_card(p,"\U0001F535  Logo + Effects")
        top=ctk.CTkFrame(c,fg_color="transparent"); top.pack(fill="x",pady=2)
        ctk.CTkSwitch(top,text="Enable",variable=le,progress_color=AR,button_color="#fb7185",font=ctk.CTkFont(size=12),command=_ar).pack(side="left")
        ctk.CTkButton(top,text="\U0001F4C2",width=60,fg_color=AB,hover_color="#2563eb",font=ctk.CTkFont(size=12),command=_ulo).pack(side="right")
        ui["ll"]=ctk.CTkLabel(c,text="No logo",text_color=T2,font=ctk.CTkFont(size=10)); ui["ll"].pack(anchor="w",pady=2)
        ctk.CTkSwitch(c,text="Remove BG",variable=lrv,progress_color=AO,button_color="#ff8c42",font=ctk.CTkFont(size=11),command=_ar).pack(anchor="w",pady=2)
        fr=ctk.CTkFrame(c,fg_color="transparent"); fr.pack(fill="x",pady=2)
        ctk.CTkLabel(fr,text="Effect:",text_color=T2,font=ctk.CTkFont(size=11)).pack(side="left")
        ctk.CTkOptionMenu(fr,values=LFX,variable=lfv,fg_color=BG_I,button_color=AO,width=140,font=ctk.CTkFont(size=11),command=lambda *_:_ar()).pack(side="left",padx=6)
        _slr(c,"Size:",lsv,40,400," px","lsz",AR)
        pr=ctk.CTkFrame(c,fg_color="transparent"); pr.pack(fill="x",pady=2)
        ctk.CTkLabel(pr,text="Drag \u2192",text_color=TM,font=ctk.CTkFont(size=10,slant="italic")).pack(side="left")
        ui["lpos"]=ctk.CTkLabel(pr,text="x:0.03 y:0.03",text_color=AG,font=ctk.CTkFont(size=10)); ui["lpos"].pack(side="left",padx=8)

    def C6(p):
        c=_card(p,"🎚  Visualizer")
        tr6=ctk.CTkFrame(c,fg_color="transparent"); tr6.pack(fill="x",pady=(0,4))
        ctk.CTkSwitch(tr6,text="Enable Visualizer",variable=vsenv,progress_color=AC,button_color="#22d3ee",font=ctk.CTkFont(size=12),command=_ar).pack(side="left")
        r=ctk.CTkFrame(c,fg_color="transparent"); r.pack(fill="x",pady=2)
        ctk.CTkLabel(r,text="Style:",text_color=T2,font=ctk.CTkFont(size=11)).pack(side="left")
        ctk.CTkOptionMenu(r,values=VSN,variable=vsv,fg_color=BG_I,button_color=AP,width=130,font=ctk.CTkFont(size=11)).pack(side="left",padx=6)
        ctk.CTkLabel(c,text="Bars inside active button",text_color=TM,font=ctk.CTkFont(size=9)).pack(anchor="w")

    def C7(p):
        c=_card(p,"\u26A1  Render + Loop")
        ctk.CTkSwitch(c,text="  Superfast",variable=sfv,progress_color=AX,button_color="#ff4444",font=ctk.CTkFont(size=12,weight="bold")).pack(anchor="w",pady=4)
        lr=ctk.CTkFrame(c,fg_color="transparent"); lr.pack(fill="x",pady=2)
        ctk.CTkLabel(lr,text="Loop:",text_color=T2,font=ctk.CTkFont(size=12)).pack(side="left")
        ctk.CTkSegmentedButton(lr,values=["1","2","3","4","5"],variable=lpv,selected_color=AO,
                               unselected_color=BG_I,font=ctk.CTkFont(size=12,weight="bold")).pack(side="left",padx=6)
        ctk.CTkLabel(lr,text="x repeat",text_color=TM,font=ctk.CTkFont(size=10)).pack(side="left",padx=4)

    def C8(p):
        c=_card(p,"\U0001F4BE  Output")
        r=ctk.CTkFrame(c,fg_color="transparent"); r.pack(fill="x",pady=4)
        ctk.CTkEntry(r,textvariable=ov,placeholder_text="my_video",fg_color=BG_I,border_color=BC,text_color=T1,height=32).pack(side="left",fill="x",expand=True,padx=(0,4))
        ctk.CTkLabel(r,text=".mp4",text_color=T2).pack(side="left")
        dr=ctk.CTkFrame(c,fg_color="transparent"); dr.pack(fill="x",pady=2)
        ctk.CTkEntry(dr,textvariable=odv,fg_color=BG_I,border_color=BC,text_color=T1,height=28).pack(side="left",fill="x",expand=True,padx=(0,4))
        ctk.CTkButton(dr,text="\U0001F4C2",width=40,fg_color=AB,hover_color="#2563eb",command=lambda:(lambda d:odv.set(d) if d else None)(filedialog.askdirectory(initialdir=odv.get()))).pack(side="left")

    def _right(par):
        # ═══ Action bar — primary controls, lifted out of the side panel ═══
        ab=ctk.CTkFrame(par,fg_color=BG_C,corner_radius=12,border_width=1,border_color=BC)
        ab.grid(row=0,column=0,sticky="ew",padx=8,pady=(8,6))
        abi=ctk.CTkFrame(ab,fg_color="transparent"); abi.pack(fill="x",padx=12,pady=10)
        ui["btn"]=ctk.CTkButton(abi,text="🚀  Render Now",
                                font=ctk.CTkFont(size=14,weight="bold"),
                                fg_color=AR,hover_color=AP,text_color="#ffffff",
                                height=44,width=168,corner_radius=9,command=_go)
        ui["btn"].pack(side="left")
        ctk.CTkButton(abi,text="➕  Add to Queue",font=ctk.CTkFont(size=12,weight="bold"),
                      fg_color=BG_I,hover_color="#2a0a0a",text_color=AR,
                      border_width=2,border_color=AR,height=44,width=146,
                      corner_radius=9,command=_add_queue).pack(side="left",padx=7)
        ctk.CTkButton(abi,text="📊  Analytics",font=ctk.CTkFont(size=12,weight="bold"),
                      fg_color=BG_I,hover_color="#2a0a0a",text_color=T2,
                      border_width=1,border_color=BC,height=44,width=124,
                      corner_radius=9,command=lambda:_show_stats()).pack(side="left")
        ui["gpu"]=ctk.CTkLabel(abi,text="⏳ GPU...",text_color=TM,
                               font=ctk.CTkFont(size=11,weight="bold"))
        ui["gpu"].pack(side="right",padx=(8,4))

        # ═══ Preview — now the hero of the screen ═══
        pc=ctk.CTkFrame(par,fg_color=BG_C,corner_radius=12,border_width=1,border_color=BC)
        pc.grid(row=1,column=0,sticky="nsew",padx=8,pady=(0,6))
        hdr=ctk.CTkFrame(pc,fg_color="transparent"); hdr.pack(fill="x",padx=16,pady=(10,2))
        ctk.CTkLabel(hdr,text="👁  Live Preview",
                     font=ctk.CTkFont(size=14,weight="bold"),text_color=T1).pack(side="left")
        ctk.CTkLabel(hdr,text="16:9 locked · drag elements to reposition",
                     font=ctk.CTkFont(size=10),text_color=TM).pack(side="left",padx=8)
        ui["plbl"]=ctk.CTkLabel(pc,text="No media",text_color=TM,fg_color=BG_I,
                                corner_radius=10,width=PW,height=PH)
        ui["plbl"].pack(padx=16,pady=(6,12))
        ui["plbl"].bind("<ButtonPress-1>",_drag_start)
        ui["plbl"].bind("<B1-Motion>",_drag)
        ui["plbl"].bind("<ButtonRelease-1>",lambda e:st.__setitem__("drag_el",None))

        # ═══ Slim status strip — full detail lives in the popup ═══
        sc_=ctk.CTkFrame(par,fg_color=BG_C,corner_radius=12,border_width=1,border_color=BC)
        sc_.grid(row=2,column=0,sticky="ew",padx=8,pady=(0,8))
        srow=ctk.CTkFrame(sc_,fg_color="transparent"); srow.pack(fill="x",padx=16,pady=(9,3))
        ui["pl"]=ctk.CTkLabel(srow,text="Ready",text_color=T2,
                              font=ctk.CTkFont(size=11,weight="bold"))
        ui["pl"].pack(side="left")
        ctk.CTkButton(srow,text="Details  ›",width=76,height=24,
                      fg_color="transparent",hover_color=BG_I,text_color=AR,
                      font=ctk.CTkFont(size=10,weight="bold"),
                      command=lambda:_show_stats()).pack(side="right")
        ui["pb"]=ctk.CTkProgressBar(sc_,height=8,corner_radius=4,
                                     progress_color=AR,fg_color=BG_I)
        ui["pb"].pack(fill="x",padx=16,pady=(0,11)); ui["pb"].set(0)

        # ═══ Analytics popup — built once, hidden until asked for ═══
        win=ctk.CTkToplevel(par)
        try: win.title("Render Analytics")
        except Exception: pass
        try: win.geometry("620x560")
        except Exception: pass
        try: win.configure(fg_color=BG_M)
        except Exception: pass
        try: win.withdraw()
        except Exception: pass
        try: win.protocol("WM_DELETE_WINDOW",win.withdraw)
        except Exception: pass
        ui["statwin"]=win

        def _show_stats():
            try:
                win.deiconify(); win.lift(); win.focus_force()
            except Exception: pass
        ui["show_stats"]=_show_stats

        wtop=ctk.CTkFrame(win,fg_color=BG_C,corner_radius=0); wtop.pack(fill="x")
        ctk.CTkLabel(wtop,text="📊  Render Analytics",
                     font=ctk.CTkFont(size=15,weight="bold"),
                     text_color=T1).pack(side="left",padx=16,pady=11)
        ctk.CTkButton(wtop,text="✕",width=30,height=26,fg_color="transparent",
                      hover_color=BG_I,text_color=TM,
                      font=ctk.CTkFont(size=13,weight="bold"),
                      command=lambda:win.withdraw()).pack(side="right",padx=12)

        stepc=ctk.CTkFrame(win,fg_color=BG_C,corner_radius=12,border_width=1,border_color=BC)
        stepc.pack(fill="x",padx=12,pady=(12,6))
        ctk.CTkLabel(stepc,text="Pipeline",font=ctk.CTkFont(size=11,weight="bold"),
                     text_color=AO).pack(anchor="w",padx=14,pady=(9,3))
        sr=ctk.CTkFrame(stepc,fg_color="transparent"); sr.pack(fill="x",padx=12,pady=(0,8))
        ui["steps"]=[]
        for i,nm in enumerate(["Assets","Audio","Render","Done"]):
            f=ctk.CTkFrame(sr,fg_color=BG_I,corner_radius=7,width=78,height=30)
            f.pack(side="left",padx=3,expand=True,fill="x"); f.pack_propagate(False)
            l=ctk.CTkLabel(f,text=f"{i+1}. {nm}",font=ctk.CTkFont(size=10),text_color=TM)
            l.place(relx=0.5,rely=0.5,anchor="center")
            ui["steps"].append((f,l))
        ui["sl"]=ctk.CTkLabel(stepc,text="",text_color=AC,
                              font=ctk.CTkFont(size=10,slant="italic"),anchor="w")
        ui["sl"].pack(fill="x",padx=14,pady=(0,9))

        lc=ctk.CTkFrame(win,fg_color=BG_C,corner_radius=12,border_width=1,border_color=BC)
        lc.pack(fill="both",expand=True,padx=12,pady=(0,12))
        ctk.CTkLabel(lc,text="📋  Log",font=ctk.CTkFont(size=11,weight="bold"),
                     text_color=AB).pack(anchor="w",padx=14,pady=(9,3))
        ui["log"]=ctk.CTkTextbox(lc,fg_color=BG_I,text_color=T1,
                                  font=ctk.CTkFont(family="Consolas",size=10),
                                  border_color=BC,corner_radius=8)
        ui["log"].pack(fill="both",expand=True,padx=12,pady=(0,12))
        ui["log"].configure(state="disabled")

    pane=tk.PanedWindow(frame,orient=tk.HORIZONTAL,sashwidth=6,sashrelief="flat",
                        background=BC,bd=0)
    pane.pack(fill="both",expand=True)

    # ═══ Side panel — grouped into tabs so there is far less scrolling ═══
    lw=tk.Frame(pane,bg=BG_M,bd=0,highlightthickness=0); pane.add(lw,minsize=300,width=396)
    ltabs=ctk.CTkTabview(lw,fg_color=BG_M,corner_radius=10,
                         segmented_button_fg_color=BG_C,
                         segmented_button_selected_color=AR,
                         segmented_button_selected_hover_color=AP,
                         segmented_button_unselected_color=BG_C,
                         segmented_button_unselected_hover_color=BG_I,
                         text_color=T1)
    ltabs.pack(fill="both",expand=True,padx=4,pady=4)
    _tc=ltabs.add("🎵 Content"); _ts=ltabs.add("🎨 Style")
    _to=ltabs.add("⚡ Output");      _tp=ltabs.add("💾 Presets")

    def _sf(par):
        f_=ctk.CTkScrollableFrame(par,fg_color=BG_M,scrollbar_button_color=BC,
                                  scrollbar_button_hover_color=AR)
        f_.pack(fill="both",expand=True); return f_

    s_content=_sf(_tc); s_style=_sf(_ts); s_out=_sf(_to); s_pre=_sf(_tp)

    C3(s_content); C1(s_content); C2(s_content); C0(s_content)
    C_THEME(s_style); C4(s_style);   C5(s_style);   C_GIF(s_style);   C6(s_style);   C_OV(s_style)
    C7(s_out);     C8(s_out);     C_TH(s_out);   C_FF(s_out)
    C_PRESET(s_pre)

    # Queue sits with the render settings
    qc=ctk.CTkFrame(s_out,fg_color=BG_C,corner_radius=10,border_width=1,border_color=BC)
    qc.pack(fill="x",padx=6,pady=(2,10))
    qh=ctk.CTkFrame(qc,fg_color="transparent"); qh.pack(fill="x",padx=12,pady=(9,4))
    ui["qtab"]=ctk.CTkLabel(qh,text="Queue  (0 items)",
                            font=ctk.CTkFont(size=12,weight="bold"),text_color=AR)
    ui["qtab"].pack(side="left")
    ctk.CTkButton(qh,text="🗑 Clear",width=62,height=22,fg_color=BG_I,
                  hover_color="#2a0a0a",text_color=T2,font=ctk.CTkFont(size=10),
                  command=_clear_queue).pack(side="right")
    ui["qlb"]=ctk.CTkTextbox(qc,height=80,fg_color=BG_I,text_color=T2,
                              font=ctk.CTkFont(family="Consolas",size=10),
                              border_color=BC,corner_radius=6)
    ui["qlb"].pack(fill="x",padx=10,pady=(0,6))
    ui["qlb"].configure(state="disabled")
    _refresh_queue_ui()
    qbr=ctk.CTkFrame(qc,fg_color="transparent"); qbr.pack(fill="x",padx=10,pady=(0,9))
    ctk.CTkButton(qbr,text="▶▶  One by One",font=ctk.CTkFont(size=11,weight="bold"),
                  fg_color=AR,hover_color=AP,text_color="#ffffff",height=34,corner_radius=8,
                  command=_run_queue_seq).pack(side="left",fill="x",expand=True,padx=(0,4))
    ctk.CTkButton(qbr,text="⚡  Parallel",font=ctk.CTkFont(size=11,weight="bold"),
                  fg_color=BG_I,hover_color="#2a0a0a",text_color=AR,
                  border_width=2,border_color=AR,height=34,corner_radius=8,
                  command=_run_queue_par).pack(side="left",fill="x",expand=True)

    rw=tk.Frame(pane,bg=BG_M,bd=0,highlightthickness=0); pane.add(rw,minsize=420)
    right=ctk.CTkFrame(rw,fg_color=BG_M); right.pack(fill="both",expand=True)
    right.rowconfigure(1,weight=1); right.columnconfigure(0,weight=1); _right(right)

    def _gpu_():
        enc=detect_gpu(); st["enc"]=enc
        nice={"libx264":"CPU (x264)","h264_nvenc":"NVIDIA NVENC","hevc_nvenc":"NVIDIA HEVC",
              "h264_amf":"AMD AMF","h264_qsv":"Intel QSV","h264_mf":"GPU Accelerated (MediaFoundation)",
              "h264_videotoolbox":"Apple VT"}.get(enc,enc)

        try:
            frame.after(0,lambda: ui.get("gpu") and ui["gpu"].winfo_exists() and ui["gpu"].configure(text=f"\u26A1 {nice}",text_color=AG if enc!="libx264" else T2))
        except Exception:
            pass
    threading.Thread(target=_gpu_,daemon=True).start()
    frame.after(200,_ref); frame.after(700,_tick)

# ════════════════════════════════════════════════════════════
# 🎵 YT Audio Splitter — integrated as a second tab
# ════════════════════════════════════════════════════════════
# ─── Theme ───────────────────────────────────────────────────────────────────

ACCENT   = "#4A9EFF"
BG_DARK  = "#0F1117"
BG_CARD  = "#181B24"
BG_INPUT = "#1E2130"
BG_ROW   = "#1A1D28"
BG_ROW_ALT = "#1E2232"
TEXT_DIM = "#8B95A8"
GREEN    = "#3DD68C"
RED      = "#FF5C5C"
ORANGE   = "#FFA040"

# ─── Helpers ─────────────────────────────────────────────────────────────────
def parse_timestamp(ts: str) -> float:
    """Convert HH:MM:SS or MM:SS string to seconds, robust to brackets/whitespace."""
    if not ts:
        return 0.0
    ts = re.sub(r'[^\d:.]', '', str(ts).strip())
    parts = ts.split(":")
    try:
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        elif len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        elif len(parts) == 1 and parts[0]:
            return float(parts[0])
    except Exception:
        pass
    return 0.0

def sanitize_filename(name: str) -> str:
    """Remove characters not safe for Windows filenames, replacing colons with hyphens."""
    name = str(name).replace(":", "-")
    name = re.sub(r'[\\/*?"<>|]', "", name)
    name = re.sub(r'\s+', " ", name).strip(" .-")
    return name or "segment"

def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

# ─── Segment Row Widget ───────────────────────────────────────────────────────
class SegmentRow(ctk.CTkFrame):
    def __init__(self, master, index: int, on_delete, **kwargs):
        super().__init__(master, fg_color=BG_ROW if index % 2 == 0 else BG_ROW_ALT,
                         corner_radius=6, **kwargs)
        self.index   = index
        self.on_delete = on_delete

        pad = dict(padx=4, pady=5)

        # Index label
        ctk.CTkLabel(self, text=f"{index+1}", width=28,
                     font=("Inter", 12, "bold"), text_color=ACCENT).pack(side="left", **pad)

        # Name
        self.name_var = tk.StringVar()
        ctk.CTkEntry(self, textvariable=self.name_var, placeholder_text="Song / Segment name",
                     width=220, font=("Inter", 12),
                     fg_color=BG_INPUT, border_color="#2A2E40", border_width=1,
                     corner_radius=5).pack(side="left", **pad)

        # Start
        self.start_var = tk.StringVar()
        ctk.CTkEntry(self, textvariable=self.start_var, placeholder_text="00:00",
                     width=80, font=("Inter", 12),
                     fg_color=BG_INPUT, border_color="#2A2E40", border_width=1,
                     corner_radius=5).pack(side="left", **pad)

        ctk.CTkLabel(self, text="→", text_color=TEXT_DIM,
                     font=("Inter", 13)).pack(side="left", padx=2)

        # End
        self.end_var = tk.StringVar()
        ctk.CTkEntry(self, textvariable=self.end_var, placeholder_text="00:00",
                     width=80, font=("Inter", 12),
                     fg_color=BG_INPUT, border_color="#2A2E40", border_width=1,
                     corner_radius=5).pack(side="left", **pad)

        # Delete btn
        ctk.CTkButton(self, text="✕", width=30, height=26,
                      fg_color="#2A1A1A", hover_color="#FF5C5C",
                      text_color=RED, font=("Inter", 13, "bold"),
                      corner_radius=5,
                      command=lambda: on_delete(self)).pack(side="right", **pad)

        # Status dot
        self.status_lbl = ctk.CTkLabel(self, text="●", width=24,
                                        text_color=TEXT_DIM, font=("Inter", 16))
        self.status_lbl.pack(side="right", padx=(0, 4))

    def set_status(self, state: str):
        """state: idle | processing | done | error"""
        colors = {"idle": TEXT_DIM, "processing": ORANGE, "done": GREEN, "error": RED}
        self.status_lbl.configure(text_color=colors.get(state, TEXT_DIM))

    def get_data(self):
        return {
            "name":  self.name_var.get().strip(),
            "start": self.start_var.get().strip(),
            "end":   self.end_var.get().strip(),
        }


# ─── Main App ─────────────────────────────────────────────────────────────────
class YTAudioSplitter(ctk.CTkFrame):
    """YT Audio Splitter, embedded as a tab inside Song Video Maker."""
    def __init__(self, master):
        super().__init__(master, fg_color=BG_DARK)

        self._rows: list[SegmentRow] = []
        self._audio_path: str | None = None
        self._busy = False

        self._build_ui()

    # ── UI construction ───────────────────────────────────────────────────────
    def _build_ui(self):
        # ── Header
        header = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0, height=58)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(header, text="🎵  YT Audio Splitter",
                     font=("Inter", 19, "bold"), text_color="white").pack(side="left", padx=20)
        ctk.CTkLabel(header, text="Download · Split · Export",
                     font=("Inter", 12), text_color=TEXT_DIM).pack(side="left", padx=4)

        # ── Main scroll container
        scroll = ctk.CTkScrollableFrame(self, fg_color=BG_DARK, scrollbar_button_color="#2A2E40")
        scroll.pack(fill="both", expand=True, padx=14, pady=10)

        # ── URL card
        url_card = ctk.CTkFrame(scroll, fg_color=BG_CARD, corner_radius=10)
        url_card.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(url_card, text="YouTube URL", font=("Inter", 13, "bold"),
                     text_color=ACCENT).pack(anchor="w", padx=14, pady=(12, 4))

        url_row = ctk.CTkFrame(url_card, fg_color="transparent")
        url_row.pack(fill="x", padx=14, pady=(0, 10))

        self.url_var = tk.StringVar()
        ctk.CTkEntry(url_row, textvariable=self.url_var,
                     placeholder_text="https://www.youtube.com/watch?v=...",
                     font=("Inter", 13), height=38,
                     fg_color=BG_INPUT, border_color="#2A2E40", border_width=1,
                     corner_radius=7).pack(side="left", fill="x", expand=True)

        self.dl_btn = ctk.CTkButton(url_row, text="⬇  Download Audio",
                                     font=("Inter", 13, "bold"), height=38,
                                     fg_color=ACCENT, hover_color="#3080DD",
                                     corner_radius=7, width=170,
                                     command=self._start_download)
        self.dl_btn.pack(side="left", padx=(8, 0))

        # ── OR: browse existing file
        browse_row = ctk.CTkFrame(url_card, fg_color="transparent")
        browse_row.pack(fill="x", padx=14, pady=(0, 12))
        ctk.CTkLabel(browse_row, text="— or use existing audio file —",
                     font=("Inter", 11), text_color=TEXT_DIM).pack(side="left")
        ctk.CTkButton(browse_row, text="Browse…", width=90, height=28,
                      font=("Inter", 11), fg_color="#232636",
                      hover_color="#2A2E40", corner_radius=6,
                      command=self._browse_file).pack(side="left", padx=8)
        self.file_lbl = ctk.CTkLabel(browse_row, text="No file selected",
                                      font=("Inter", 11), text_color=TEXT_DIM)
        self.file_lbl.pack(side="left")

        # ── YouTube Token / Cookies Bypass Section (Dedicated Card like Suno Downloader)
        token_card = ctk.CTkFrame(scroll, fg_color=BG_CARD, corner_radius=10)
        token_card.pack(fill="x", pady=(0, 10))

        token_hdr = ctk.CTkFrame(token_card, fg_color="transparent")
        token_hdr.pack(fill="x", padx=14, pady=(12, 4))

        ctk.CTkLabel(token_hdr, text="🔑  YouTube Token / Cookie / Netscape (Bypass 403 & Bot Check)",
                     font=("Inter", 13, "bold"), text_color="#38bdf8").pack(side="left")

        saved_tok = self._load_saved_token()
        self.token_status_lbl = ctk.CTkLabel(
            token_hdr,
            text="● Active" if saved_tok else "● Not Configured",
            font=("Inter", 11, "bold"),
            text_color=GREEN if saved_tok else TEXT_DIM
        )
        self.token_status_lbl.pack(side="right")

        ctk.CTkLabel(
            token_card,
            text="Extract full-length audio without YouTube connection drops, bot checks, or truncation (like Suno Downloader).",
            font=("Inter", 11),
            text_color=TEXT_DIM
        ).pack(anchor="w", padx=14, pady=(0, 8))

        token_input_row = ctk.CTkFrame(token_card, fg_color="transparent")
        token_input_row.pack(fill="x", padx=14, pady=(0, 8))

        self.token_var = tk.StringVar(value=saved_tok)
        self.token_entry = ctk.CTkEntry(
            token_input_row,
            textvariable=self.token_var,
            placeholder_text="Paste YouTube Cookie / Token (LOGIN_INFO, __Secure-3PSID, Netscape cookie text, or browser name)...",
            font=("Inter", 11),
            height=36,
            fg_color=BG_INPUT,
            border_color="#2A2E40",
            border_width=1,
            corner_radius=7,
        )
        self.token_entry.pack(side="left", fill="x", expand=True)

        token_btn_row = ctk.CTkFrame(token_card, fg_color="transparent")
        token_btn_row.pack(fill="x", padx=14, pady=(0, 12))

        ctk.CTkButton(token_btn_row, text="📤 Upload Cookies (.txt / JSON)", width=195, height=30,
                      font=("Inter", 11, "bold"), fg_color="#0284C7", hover_color="#0369A1",
                      text_color="#FFFFFF", corner_radius=6, command=self._upload_cookies_file).pack(side="left", padx=(0, 8))

        ctk.CTkButton(token_btn_row, text="💾 Save", width=80, height=30,
                      font=("Inter", 11, "bold"), fg_color="#1E293B", hover_color="#334155",
                      corner_radius=6, command=self._save_token).pack(side="left", padx=(0, 8))

        ctk.CTkButton(token_btn_row, text="⚡ Verify", width=80, height=30,
                      font=("Inter", 11, "bold"), fg_color="#0F766E", hover_color="#115E59",
                      corner_radius=6, command=self._verify_token).pack(side="left", padx=(0, 8))

        ctk.CTkButton(token_btn_row, text="🌐 Auto Chrome/Edge", width=155, height=30,
                      font=("Inter", 11), fg_color="#3B0764", hover_color="#581C87",
                      text_color="#F3E8FF", corner_radius=6, command=self._use_browser_cookies).pack(side="left", padx=(0, 8))

        ctk.CTkButton(token_btn_row, text="✕ Clear", width=65, height=30,
                      font=("Inter", 11), fg_color="#2A1A1A", hover_color="#FF5C5C",
                      corner_radius=6, command=self._clear_token).pack(side="right")

        # ── Output folder
        out_card = ctk.CTkFrame(scroll, fg_color=BG_CARD, corner_radius=10)
        out_card.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(out_card, text="Output Folder", font=("Inter", 13, "bold"),
                     text_color=ACCENT).pack(anchor="w", padx=14, pady=(12, 4))
        out_row = ctk.CTkFrame(out_card, fg_color="transparent")
        out_row.pack(fill="x", padx=14, pady=(0, 12))
        self.out_var = tk.StringVar(value=str(Path.home() / "Desktop" / "AudioSegments"))
        ctk.CTkEntry(out_row, textvariable=self.out_var, font=("Inter", 12), height=34,
                     fg_color=BG_INPUT, border_color="#2A2E40", border_width=1,
                     corner_radius=6).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(out_row, text="📁", width=40, height=34,
                      fg_color="#232636", hover_color="#2A2E40",
                      corner_radius=6, command=self._browse_out).pack(side="left", padx=(6, 0))

        # ── Segments card
        seg_card = ctk.CTkFrame(scroll, fg_color=BG_CARD, corner_radius=10)
        seg_card.pack(fill="x", pady=(0, 10))

        seg_header = ctk.CTkFrame(seg_card, fg_color="transparent")
        seg_header.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(seg_header, text="Segments", font=("Inter", 13, "bold"),
                     text_color=ACCENT).pack(side="left")

        btn_bar = ctk.CTkFrame(seg_header, fg_color="transparent")
        btn_bar.pack(side="right")

        ctk.CTkButton(btn_bar, text="＋ Add Row", width=100, height=30,
                      font=("Inter", 12), fg_color="#1A2A1A",
                      hover_color="#223322", text_color=GREEN,
                      corner_radius=6, command=self._add_row).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_bar, text="📋 Paste & Auto-Parse", width=165, height=30,
                      font=("Inter", 12, "bold"), fg_color=GREEN,
                      hover_color="#2AAA6A", text_color="#001A0D",
                      corner_radius=6, command=self._paste_table).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_bar, text="📝 Bulk Paste", width=110, height=30,
                      font=("Inter", 12), fg_color="#1E293B",
                      hover_color="#334155", text_color="#38BDF8",
                      corner_radius=6, command=self._open_bulk_paste_modal).pack(side="left", padx=(0, 6))
        self.format_btn = ctk.CTkButton(
            btn_bar, text="📋 Format Prompt", width=135, height=30,
            font=("Inter", 12, "bold"), fg_color="#3B1D54",
            hover_color="#532778", text_color="#C084FC",
            corner_radius=6, command=self._copy_format_prompt
        )
        self.format_btn.pack(side="left")

        # Column headers
        col_hdr = ctk.CTkFrame(seg_card, fg_color="#13151E", corner_radius=0)
        col_hdr.pack(fill="x", padx=14, pady=(0, 4))
        for txt, w in [("#", 28), ("Song / Segment Name", 220),
                       ("Start", 80), ("End", 80), ("", 60)]:
            ctk.CTkLabel(col_hdr, text=txt, width=w, font=("Inter", 11, "bold"),
                         text_color=TEXT_DIM).pack(side="left", padx=4, pady=4)

        # Row container
        self.rows_frame = ctk.CTkFrame(seg_card, fg_color="transparent")
        self.rows_frame.pack(fill="x", padx=14, pady=(0, 14))

        # Add 3 blank rows to start
        for _ in range(3):
            self._add_row()

        # ── Log
        log_card = ctk.CTkFrame(scroll, fg_color=BG_CARD, corner_radius=10)
        log_card.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(log_card, text="Log", font=("Inter", 13, "bold"),
                     text_color=ACCENT).pack(anchor="w", padx=14, pady=(10, 4))
        self.log_box = ctk.CTkTextbox(log_card, height=130, font=("Consolas", 11),
                                       fg_color=BG_INPUT, border_width=0,
                                       corner_radius=6, text_color="#C8CDD8")
        self.log_box.pack(fill="x", padx=14, pady=(0, 12))

        # ── Bottom bar (sticky)
        bot = ctk.CTkFrame(self, fg_color=BG_CARD, corner_radius=0, height=64)
        bot.pack(fill="x", side="bottom")
        bot.pack_propagate(False)

        self.progress = ctk.CTkProgressBar(bot, mode="indeterminate",
                                            progress_color=ACCENT, fg_color="#1E2130",
                                            height=6, corner_radius=3)
        self.progress.pack(fill="x", padx=20, pady=(10, 0))

        self.status_lbl = ctk.CTkLabel(bot, text="Ready",
                                        font=("Inter", 12), text_color=TEXT_DIM)
        self.status_lbl.pack(side="left", padx=20)

        self.split_btn = ctk.CTkButton(bot, text="✂  Split & Export",
                                        font=("Inter", 14, "bold"), height=38, width=180,
                                        fg_color=GREEN, hover_color="#2AAA6A",
                                        text_color="#001A0D", corner_radius=8,
                                        command=self._start_split)
        self.split_btn.pack(side="right", padx=20, pady=12)

    # ── Row management ─────────────────────────────────────────────────────────
    def _add_row(self):
        row = SegmentRow(self.rows_frame, len(self._rows), self._delete_row)
        row.pack(fill="x", pady=2)
        self._rows.append(row)

    def _delete_row(self, row: SegmentRow):
        if len(self._rows) <= 1:
            return
        self._rows.remove(row)
        row.destroy()
        # Renumber
        for i, r in enumerate(self._rows):
            r.index = i
            r.configure(fg_color=BG_ROW if i % 2 == 0 else BG_ROW_ALT)

    def _probe_audio_duration(self, filepath: str | None) -> float:
        """Get source audio duration in seconds using ffprobe or ffmpeg."""
        if not filepath or not Path(filepath).exists():
            return 0.0
        try:
            cmd = [
                FP, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                filepath
            ]
            res = _rq(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0 and res.stdout.strip():
                return float(res.stdout.strip())
        except Exception:
            pass
        # Fallback to ffmpeg
        try:
            out = subprocess.check_output([FF, "-hide_banner", "-i", str(filepath)], stderr=subprocess.STDOUT, text=True)
            m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", out)
            if m:
                return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        except Exception:
            pass
        return 0.0

    def _clean_segment_name(self, raw_name: str) -> str:
        """Clean song name from quotes, numbering, stray timestamps, and delimiters."""
        t = str(raw_name).strip()
        ts_pat = r'(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\.\d+)?'
        t = re.sub(rf'[\(\[]?\s*{ts_pat}\s*[\)\]]?', '', t)
        t = re.sub(r'^(?:(?:track|song|chapter|ch|part)\s*\d+[:\-.]?|\d+[\.\)\-:]+|#\d+[:\-.]?)\s*', '', t, flags=re.IGNORECASE)
        t = re.sub(r'^[\s:\-–—\"\'*|]+|[\s:\-–—\"\'*|]+$', '', t)
        if (t.startswith('(') and t.endswith(')')) or (t.startswith('[') and t.endswith(']')):
            t = t[1:-1].strip()
        while t.endswith(')') and t.count(')') > t.count('('):
            t = t[:-1].strip()
        while t.endswith(']') and t.count(']') > t.count('['):
            t = t[:-1].strip()
        while t.startswith('(') and t.count('(') > t.count(')'):
            t = t[1:].strip()
        while t.startswith('[') and t.count('[') > t.count(']'):
            t = t[1:].strip()
        t = re.sub(r'^[\s:\-–—\"\'*|]+|[\s:\-–—\"\'*|]+$', '', t)
        t = re.sub(r'\s+', ' ', t)
        return t.strip()

    def _parse_clipboard_text(self, raw: str) -> list[tuple[str, str, str]]:
        """Universal parser supporting ANY tracklist format (ranges, single timestamps, chapters, tables)."""
        lines = [l.strip() for l in (raw or "").strip().splitlines() if l.strip()]
        if not lines:
            return []

        ts_pat = r'(?:\d{1,2}:)?\d{1,2}:\d{2}(?:\.\d+)?'
        ts_re = re.compile(ts_pat)
        range_re = re.compile(rf'[\(\[]?\s*({ts_pat})\s*(?:[-–—~]|to|->|\.\.)\s*({ts_pat})\s*[\)\]]?', re.IGNORECASE)
        single_wrap_re = re.compile(rf'[\(\[]\s*({ts_pat})\s*[\)\]]')
        single_plain_re = re.compile(rf'\b({ts_pat})\b')

        # 1. Check for markdown / delimited table first
        table_rows = []
        for line in lines:
            if line.startswith("|") and "---" not in line:
                cells = [c.strip().strip("*").strip() for c in line.strip("|").split("|")]
                times = [c for c in cells if ts_re.search(c)]
                names = [c for c in cells if not ts_re.search(c) and c.replace("#", "").strip() and not c.replace("#", "").strip().isdigit()]
                if len(times) >= 2 and names:
                    table_rows.append((self._clean_segment_name(names[0]), times[0].strip(), times[1].strip()))
                elif len(times) == 1 and names:
                    table_rows.append((self._clean_segment_name(names[0]), times[0].strip(), ""))
        if table_rows:
            # Fill missing end times from next start
            final_table = []
            for i, (name, s, e) in enumerate(table_rows):
                if not e and i + 1 < len(table_rows):
                    e = table_rows[i+1][1]
                final_table.append((name, s, e))
            return final_table

        # 2. Universal line-by-line parsing
        segments = []
        for line in lines:
            if line.startswith("#") or line.startswith("//"):
                continue

            # Case A: Range anywhere in line e.g. Title: (0:00:37 - 0:05:32)
            m_range = range_re.search(line)
            if m_range:
                t1, t2 = m_range.group(1), m_range.group(2)
                raw_title = line[:m_range.start()] + " " + line[m_range.end():]
                name = self._clean_segment_name(raw_title) or f"Segment_{len(segments)+1}"
                segments.append((name, t1.strip(), t2.strip()))
                continue

            # Case B: Wrapped single timestamp e.g. Title: (0:00:37) or Title [0:00:37]
            m_wrap = single_wrap_re.search(line)
            if m_wrap:
                t1 = m_wrap.group(1)
                raw_title = line[:m_wrap.start()] + " " + line[m_wrap.end():]
                name = self._clean_segment_name(raw_title) or f"Segment_{len(segments)+1}"
                segments.append((name, t1.strip(), ""))
                continue

            # Case C: Plain single timestamp e.g. 0:00:37 - Title or 0:00:37 Title
            m_plain = single_plain_re.search(line)
            if m_plain:
                t1 = m_plain.group(1)
                raw_title = line[:m_plain.start()] + " " + line[m_plain.end():]
                name = self._clean_segment_name(raw_title) or f"Segment_{len(segments)+1}"
                segments.append((name, t1.strip(), ""))
                continue

        # Fill end times from next song's start if end is missing
        if segments:
            final_segments = []
            for i, (name, s, e) in enumerate(segments):
                if not e and i + 1 < len(segments):
                    e = segments[i + 1][1]
                final_segments.append((name, s, e))
            return final_segments

        return segments

    def _load_segments_into_table(self, segments: list[tuple[str, str, str]]):
        """Populate parsed segments into UI rows."""
        if not segments:
            return
        # Clear existing rows
        for r in self._rows[:]:
            r.destroy()
        self._rows.clear()

        for name, start, end in segments:
            self._add_row()
            row = self._rows[-1]
            row.name_var.set(name)
            row.start_var.set(start)
            row.end_var.set(end)

        self._log(f"✔  Loaded {len(segments)} segment(s) into table", GREEN)

    def _paste_table(self):
        """Parse clipboard table or timestamp range lines and populate rows."""
        try:
            raw = self.clipboard_get()
        except Exception:
            self._log("⚠  Clipboard empty or unavailable", RED)
            return

        segments = self._parse_clipboard_text(raw)
        if not segments:
            self._log(
                "⚠  No valid timestamps found in clipboard. Paste lines like:\n"
                "Opening Prayer and Worship: (0:00:00 - 0:02:29)\n"
                "Or click '📝 Bulk Paste' to paste/edit manually.",
                RED
            )
            return

        self._load_segments_into_table(segments)

    def _copy_format_prompt(self):
        prompt_text = (
            "Please provide the timestamp of these songs in this format:\n\n"
            "Song Title 1 (0:00:00 - 0:03:30)\n"
            "Song Title 2 (0:03:30 - 0:06:45)\n"
            "Song Title 3 (0:06:45 - 0:10:20)\n"
        )
        try:
            self.clipboard_clear()
            self.clipboard_append(prompt_text)
            self._log("📋 Prompt copied to clipboard! Paste it into ChatGPT / AI to format timestamps.", GREEN)
            orig_text = self.format_btn.cget("text")
            orig_fg = self.format_btn.cget("fg_color")
            self.format_btn.configure(text="✔ Copied!", fg_color="#10B981", text_color="#FFFFFF")
            self.after(2000, lambda: self.format_btn.configure(text=orig_text, fg_color=orig_fg, text_color="#C084FC"))
        except Exception as e:
            self._log(f"⚠️ Failed to copy prompt: {e}", RED)

    def _open_bulk_paste_modal(self):
        """Open a dedicated dialog for bulk pasting and editing tracklist text."""
        modal = ctk.CTkToplevel(self.winfo_toplevel())
        modal.title("📝 Bulk Paste Tracklist / Timestamps")
        modal.geometry("640x520")
        modal.resizable(True, True)
        modal.configure(fg_color="#0F1117")
        modal.transient(self.winfo_toplevel())
        modal.grab_set()

        ctk.CTkLabel(modal, text="📝  Bulk Paste Tracklist / Timestamps",
                     font=("Inter", 15, "bold"), text_color="#38bdf8").pack(anchor="w", padx=20, pady=(16, 4))
        ctk.CTkLabel(
            modal,
            text="Paste your songs / segments text below. Supported formats:\n"
                 "• Opening Prayer and Worship: (0:00:00 - 0:02:29)\n"
                 "• \"Hold My Hand\" Worship Section: (0:02:47 - 0:04:39)\n"
                 "• Title: 0:00:00 - 0:02:29\n"
                 "• Title | 0:00:00 | 0:02:29\n"
                 "• 0:00:00 Intro, 02:30 Song 1 (Chapters)",
            font=("Inter", 11),
            text_color=TEXT_DIM,
            justify="left"
        ).pack(anchor="w", padx=20, pady=(0, 10))

        txt_box = ctk.CTkTextbox(
            modal, font=("Consolas", 12), fg_color=BG_INPUT,
            border_color="#2A2E40", border_width=1, corner_radius=8
        )
        txt_box.pack(fill="both", expand=True, padx=20, pady=(0, 12))

        # Pre-fill from clipboard if it contains timestamps
        try:
            cb = self.clipboard_get()
            if any(c in cb for c in [":", "-", "|"]):
                txt_box.insert("1.0", cb.strip())
        except Exception:
            pass

        btn_row = ctk.CTkFrame(modal, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 16))

        def _do_load():
            content = txt_box.get("1.0", "end").strip()
            if not content:
                messagebox.showwarning("Empty", "Please paste your tracklist text first.", parent=modal)
                return
            segments = self._parse_clipboard_text(content)
            if not segments:
                messagebox.showwarning("No Segments Found", "Could not parse any timestamps from the entered text.", parent=modal)
                return
            self._load_segments_into_table(segments)
            modal.destroy()

        ctk.CTkButton(btn_row, text="✔  Load into Table", font=("Inter", 12, "bold"),
                      fg_color=GREEN, hover_color="#2AAA6A", text_color="#001A0D",
                      height=34, width=160, command=_do_load).pack(side="left", padx=(0, 8))

        ctk.CTkButton(btn_row, text="Cancel", font=("Inter", 11),
                      fg_color="#1E2130", hover_color="#2A2E40",
                      height=34, width=90, command=modal.destroy).pack(side="right")


    # ── File / folder pickers ─────────────────────────────────────────────────
    def _browse_file(self):
        path = filedialog.askopenfilename(
            title="Select audio file",
            filetypes=[("Audio files", "*.mp3 *.wav *.m4a *.opus *.ogg *.flac *.aac"), ("All", "*.*")]
        )
        if path:
            self._audio_path = path
            short = Path(path).name
            file_mb = Path(path).stat().st_size / (1024 * 1024) if Path(path).exists() else 0.0
            dur = self._probe_audio_duration(path)
            dur_str = f", Duration: {format_duration(dur)}" if dur > 0 else ""
            self.file_lbl.configure(text=f"{short[:40]} ({file_mb:.1f} MB{dur_str})", text_color=GREEN)
            self._log(f"📂  Using existing audio: {short} ({file_mb:.1f} MB{dur_str})", GREEN)
            self._set_status(f"Loaded: {short} ({format_duration(dur)}) — ready to split")

    def _browse_out(self):
        path = filedialog.askdirectory(title="Choose output folder")
        if path:
            self.out_var.set(path)

    # ── Token & Cookies Management (Bypass Bot Check & 403 Forbidden) ─────────
    def _get_cookie_cfg_path(self) -> Path:
        p = Path.home() / "AppData" / "Local" / "StoriesStudio"
        p.mkdir(parents=True, exist_ok=True)
        return p / "yt_splitter_config.json"

    def _load_saved_token(self) -> str:
        cfg_p = self._get_cookie_cfg_path()
        if cfg_p.exists():
            try:
                with open(cfg_p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    tok = data.get("token", "")
                    if tok:
                        return tok
            except Exception:
                pass
        # Also check suno config
        suno_p = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))) / "StoriesStudio" / "suno_downloader" / "suno_config.json"
        if suno_p.exists():
            try:
                with open(suno_p, "r", encoding="utf-8") as f:
                    return json.load(f).get("token", "")
            except Exception:
                pass
        return ""

    def _save_token(self):
        tok = self.token_var.get().strip()
        cfg_p = self._get_cookie_cfg_path()
        try:
            cfg = {}
            if cfg_p.exists():
                try:
                    with open(cfg_p, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                except Exception:
                    pass
            cfg["token"] = tok
            with open(cfg_p, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            if tok:
                self.token_status_lbl.configure(text="● Active", text_color=GREEN)
                self._log(f"🔑  YouTube Token / Cookie saved successfully ({len(tok)} chars)", GREEN)
            else:
                self.token_status_lbl.configure(text="● Not Configured", text_color=TEXT_DIM)
                self._log("🔑  Saved empty YouTube Token / Cookie.")
        except Exception as e:
            self._log(f"⚠  Failed to save token: {e}", RED)

    def _clear_token(self):
        self.token_var.set("")
        self._save_token()
        self.token_status_lbl.configure(text="● Not Configured", text_color=TEXT_DIM)
        self._log("🔑  Cleared YouTube Token / Cookies.")

    def _upload_cookies_file(self):
        """Allow user to directly upload any exported cookies file (.txt, .json, .cookies)."""
        p = filedialog.askopenfilename(
            title="Upload Cookies File (.txt, .json, .cookies)",
            filetypes=[
                ("Cookie Files (*.txt, *.json, *.cookies)", "*.txt;*.json;*.cookies;*.cookie;*.dat"),
                ("Text Files (*.txt)", "*.txt"),
                ("JSON Files (*.json)", "*.json"),
                ("All Files (*.*)", "*.*")
            ]
        )
        if not p:
            return

        try:
            content = ""
            for enc in ("utf-8", "utf-8-sig", "latin-1", "cp1252"):
                try:
                    with open(p, "r", encoding=enc) as f:
                        content = f.read()
                    break
                except Exception:
                    continue

            if not content.strip():
                messagebox.showwarning("Empty File", "The selected cookie file appears to be empty.", parent=self)
                return

            cf = self._prepare_netscape_cookies(content)
            if not cf:
                cf = p

            self.token_var.set(cf)
            self._save_token()
            self.token_status_lbl.configure(text="● Active (Uploaded)", text_color=GREEN)

            filename = Path(p).name
            self._log(f"📤  Cookies file uploaded & activated: {filename}", GREEN)
            messagebox.showinfo(
                "Cookies Uploaded",
                f"✔ Cookies successfully uploaded from:\n{filename}\n\n"
                f"Active file: {cf}\n\n"
                f"Your YouTube cookies are now saved and ready to bypass bot-checks & 403 errors!"
            )
        except Exception as e:
            self._log(f"✖  Failed to upload cookies file: {e}", RED)
            messagebox.showerror("Upload Error", f"Could not read cookie file:\n{e}")

    def _browse_cookies_file(self):
        self._upload_cookies_file()

    def _use_browser_cookies(self):
        mb = messagebox.askyesno(
            "Auto-Import Cookies",
            "Click YES to use Google Chrome cookies.\nClick NO to use Microsoft Edge cookies."
        )
        browser = "chrome" if mb else "edge"
        self.token_var.set(browser)
        self._save_token()
        self._log(f"🌐  Configured to auto-fetch cookies from {browser.capitalize()}", GREEN)

    def _verify_token(self):
        tok = self.token_var.get().strip()
        if not tok:
            messagebox.showwarning("Verify Token", "Please paste a token or select a cookie file/browser first.")
            return

        self._log("⚡  Verifying YouTube token / cookie session...")
        self.token_status_lbl.configure(text="● Verifying…", text_color=ORANGE)

        def _test_worker():
            try:
                import yt_dlp
                yopts = {
                    "simulate": True,
                    "noplaylist": True,
                    "nocheckcertificate": True,
                    "socket_timeout": 20,
                    "extractor_args": {"youtube": {"player_client": ["ios", "web", "mweb"]}},
                    "quiet": True,
                    "no_warnings": True,
                }
                if tok.lower() in ("chrome", "edge", "firefox", "brave", "opera"):
                    yopts["cookiesfrombrowser"] = (tok.lower(),)
                elif os.path.isfile(tok):
                    yopts["cookiefile"] = tok
                else:
                    cf = self._prepare_netscape_cookies(tok)
                    if cf:
                        yopts["cookiefile"] = cf
                with yt_dlp.YoutubeDL(yopts) as ydl:
                    ydl.extract_info("https://www.youtube.com/watch?v=dQw4w9WgXcQ", download=False)
                self.after(0, lambda: self._log("✅  YouTube session valid and working!", GREEN))
                self.after(0, lambda: self.token_status_lbl.configure(text="● Valid", text_color=GREEN))
            except Exception as e:
                self.after(0, lambda err=str(e): self._log(f"⚠️  Verification warning: {err[:120]}", ORANGE))
                self.after(0, lambda: self.token_status_lbl.configure(text="● Warning", text_color=ORANGE))

        threading.Thread(target=_test_worker, daemon=True).start()

    # ── Log helper ────────────────────────────────────────────────────────────
    def _log(self, msg: str, color: str = "#C8CDD8"):
        ts = time.strftime("%H:%M:%S")
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{ts}] {msg}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _set_status(self, text: str):
        self.status_lbl.configure(text=text)

    def _update_dl_progress(self, text: str, pct_fraction: float = None):
        try:
            if pct_fraction is not None:
                self.progress.stop()
                self.progress.set(max(0.0, min(1.0, float(pct_fraction))))
            self.status_lbl.configure(text=text)
        except Exception:
            pass

    def _set_busy(self, busy: bool):
        self._busy = busy
        if busy:
            self.progress.start()
            self.dl_btn.configure(state="disabled")
            self.split_btn.configure(state="disabled")
        else:
            self.progress.stop()
            self.progress.set(0)
            self.dl_btn.configure(state="normal")
            self.split_btn.configure(state="normal")

    # ── Download ──────────────────────────────────────────────────────────────
    def _start_download(self):
        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("No URL", "Please enter a YouTube URL.")
            return
        if self._busy:
            return

        self._set_busy(True)
        self._set_status("Connecting to stream & fetching info…")
        threading.Thread(target=self._download_worker, args=(url,), daemon=True).start()

    def _download_worker(self, url: str):
        try:
            import yt_dlp
            out_dir = Path(self.out_var.get())
            out_dir.mkdir(parents=True, exist_ok=True)
            out_template = str(out_dir / "%(title)s.%(ext)s")

            # 1. Fetch metadata first
            expected_dur = 0.0
            try:
                self.after(0, lambda: self._update_dl_progress("Connecting to stream & probing audio info…", 0.05))
                probe_opts = {
                    "quiet": True,
                    "no_warnings": True,
                    "noplaylist": True,
                    "nocheckcertificate": True,
                    "socket_timeout": 15,
                    "extractor_args": {"youtube": {"player_client": ["web_embedded", "android"]}},
                }
                tok = self.token_var.get().strip()
                if tok:
                    if os.path.isfile(tok):
                        probe_opts["cookiefile"] = tok
                    elif tok.lower() in ("chrome", "edge", "firefox", "brave", "opera"):
                        pass
                    else:
                        cf = self._prepare_netscape_cookies(tok)
                        if cf and os.path.isfile(cf):
                            probe_opts["cookiefile"] = cf
                with yt_dlp.YoutubeDL(probe_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        expected_dur = float(info.get("duration") or 0.0)
                        title = info.get("title", "")
                        if title:
                            self.after(0, lambda t=title, d=expected_dur: self._log(
                                f"ℹ  Target: {t[:55]} ({format_duration(d)})", ACCENT
                            ))
            except Exception:
                pass

            # 2. Resilient download with live speed, percentage & ETA
            tok = self.token_var.get().strip()
            cookie_file = None
            browser_cookie = None
            is_browser_cookie = False

            if tok:
                if os.path.isfile(tok):
                    cookie_file = tok
                    self._log(f"🔑  Using uploaded cookie file: {Path(tok).name}", GREEN)
                elif tok.lower() in ("chrome", "edge", "firefox", "brave", "opera"):
                    is_browser_cookie = True
                    browser_cookie = tok.lower()
                    self._log(f"🔑  Using browser cookies: {tok.lower().capitalize()}")
                else:
                    cf = self._prepare_netscape_cookies(tok)
                    if cf and os.path.isfile(cf):
                        cookie_file = cf
                        self._log("🔑  Using converted YouTube token / cookie session", GREEN)
            else:
                self._log("ℹ  No cookies configured. Using high-speed embedded stream...", ACCENT)

            strategies = [
                {"client": "web_embedded,android", "use_cookies": True, "label": "Web Embedded + Android"},
                {"client": "web_embedded,android", "use_cookies": False, "label": "Direct Web Embedded (Bypassing browser lock)"},
                {"client": "android_vr,web", "use_cookies": False, "label": "Android VR Fallback"},
                {"client": "default", "use_cookies": False, "label": "Standard Stream Fallback"}
            ]

            success = False
            last_err = ""
            filepath = None
            last_milestone = [-1]

            def _progress_hook(d):
                nonlocal filepath
                status = d.get("status")
                if status == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                    downloaded = d.get("downloaded_bytes") or 0
                    speed = d.get("speed") or 0
                    eta = d.get("eta")

                    down_mb = (downloaded / (1024 * 1024))
                    speed_mb = (speed / (1024 * 1024)) if speed else 0.0

                    if speed_mb >= 1.0:
                        speed_str = f"{speed_mb:.1f} MB/s"
                    elif speed:
                        speed_str = f"{speed / 1024:.0f} KB/s"
                    else:
                        speed_str = "downloading..."

                    eta_str = f"{int(eta)}s" if eta is not None else ""

                    if total > 0:
                        tot_mb = (total / (1024 * 1024))
                        pct = (downloaded / total) * 100.0
                        frac = max(0.0, min(1.0, downloaded / total))
                        eta_part = f" • ⏱ ETA: {eta_str}" if eta_str else ""
                        status_msg = f"Downloading: {pct:.1f}% ({down_mb:.1f} / {tot_mb:.1f} MB) • ⚡ Speed: {speed_str}{eta_part}"
                    else:
                        pct = 0.0
                        frac = 0.35
                        status_msg = f"Downloading: {down_mb:.1f} MB • ⚡ Speed: {speed_str}"

                    self.after(0, lambda m=status_msg, f=frac: self._update_dl_progress(m, f))

                    int_pct = int(pct)
                    if int_pct >= 20 and int_pct // 20 > last_milestone[0]:
                        last_milestone[0] = int_pct // 20
                        ms = (int_pct // 20) * 20
                        if ms <= 100:
                            self.after(0, lambda m=ms, sp=speed_str, dmb=down_mb: self._log(
                                f"⬇  Download: {m}% ({dmb:.1f} MB) | Speed: {sp}"
                            ))

                elif status == "finished":
                    filepath = d.get("filename")
                    self.after(0, lambda: self._update_dl_progress("Extracting & Converting audio to 320k MP3…", 0.98))
                    self.after(0, lambda: self._log("⚡  Download finished! Extracting 320k MP3 with FFmpeg...", ACCENT))

            for s_idx, strat in enumerate(strategies, 1):
                if s_idx == 2 and not is_browser_cookie:
                    continue

                self.after(0, lambda lbl=strat["label"]: self._log(f"⬇  Downloading audio ({lbl})…"))
                self.after(0, lambda lbl=strat["label"]: self._update_dl_progress(f"Connecting to audio stream ({lbl})…", 0.1))

                ydl_opts = {
                    "format": "ba[ext=m4a]/ba/b[height<=480]/b",
                    "outtmpl": out_template,
                    "noplaylist": True,
                    "nocheckcertificate": True,
                    "socket_timeout": 35,
                    "retries": 10,
                    "fragment_retries": 10,
                    "continuedl": True,
                    "postprocessors": [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "0",
                    }],
                    "progress_hooks": [_progress_hook],
                    "quiet": True,
                    "no_warnings": True,
                }

                if strat["client"] != "default":
                    ydl_opts["extractor_args"] = {"youtube": {"player_client": strat["client"].split(",")}}

                if FF and os.path.isfile(FF):
                    ydl_opts["ffmpeg_location"] = os.path.dirname(os.path.abspath(FF))

                if strat["use_cookies"]:
                    if browser_cookie:
                        ydl_opts["cookiesfrombrowser"] = (browser_cookie,)
                    elif cookie_file:
                        ydl_opts["cookiefile"] = cookie_file

                try:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ret_code = ydl.download([url])
                        if ret_code == 0:
                            success = True
                            break
                except Exception as ex:
                    err_out = str(ex)
                    last_err = err_out[-400:]
                    if "database is locked" in err_out or "Could not copy Chrome cookie" in err_out:
                        self.after(0, lambda: self._log("Cookie database locked. Direct stream fallback...", ORANGE))
                    elif any(b in err_out.lower() for b in ["403", "forbidden", "bot"]):
                        self.after(0, lambda lbl=strat["label"]: self._log(
                            f"ℹ  Client throttled ({lbl}). Trying next fallback...",
                            ORANGE
                        ))
                    else:
                        self.after(0, lambda e=last_err[:120]: self._log(f"ℹ  Attempt notice: {e}", ORANGE))

            if not success:
                raise RuntimeError(last_err or "Download failed after multiple fallback attempts.")

            if not filepath or not Path(filepath).exists():
                mp3s = sorted(out_dir.glob("*.mp3"), key=os.path.getmtime, reverse=True)
                if mp3s:
                    filepath = str(mp3s[0])
                else:
                    raise RuntimeError("Could not locate downloaded audio file.")

            self._audio_path = filepath
            short = Path(filepath).name
            file_mb = Path(filepath).stat().st_size / (1024 * 1024) if Path(filepath).exists() else 0.0
            actual_dur = self._probe_audio_duration(filepath)
            dur_str = f", Duration: {format_duration(actual_dur)}" if actual_dur > 0 else ""

            if expected_dur > 60 and actual_dur > 0 and actual_dur < (expected_dur * 0.85):
                trunc_msg = f"Incomplete Download: {format_duration(actual_dur)} of {format_duration(expected_dur)}. YouTube severed connection early."
                self.after(0, lambda: self._log(trunc_msg, ORANGE))
                self.after(0, lambda: messagebox.showwarning("Download Truncated", trunc_msg))
            else:
                self.after(0, lambda: self._log(f"Complete Download: {short} ({file_mb:.1f} MB{dur_str})", GREEN))

            self.after(0, lambda: self.file_lbl.configure(text=f"{short[:40]} ({file_mb:.1f} MB)", text_color=GREEN))
            self.after(0, lambda: self._update_dl_progress(f"Download complete ({format_duration(actual_dur)}) — ready to split", 1.0))

        except Exception as e:
            self.after(0, lambda: self._log(f"✖  Download failed: {e}", RED))
            self.after(0, lambda: self._update_dl_progress("Download failed", 0.0))
        finally:
            self.after(0, lambda: self._set_busy(False))

    # ── Split ─────────────────────────────────────────────────────────────────
    def _start_split(self):
        if self._busy:
            return
        if not self._audio_path or not Path(self._audio_path).exists():
            messagebox.showwarning("No Audio", "Download audio first or browse an existing file.")
            return

        segments = []
        for row in self._rows:
            d = row.get_data()
            if not d["name"] or not d["start"] or not d["end"]:
                continue
            segments.append((row, d))

        if not segments:
            messagebox.showwarning("No Segments", "Add at least one segment with name, start, and end.")
            return

        # Reset statuses
        for row, _ in segments:
            row.set_status("idle")

        self._set_busy(True)
        self._set_status("Splitting…")
        threading.Thread(target=self._split_worker, args=(segments,), daemon=True).start()

    def _split_worker(self, segments):
        out_dir = Path(self.out_var.get())
        out_dir.mkdir(parents=True, exist_ok=True)

        ok_count = 0
        fail_count = 0

        # Probe source audio duration to validate segment bounds and prevent 0 KB files
        source_dur = self._probe_audio_duration(self._audio_path)
        if source_dur > 0:
            self._log(f"ℹ  Source audio length: {format_duration(source_dur)} ({source_dur:.1f}s)", ACCENT)

        for idx, (row, data) in enumerate(segments):
            name  = sanitize_filename(data["name"])
            start = data["start"]
            end   = data["end"]

            self.after(0, lambda r=row: r.set_status("processing"))
            self.after(0, lambda n=name: self._set_status(f"Cutting: {n}"))

            try:
                start_sec = parse_timestamp(start)
                end_sec   = parse_timestamp(end)

                # Check if start timestamp is past the end of the source audio
                if source_dur > 0 and start_sec >= source_dur:
                    raise ValueError(
                        f"Start time ({start} = {start_sec:.0f}s) is beyond audio duration ({format_duration(source_dur)}). "
                        "The source audio file is shorter than this timestamp. (Download was cut off or wrong file selected)."
                    )

                # Clamp end time if it slightly exceeds source duration
                if source_dur > 0 and end_sec > source_dur:
                    self._log(f"ℹ  Clamping '{name}' end from {end} to audio end ({format_duration(source_dur)})")
                    end_sec = source_dur

                duration  = end_sec - start_sec
                if duration <= 0:
                    raise ValueError(f"Invalid duration ({duration:.1f}s). End ({end}) must be after start ({start})")

                # Zero-padded index in filename
                out_file = out_dir / f"{idx+1:02d}. {name}.mp3"

                # Fast seeking with -ss BEFORE -i, -nostdin to prevent hangs, make_zero for clean start
                cmd = [
                    FF, "-y", "-nostdin",
                    "-ss", str(start_sec),
                    "-i", self._audio_path,
                    "-t",  str(duration),
                    "-avoid_negative_ts", "make_zero",
                    "-acodec", "libmp3lame",
                    "-q:a", "0",
                    str(out_file)
                ]
                result = _rq(cmd, capture_output=True, text=True, timeout=180)

                if result.returncode != 0:
                    if out_file.exists():
                        try: out_file.unlink()
                        except Exception: pass
                    err = result.stderr[-300:] if result.stderr else "ffmpeg error"
                    raise RuntimeError(err)

                # Verify file exists and is not empty / 0 KB
                if not out_file.exists() or out_file.stat().st_size <= 1024:
                    if out_file.exists():
                        try: out_file.unlink()
                        except Exception: pass
                    raise RuntimeError("Export produced an empty file (0 KB). Audio segment was not exported.")

                dur_str = format_duration(duration)
                file_mb = out_file.stat().st_size / (1024 * 1024)
                self.after(0, lambda r=row: r.set_status("done"))
                self.after(0, lambda n=name, d=dur_str, f=out_file.name, sz=file_mb:
                           self._log(f"✔  [{d}] {f} ({sz:.2f} MB)", GREEN))
                ok_count += 1

            except Exception as e:
                self.after(0, lambda r=row: r.set_status("error"))
                self.after(0, lambda n=name, err=str(e):
                           self._log(f"✖  {n}: {err}", RED))
                fail_count += 1

        summary = f"Done — {ok_count} segment(s) exported"
        if fail_count:
            summary += f", {fail_count} failed"
        self.after(0, lambda: self._set_status(summary))
        self.after(0, lambda: self._log(f"📁  Output: {out_dir}", ACCENT))
        self.after(0, lambda: self._set_busy(False))

        if ok_count:
            self.after(0, lambda: messagebox.showinfo(
                "Done!",
                f"{ok_count} segment(s) saved to:\n{out_dir}"
            ))


def create(parent_frame, boot_data=None):
    """Plugin-compatible create — Music tab ke andar mount hota hai.
    Internal 2 sections: Video Maker + Audio Splitter."""
    try: parent_frame.configure(fg_color=BG_M)
    except: pass
    _cfg=load_cfg()
    if _cfg.get("ffmpeg_path") and set_ff(_cfg["ffmpeg_path"]):
        print("  ffmpeg (saved): "+str(FF))
    main_container = ctk.CTkFrame(parent_frame, fg_color=BG_M, corner_radius=0)
    try:
        main_container.pack(fill="both", expand=True)
    except Exception:
        main_container.grid(row=0, column=0, sticky="nsew")
        try:
            parent_frame.grid_columnconfigure(0, weight=1)
            parent_frame.grid_rowconfigure(0, weight=1)
        except Exception:
            pass
    top_bar = ctk.CTkFrame(main_container, fg_color=BG_C, height=36, corner_radius=6)
    top_bar.pack(fill="x", side="top", padx=6, pady=(6,0))
    preset_w = preset_manager.PresetWidget(
        top_bar,
        tool_id="song_video_maker",
        collect_fn=lambda: load_cfg(),
        apply_fn=lambda d: save_cfg(d) if isinstance(d, dict) else None
    )
    preset_w.pack(side="right", padx=6, pady=2)
    tabs=ctk.CTkTabview(main_container,fg_color=BG_M,
                        segmented_button_fg_color=BG_C,
                        segmented_button_selected_color=AR,
                        segmented_button_selected_hover_color=AP,
                        segmented_button_unselected_color=BG_C,
                        text_color=T1)
    tabs.pack(fill="both",expand=True,padx=6,pady=6)
    t_vid=tabs.add("\U0001f3ac  Video Maker")
    t_spl=tabs.add("\u2702  Audio Splitter")
    c=ctk.CTkFrame(t_vid,fg_color=BG_M); c.pack(fill="both",expand=True)
    _build_video_maker(c)
    YTAudioSplitter(t_spl).pack(fill="both",expand=True)


def main():
    """Standalone run — testing ke liye."""
    ctk.set_appearance_mode("dark"); root=ctk.CTk()
    root.title("Song Video Maker v19"); root.geometry("1400x900"); root.minsize(1120,730)
    try: root.configure(fg_color=BG_M)
    except: pass
    f=ctk.CTkFrame(root,fg_color=BG_M); f.pack(fill="both",expand=True)
    create(f)
    root.mainloop()

if __name__=="__main__": main()
