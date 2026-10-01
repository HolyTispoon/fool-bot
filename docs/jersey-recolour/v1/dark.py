"""python3 dark.py S Name target poly_json [exclude_json] [Lmax]  -- black kit source"""
import sys, json; sys.path.insert(0,sys.argv[1]); from kit import *; import pickle
S,name,target=sys.argv[1:4]; polys=json.loads(sys.argv[4]); excl=json.loads(sys.argv[5]) if len(sys.argv)>5 else []
Lmax=float(sys.argv[6]) if len(sys.argv)>6 else 26
CMAX=float(sys.argv[7]) if len(sys.argv)>7 else 18
refs=pickle.load(open(S+'/refs.pkl','rb'))
r=load(name); sh=r.shape[:2]; Lab=lab(r); C=np.hypot(Lab[...,1],Lab[...,2])
region=poly_mask(sh,polys); ex=poly_mask(sh,excl) if excl else np.zeros(sh,bool)
core=region&~ex&(Lab[...,0]<Lmax)&(C<CMAX)&(r[...,3]>0.5)
core=morphology.remove_small_objects(core,max_size=40)
reg=feathered(morphology.remove_small_holes(core,max_size=3000),grow=2,radius=1.0)*(~ex)*feathered(region,0,1.0)
out,w=recolour2(r,reg,core,refs[target],mode='dark',dark_L=Lmax)
save(out,f'{S}/{name}_{target}.png'); overlay(r,w,f'{S}/ov_{name}.png')
compare([IMG%name,f'{S}/ov_{name}.png',f'{S}/{name}_{target}.png'],f'{S}/cmp_{name}.png',2)
