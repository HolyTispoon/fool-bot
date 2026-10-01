import sys
from PIL import Image, ImageDraw, ImageFont
name=sys.argv[1]; scale=float(sys.argv[2]) if len(sys.argv)>2 else 2
src=sys.argv[3] if len(sys.argv)>3 else f'd12ball/images/player_images/{name}.png'
im=Image.open(src).convert('RGBA')
bg=Image.new('RGBA',im.size,(128,128,128,255)); bg.alpha_composite(im)
bg=bg.resize((int(im.width*scale),int(im.height*scale)),Image.LANCZOS).convert('RGB')
d=ImageDraw.Draw(bg); f=ImageFont.truetype('d12ball/fonts/DejaVuSans.ttf',11)
step=25
for x in range(0,im.width,step):
    d.line([(x*scale,0),(x*scale,bg.height)],fill=(0,255,255) if x%100==0 else (90,90,90),width=1)
    if x%50==0: d.text((x*scale+2,2),str(x),fill=(255,255,0),font=f)
for y in range(0,im.height,step):
    d.line([(0,y*scale),(bg.width,y*scale)],fill=(0,255,255) if y%100==0 else (90,90,90),width=1)
    if y%50==0: d.text((2,y*scale+2),str(y),fill=(255,255,0),font=f)
out=sys.argv[4] if len(sys.argv)>4 else f'/tmp/claude-0/-home-user-fool-bot/99138136-0f52-59e6-aa80-ba7e374ec3ff/scratchpad/pilot/grid_{name}.png'
bg.save(out); print(im.size)
