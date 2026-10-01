import sys; sys.path.insert(0,sys.argv[1]); from kit import *; import pickle
S=sys.argv[1]; refs=pickle.load(open(S+'/refs.pkl','rb')); T=refs['teal']
r=load('Ozul'); sh=r.shape[:2]; Lab=lab(r); C=np.hypot(Lab[...,1],Lab[...,2])
def dark_part(polys, excl, Lmax=30, Cmax=24, grow=2):
    region=poly_mask(sh,polys); ex=poly_mask(sh,excl) if excl else np.zeros(sh,bool)
    core=region&~ex&(Lab[...,0]<Lmax)&(C<Cmax)&(r[...,3]>0.5)
    core=morphology.remove_small_objects(core,max_size=40)
    reg=feathered(morphology.remove_small_holes(core,max_size=3000),grow=grow,radius=1.0)*(~ex)*feathered(region,0,1.0)
    w=reg*np.clip((Lmax+12-Lab[...,0])/12,0,1)*np.clip(1-(C-25)/15,0,1)
    return w, core
# shirt and shorts as one garment, so no seam where two feathers meet
eye=[(264+11*np.cos(t),117+11*np.sin(t)) for t in np.linspace(0,2*np.pi,24,endpoint=False)]
ws,cs=dark_part([[(160,140),(180,112),(205,105),(250,100),(300,104),(340,112),(358,150),(345,200),(302,212),(300,225),(287,246),(265,253),(240,253),(224,242),(213,222),(200,212),(185,210),(163,170)]],
                [[(207,100),(247,98),(250,125),(238,142),(213,142)],eye])
out=recolour_w(r,ws,cs,T)
wd=np.zeros_like(ws)
# the black band on his left forearm becomes slime: the arm's own greens
arm=box(sh,295,240,355,275)&(C>35)&(Lab[...,0]>35)
slime=model(Lab[arm])
band=poly_mask(sh,[[(303,226),(318,217),(338,216),(348,222),(347,238),(330,242),(310,242)]])
bcore=band&(Lab[...,0]<45)&(C<25)
wb=feathered(band,0,1.0)*np.clip(1-(C-25)/15,0,1)
out=recolour_w(r,wb,bcore,slime,base=out)
save(out,S+'/Ozul_teal.png'); overlay(r,np.maximum(np.maximum(ws,wd),wb),S+'/ov_Ozul.png')
