import sys; sys.path.insert(0,sys.argv[1]); from kit import *; import pickle
S=sys.argv[1]; refs=pickle.load(open(S+'/refs.pkl','rb')); T=refs['purple']
r=load('Hellguard'); sh=r.shape[:2]; Lab=lab(r)
H=hue_deg(Lab); C=np.hypot(Lab[...,1],Lab[...,2]); L=Lab[...,0]
shirt=poly_mask(sh,[[(134,184),(150,176),(172,172),(200,178),(222,182),(250,176),(282,168),(305,178),(318,200),(312,235),(300,258),(250,264),(185,262),(155,252),(146,230),(136,205)]])
# the sleeves: under each shoulder pad, down to the leather band
sleeves=poly_mask(sh,[[(150,176),(140,180),(118,188),(95,190),(62,200),(60,212),(80,210),(100,212),(115,220),(130,235),(146,245),(146,230),(136,205),(134,184)],
                      [(305,178),(282,168),(300,170),(330,177),(360,171),(385,164),(398,174),(390,184),(365,182),(345,190),(330,200),(318,210),(312,235),(318,200)]])&~shirt
# the collar: between the chin and the shirt, dark fabric not skin
neck=poly_mask(sh,[[(165,166),(200,168),(240,166),(272,160),(286,168),(250,177),(222,183),(200,179),(172,173)]])&~shirt
red=np.clip(1-(H-52)/8,0,1)*np.clip((C-12)/8,0,1)
num=shirt&(H>58)&(C>18)&(L>18)
num=morphology.remove_small_objects(num,max_size=30); num=morphology.binary_closing(num,morphology.disk(2))
ws=feathered(shirt,0,1.2)*(1-feathered(num,1,0.8))
ws=np.maximum(ws,feathered(sleeves,0,1.0)*red)
ws=np.maximum(ws,feathered(neck,0,1.0)*np.clip((40-L)/10,0,1)*red)
out=recolour_w(r,ws,shirt&~num,T)
shorts=poly_mask(sh,[[(118,262),(150,255),(300,255),(338,265),(338,274),(312,274),(288,283),(270,298),(258,318),(240,320),(215,322),(198,318),(185,305),(165,290),(140,280),(116,272)]])&~shirt
lc=lowchroma(Lab,16,8,35)
rd=shorts&(lc<0.5)
fleck=rd&~morphology.remove_small_objects(rd,max_size=60)
wd=np.maximum(lc,feathered(fleck,1,0.7))*feathered(shorts,0,1.0)
out=recolour_w(r,wd,shorts&(lc>0.8),T,base=out)
save(out,S+'/Hellguard_purple.png'); overlay(r,np.maximum(ws,wd),S+'/ov_Hellguard.png')
