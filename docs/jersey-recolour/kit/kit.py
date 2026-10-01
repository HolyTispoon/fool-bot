"""Scratch recolour kit for the jersey pilot."""
import json, numpy as np
from PIL import Image, ImageDraw
from skimage import color, morphology, measure
import cv2
IMG='d12ball/images/player_images/%s.png'
def load(name):
    a=np.asarray(Image.open(IMG%name).convert('RGBA')).astype(np.float64)/255
    return a
def lab(rgba): return color.rgb2lab(rgba[...,:3])
def hsv(rgba): return color.rgb2hsv(rgba[...,:3])
def poly_mask(shape, polys):
    m=Image.new('L',(shape[1],shape[0]),0); d=ImageDraw.Draw(m)
    for p in polys: d.polygon([tuple(v) for v in p],fill=255)
    return np.asarray(m)>0
def box(shape,x0,y0,x1,y1): return poly_mask(shape,[[(x0,y0),(x1,y0),(x1,y1),(x0,y1)]])
def hue_key(rgba,h0,h1,smin=0.2,vmin=0.0,vmax=1.0):
    h,s,v=np.moveaxis(hsv(rgba),-1,0); h=h*360
    hk=((h>=h0)&(h<=h1)) if h0<=h1 else ((h>=h0)|(h<=h1))
    return hk&(s>=smin)&(v>=vmin)&(v<=vmax)&(rgba[...,3]>0.5)
def model(samples):
    """samples: Nx3 LAB of a kit's fabric -> L quantiles, a(L), b(L)."""
    L,A,B=samples.T
    q=np.percentile(L,np.linspace(0,100,101))
    bins=np.linspace(q[1],q[99],13); c=(bins[:-1]+bins[1:])/2
    am=[];bm=[];cc=[]
    for lo,hi,ci in zip(bins[:-1],bins[1:],c):
        s=(L>=lo)&(L<hi)
        if s.sum()>20: am.append(np.median(A[s]));bm.append(np.median(B[s]));cc.append(ci)
    return dict(q=q,Lc=np.array(cc),a=np.array(am),b=np.array(bm))
def recolour(rgba, soft, tgt, src_sel=None, lstretch=1.0):
    """soft: float mask 0..1 of fabric; src_sel: bool mask used for the source L distribution."""
    Lab=lab(rgba); L=Lab[...,0]
    sel=src_sel if src_sel is not None else soft>0.5
    sq=np.percentile(L[sel],np.linspace(0,100,101))
    sq=np.maximum.accumulate(sq+np.arange(101)*1e-6)
    rank=np.interp(L,sq,np.linspace(0,100,101))
    nL=np.interp(rank,np.linspace(0,100,101),tgt['q'])
    na=np.interp(nL,tgt['Lc'],tgt['a']); nb=np.interp(nL,tgt['Lc'],tgt['b'])
    new=np.stack([nL,na,nb],-1)
    rgb=np.clip(color.lab2rgb(new),0,1)
    out=rgba.copy(); m=soft[...,None]
    out[...,:3]=rgba[...,:3]*(1-m)+rgb*m
    return out
def soften(mask, radius=1.0, min_area=30, hole=40):
    m=morphology.remove_small_objects(mask,min_area)
    m=morphology.remove_small_holes(m,hole)
    f=cv2.GaussianBlur(m.astype(np.float32),(0,0),radius) if radius>0 else m.astype(np.float32)
    return np.clip(f,0,1)*(1.0)
def save(rgba,path): Image.fromarray((np.clip(rgba,0,1)*255+0.5).astype(np.uint8),'RGBA').save(path)
def overlay(rgba,soft,path,colr=(0,255,0)):
    bg=np.full(rgba.shape[:2]+(3,),0.5); a=rgba[...,3:4]
    base=rgba[...,:3]*a+bg*(1-a)
    o=base*(1-0.6*soft[...,None])+np.array(colr)/255*0.6*soft[...,None]
    Image.fromarray((o*255).astype(np.uint8)).save(path)

def hue_deg(Lab): return (np.degrees(np.arctan2(Lab[...,2],Lab[...,1]))+360)%360
def recolour2(rgba, region, core, tgt, mode='chroma', hue_tol=30, feather=1.0, dark_L=None):
    """region: float 0..1 area allowed to change; core: bool, clean fabric pixels.
    mode 'chroma': each pixel's weight is how much of the source kit colour it
    carries (chroma and hue), so white numbers and grey metal inside the
    region stay put.  mode 'dark': weight is how dark the pixel is (black kit)."""
    Lab=lab(rgba); L=Lab[...,0]; C=np.hypot(Lab[...,1],Lab[...,2]); H=hue_deg(Lab)
    sq=np.percentile(L[core],np.linspace(0,100,101)); sq=np.maximum.accumulate(sq+np.arange(101)*1e-6)
    rank=np.interp(L,sq,np.linspace(0,100,101))
    mapped=np.interp(rank,np.linspace(0,100,101),tgt['q'])
    if mode=='chroma':
        C0=np.median(C[core]); h0=np.degrees(np.arctan2(np.median(np.sin(np.radians(H[core]))),np.median(np.cos(np.radians(H[core])))))%360
        dh=np.abs((H-h0+180)%360-180)
        w=np.clip(C/(0.6*C0),0,1)*np.clip(1-(dh-hue_tol)/20,0,1)
    else:
        Lmax=dark_L if dark_L else np.percentile(L[core],97)
        w=np.clip((Lmax+12-L)/12,0,1)*np.clip(1-(C-25)/15,0,1)
    w=w*region
    nL=L+w*(mapped-L)
    na=np.interp(nL,tgt['Lc'],tgt['a']); nb=np.interp(nL,tgt['Lc'],tgt['b'])
    # a pixel only partly kit keeps its own chroma in proportion
    oa=Lab[...,1]*(1-w)+na*w; ob=Lab[...,2]*(1-w)+nb*w
    rgb=np.clip(color.lab2rgb(np.stack([nL,oa,ob],-1)),0,1)
    out=rgba.copy(); out[...,:3]=rgb; return out, w
def feathered(mask, grow=2, radius=1.0):
    m=mask
    if grow>0: m=morphology.binary_dilation(m,morphology.disk(grow))
    return np.clip(cv2.GaussianBlur(m.astype(np.float32),(0,0),radius),0,1) if radius>0 else m.astype(np.float32)
def compare(names_imgs, path, scale=2):
    ims=[]
    for im in names_imgs:
        if isinstance(im,str): im=Image.open(im).convert('RGBA')
        elif isinstance(im,np.ndarray): im=Image.fromarray((np.clip(im,0,1)*255+.5).astype(np.uint8),'RGBA')
        ims.append(im)
    W=sum(i.width for i in ims); H=max(i.height for i in ims)
    s=Image.new('RGBA',(W,H),(128,128,128,255)); x=0
    for i in ims: s.alpha_composite(i,(x,0)); x+=i.width
    s.convert('RGB').resize((W*scale//1,H*scale//1),Image.LANCZOS).save(path)

def recolour_w(rgba, w, core, tgt, base=None):
    """Apply target kit to rgba (or onto base) with a precomputed weight w."""
    Lab=lab(rgba); L=Lab[...,0]
    sq=np.percentile(L[core],np.linspace(0,100,101)); sq=np.maximum.accumulate(sq+np.arange(101)*1e-6)
    rank=np.interp(L,sq,np.linspace(0,100,101))
    mapped=np.interp(rank,np.linspace(0,100,101),tgt['q'])
    nL=L+w*(mapped-L)
    na=np.interp(nL,tgt['Lc'],tgt['a']); nb=np.interp(nL,tgt['Lc'],tgt['b'])
    oa=Lab[...,1]*(1-w)+na*w; ob=Lab[...,2]*(1-w)+nb*w
    rgb=np.clip(color.lab2rgb(np.stack([nL,oa,ob],-1)),0,1)
    out=(base if base is not None else rgba).copy()
    m=(w>0)[...,None]; out[...,:3]=np.where(m,rgb,out[...,:3]); return out
def printed(Lab, Lmin=38, Hmin=55):
    """How much a pixel is a printed number/trim (light, yellow-cream) rather than fabric."""
    H=hue_deg(Lab); return np.clip((Lab[...,0]-Lmin)/10,0,1)*np.clip((H-Hmin)/10,0,1)
def lowchroma(Lab, cmax=18, span=8, lmax=40):
    C=np.hypot(Lab[...,1],Lab[...,2]); return np.clip(1-(C-cmax)/span,0,1)*np.clip(1-(Lab[...,0]-lmax)/10,0,1)

def hue_weight(Lab, h0, tol, fade, cmin=15, cspan=10):
    H=hue_deg(Lab); C=np.hypot(Lab[...,1],Lab[...,2])
    dh=np.abs((H-h0+180)%360-180)
    return np.clip(1-(dh-tol)/fade,0,1)*np.clip((C-cmin)/cspan,0,1)
def number_mask(Lab, region, hmin=58, cmin=18, lmin=18, lmax=None):
    H=hue_deg(Lab); C=np.hypot(Lab[...,1],Lab[...,2])
    n=region&(H>hmin)&(C>cmin)&(Lab[...,0]>lmin)
    if lmax is not None: n&=Lab[...,0]<lmax
    n=morphology.remove_small_objects(n,max_size=30); return morphology.binary_closing(n,morphology.disk(2))
