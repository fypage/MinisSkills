#!/usr/bin/env python3
import argparse, math, random, re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

PALETTES = {
    'aurora': ('#07111f', '#26f2bd', '#5d78ff', '#ff65bd'),
    'cyberpunk': ('#080616', '#00e5ff', '#ff2bd6', '#ffd166'),
    'sunset': ('#24122d', '#ff7a59', '#ffd166', '#4cc9f0'),
    'forest': ('#08130d', '#2dd36f', '#98f5a4', '#1b4332'),
    'minimal': ('#f6f1e9', '#111827', '#e76f51', '#2a9d8f'),
}

def slugify(text):
    s = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fff]+', '_', text.strip()).strip('_')
    return (s[:36] or 'generated_image') + '.png'

def pick_palette(prompt):
    p = prompt.lower()
    if any(k in p for k in ['极光','aurora','夜','星空']): return PALETTES['aurora']
    if any(k in p for k in ['赛博','cyber','neon','霓虹']): return PALETTES['cyberpunk']
    if any(k in p for k in ['日落','sunset','黄昏','暖']): return PALETTES['sunset']
    if any(k in p for k in ['森林','forest','自然','绿色']): return PALETTES['forest']
    if any(k in p for k in ['极简','minimal','海报','poster']): return PALETTES['minimal']
    return random.choice(list(PALETTES.values()))

def hexrgb(h):
    h=h.lstrip('#')
    return tuple(int(h[i:i+2],16) for i in (0,2,4))

def lerp(a,b,t): return int(a+(b-a)*t)

def generate(prompt, output, size):
    W,H = map(int, size.lower().split('x'))
    random.seed(abs(hash(prompt)) % (2**32))
    bg, c1, c2, c3 = [hexrgb(x) for x in pick_palette(prompt)]
    img = Image.new('RGB',(W,H),bg); px = img.load()
    for y in range(H):
        t=y/max(1,H-1)
        for x in range(W):
            n=(math.sin(x/W*math.pi*2)+math.cos((x+y)/W*math.pi*1.7))*0.08
            tt=max(0,min(1,t+n))
            px[x,y]=tuple(lerp(bg[i], c2[i], tt*0.45) for i in range(3))
    img=img.convert('RGBA')
    overlay=Image.new('RGBA',(W,H),(0,0,0,0)); d=ImageDraw.Draw(overlay)
    # luminous bands / abstract composition
    for band,col in enumerate([c1,c2,c3]):
        pts=[]; base=H*(0.25+0.14*band); amp=H*(0.06+0.02*band)
        for x in range(-W//10, W+W//10, max(12,W//48)):
            y=base+math.sin(x/(W*0.09)+band)*amp+math.sin(x/(W*0.035))*amp*0.25
            pts.append((x,y))
        poly=pts+[(W+W//10,base+H*.25),(-W//10,base+H*.25)]
        d.polygon(poly,fill=(*col,70))
    overlay=overlay.filter(ImageFilter.GaussianBlur(max(12,W//40)))
    img=Image.alpha_composite(img,overlay)
    d=ImageDraw.Draw(img)
    # stars / particles
    for _ in range(max(120, W*H//2200)):
        x=random.randrange(W); y=random.randrange(max(1,int(H*.68)))
        r=random.choice([1,1,1,2,2,3])
        br=random.randrange(140,256)
        d.ellipse((x-r,y-r,x+r,y+r),fill=(br,br,br,random.randrange(50,190)))
    # central sun/moon orb
    ox=random.randint(int(W*.58), int(W*.78)); oy=random.randint(int(H*.12), int(H*.28)); rr=int(min(W,H)*.07)
    d.ellipse((ox-rr,oy-rr,ox+rr,oy+rr),fill=(*c3,190))
    # mountains / skyline
    for layer in range(3):
        base=H*(0.70+layer*.08)
        shade=(max(0,bg[0]-layer*2), max(0,bg[1]-layer*5), max(0,bg[2]-layer*7), 245)
        pts=[(0,H)]
        step=max(40,W//14)
        for x in range(0,W+step,step):
            y=base-random.randrange(int(H*.05),int(H*.18))+math.sin(x/(W*.08)+layer)*H*.025
            pts.append((x,y))
        pts.append((W,H)); d.polygon(pts,fill=shade)
    # reflection lines
    for _ in range(70):
        y=random.randrange(int(H*.72), H-10); x=random.randrange(W)
        length=random.randrange(max(15,W//40), max(30,W//6))
        col=random.choice([c1,c2,c3])
        d.line((x,y,min(W,x+length),y),fill=(*col,random.randrange(20,75)),width=max(1,W//700))
    # title if poster/海报 requested
    if any(k in prompt.lower() for k in ['poster','海报','cover','封面']):
        text = prompt[:18]
        d.rectangle((int(W*.06),int(H*.06),int(W*.62),int(H*.15)),fill=(0,0,0,55))
        d.text((int(W*.08),int(H*.08)),text,fill=(255,255,255,230))
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    img.convert('RGB').save(output, quality=95)

if __name__ == '__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--prompt', required=True)
    ap.add_argument('--output')
    ap.add_argument('--size', default='1024x1024')
    args=ap.parse_args()
    out=args.output or ('/var/minis/attachments/'+slugify(args.prompt))
    generate(args.prompt, out, args.size)
    print(out)
