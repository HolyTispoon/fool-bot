"""Zenith's trailing foot: the image stops at his ankle. Borrow his own leading foot,
turn it to hang off the trailing shin, tone it to that shin, and grow the canvas to hold it."""
import sys; sys.path.insert(0,sys.argv[1]); from kit import *
from PIL import Image
S=sys.argv[1]; ANG=float(sys.argv[2]) if len(sys.argv)>2 else 93; ANK=(157,302); SC=float(sys.argv[3]) if len(sys.argv)>3 else 0.8
src=Image.open(S+'/Zenith_teal.png').convert('RGBA'); W,H=src.size
a=np.asarray(src).astype(float)/255
# the leading foot, from its ankle ring on, and nothing of the shin above it
foot=poly_mask(a.shape[:2],[[(344,236),(356,228),(366,232),(376,244),(440,256),(442,284),(344,284)]])
f=a.copy(); f[...,3]*=foot
# tone: the foot's Lab moved to the trailing shin's mean and spread
shin=box(a.shape[:2],150,262,200,300)&(a[...,3]>0.9)
fl=lab(f); sl=lab(a)[shin]; fm=foot&(a[...,3]>0.9)
mu_f,sd_f=fl[fm].mean(0),fl[fm].std(0)+1e-6; mu_s,sd_s=sl.mean(0),sl.std(0)+1e-6
t=(fl-mu_f)/sd_f*sd_s+mu_s
f[...,:3]=np.where(fm[...,None]|(f[...,3:4]>0),np.clip(color.lab2rgb(t),0,1),f[...,:3])
fimg=Image.fromarray((f*255+.5).astype(np.uint8),'RGBA').crop((336,220,446,290))
# rotate about the ring (355,242), i.e. (19,22) in the crop
piv=(19,22); big=Image.new('RGBA',(300,300),(0,0,0,0)); big.alpha_composite(fimg,(150-piv[0],150-piv[1]))
big=big.resize((int(300*SC),int(300*SC)),Image.LANCZOS); cc=150*SC
rot=big.rotate(-ANG,resample=Image.BICUBIC,center=(cc,cc))
bb=rot.getbbox(); need=max(H, int(ANK[1]-cc+bb[3]+2))
canvas=Image.new('RGBA',(W,need),(0,0,0,0)); canvas.alpha_composite(src,(0,0))
# the leg's own stump below the ankle knob goes; the new foot takes its place
c=np.asarray(canvas).copy(); stump=poly_mask(c.shape[:2],[[(138,309),(170,309),(172,323),(138,323)]]); c[stump,3]=0
canvas=Image.fromarray(c,'RGBA')
canvas.alpha_composite(rot,(int(ANK[0]-cc),int(ANK[1]-cc)))
canvas.save(S+f'/Zenith_teal_foot.png'); print('canvas',canvas.size)
