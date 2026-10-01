import sys; sys.path.insert(0,sys.argv[1]); from kit import *; import pickle
S=sys.argv[1]; refs=pickle.load(open(S+'/refs.pkl','rb')); T=refs['purple']
r=load('Hellguard'); sh=r.shape[:2]; Lab=lab(r)
shirt=poly_mask(sh,[[(134,184),(150,176),(172,172),(200,178),(222,182),(250,176),(282,168),(305,178),(318,200),(312,235),(300,258),(250,264),(185,262),(155,252),(146,230),(136,205)]])
shorts=poly_mask(sh,[[(118,266),(150,258),(300,258),(330,268),(322,300),(300,312),(262,310),(245,318),(215,320),(200,310),(170,302),(130,292),(115,282)]])&~shirt
lc=lowchroma(Lab,20,10,35)
# red flecks on the shorts: small red blobs, not the skin they sit beside
red=shorts&(lc<0.5)
fleck=red&~morphology.remove_small_objects(red,max_size=60)
wd=np.maximum(lc,feathered(fleck,1,0.7))*feathered(shorts,0,1.0)
H=hue_deg(Lab); C=np.hypot(Lab[...,1],Lab[...,2])
num=shirt&(H>58)&(C>18)&(Lab[...,0]>18)
num=morphology.remove_small_objects(num,max_size=30); num=morphology.binary_closing(num,morphology.disk(2))
ws=feathered(shirt,0,1.2)*(1-feathered(num,1,0.8))
out=recolour_w(r,ws,shirt&~num,T)
out=recolour_w(r,wd,shorts&(lc>0.8),T,base=out)
save(out,S+'/Hellguard_purple.png'); overlay(r,np.maximum(ws,wd),S+'/ov_Hellguard.png')
compare([IMG%'Hellguard',S+'/ov_Hellguard.png',S+'/Hellguard_purple.png'],S+'/cmp_Hellguard.png',1)
