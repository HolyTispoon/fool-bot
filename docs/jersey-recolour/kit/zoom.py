"""zoom.py src x0 y0 x1 y1 scale out [src2]: crop in original coords, grid every 10px, labels every 50; side by side with src2."""
import sys
from PIL import Image, ImageDraw, ImageFont
src,x0,y0,x1,y1,sc,out=sys.argv[1],*map(int,sys.argv[2:7]),sys.argv[7]
srcs=[src]+sys.argv[8:]
f=ImageFont.truetype('d12ball/fonts/DejaVuSans.ttf',12)
tiles=[]
for s_ in srcs:
    im=Image.open(s_).convert('RGBA').crop((x0,y0,x1,y1))
    bg=Image.new('RGBA',im.size,(128,128,128,255)); bg.alpha_composite(im)
    bg=bg.resize((im.width*sc,im.height*sc),Image.NEAREST).convert('RGB'); d=ImageDraw.Draw(bg)
    for x in range((x0//10+1)*10,x1,10):
        d.line([((x-x0)*sc,0),((x-x0)*sc,bg.height)],fill=(0,255,255) if x%50==0 else (70,70,70))
        if x%50==0: d.text(((x-x0)*sc+2,2),str(x),fill=(255,255,0),font=f)
    for y in range((y0//10+1)*10,y1,10):
        d.line([(0,(y-y0)*sc),(bg.width,(y-y0)*sc)],fill=(0,255,255) if y%50==0 else (70,70,70))
        if y%50==0: d.text((2,(y-y0)*sc+2),str(y),fill=(255,255,0),font=f)
    tiles.append(bg)
W=sum(t.width for t in tiles)+10*(len(tiles)-1); o=Image.new('RGB',(W,tiles[0].height),(0,0,0)); x=0
for t in tiles: o.paste(t,(x,0)); x+=t.width+10
o.save(out)
