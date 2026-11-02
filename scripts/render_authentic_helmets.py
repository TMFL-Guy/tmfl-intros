#!/usr/bin/env python3
"""Deterministic 32-team helmet flythrough; never AI-generates or alters team logos."""
import io, math, os, pathlib, subprocess
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont
ROOT=pathlib.Path(__file__).resolve().parent.parent
OUT=ROOT/"output"; OUT.mkdir(exist_ok=True)
ASSETS=ROOT/"assets"
TEAMS="ARI ATL BAL BUF CAR CHI CIN CLE DAL DEN DET GB HOU IND JAX KC LAC LAR LV MIA MIN NE NO NYG NYJ PHI PIT SEA SF TB TEN WAS".split()
BASE="https://raw.githubusercontent.com/samhoppen/NFL-data-viz/master/helmet_left/"
W,H=1280,720
def load_helmet(code):
    local=ASSETS/"helmets"/(code+".png")
    if local.exists(): return Image.open(local).convert("RGBA")
    if code in ("KC","WAS"):
        raise RuntimeError("Authentic "+code+" helmet required: upload assets/helmets/"+code+".png. Public dataset uses an intentionally modified helmet.")
    r=requests.get(BASE+code+".png",timeout=25); r.raise_for_status()
    return Image.open(io.BytesIO(r.content)).convert("RGBA")
def fit(img,w,h):
    img=img.copy(); img.thumbnail((max(1,int(w)),max(1,int(h))),Image.Resampling.LANCZOS);return img
def render():
    logo_file=ASSETS/"tmfl-logo.png"
    if not logo_file.exists(): raise RuntimeError("Upload your exact official TMFL logo as assets/tmfl-logo.png")
    logo=Image.open(logo_file).convert("RGBA")
    helmets=[load_helmet(t) for t in TEAMS]
    frames=120; fps=30
    output=OUT/"TMFL-The-32-Authentic-Helmets.mp4"
    proc=subprocess.Popen(["ffmpeg","-y","-f","rawvideo","-pix_fmt","rgb24","-s",f"{W}x{H}","-r",str(fps),"-i","-","-an","-c:v","libx264","-preset","fast","-crf","20","-pix_fmt","yuv420p",str(output)],stdin=subprocess.PIPE)
    try:
      for i in range(frames):
        p=i/(frames-1); travel=p*17.8
        bg=Image.new("RGB",(W,H),(4,7,18)); d=ImageDraw.Draw(bg)
        d.polygon([(0,H),(W,H),(790,365),(490,365)],fill=(10,14,25))
        d.polygon([(0,0),(W,0),(790,365),(490,365)],fill=(7,10,22))
        for side in (-1,1):
          xedge=0 if side==-1 else W
          d.polygon([(xedge,0),(xedge,H),(490 if side==-1 else 790,365)],fill=(11,17,31))
        for n in range(18):
          z=n-travel
          if z<0.1:continue
          s=1/(1+z*.27); yy=365+245*s
          for side in (-1,1):
            x=640+side*(180+560*s)
            d.line([(x,365-225*s),(x,365+245*s)],fill=(23,46,76),width=max(1,int(6*s)))
            d.line([(x-26*s,yy),(x+26*s,yy)],fill=(130,25,38),width=max(1,int(6*s)))
        canvas=bg.convert("RGBA")
        order=[]
        for j,im in enumerate(helmets):
          side=-1 if j<16 else 1
          idx=j%16
          z=idx+0.5-travel
          if z<0.05:continue
          scale=1/(0.38+z*.33)
          size=min(470,int(210*scale))
          x=int(640+side*(195+450*scale))
          y=int(360+25*scale)
          order.append((z,im,x,y,size))
        for z,im,x,y,size in sorted(order,reverse=True):
          h=fit(im,size,size)
          canvas.alpha_composite(h,(int(x-h.width/2),int(y-h.height/2)))
        # Logo stays exact; enlarges during final push, with no AI reconstruction.
        zoom=max(0,(p-.65)/.35)
        sz=int(110+zoom**2*1280)
        lg=fit(logo,sz,sz)
        canvas.alpha_composite(lg,(int(640-lg.width/2),int(355-lg.height/2)))
        proc.stdin.write(canvas.convert("RGB").tobytes())
    finally:
      proc.stdin.close()
      if proc.wait()!=0:raise RuntimeError("ffmpeg failed")
    (OUT/"status.txt").write_text("SUCCESS: Authentic team helmet sprites, official TMFL logo, deterministic flythrough.\n")
    print(output)
if __name__=="__main__":
    try:render()
    except Exception as e:
      (OUT/"status.txt").write_text("FAILED: "+str(e)+"\n")
      raise
