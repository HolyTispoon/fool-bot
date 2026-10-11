"""python3 generic.py S Name target poly_json [exclude_json] [key h0 h1 smin vmin]"""
import sys, json; sys.path.insert(0,sys.argv[1]); from kit import *; import pickle
S,name,target=sys.argv[1:4]; polys=json.loads(sys.argv[4]); excl=json.loads(sys.argv[5]) if len(sys.argv)>5 else []
key=[float(v) for v in sys.argv[6].split(',')] if len(sys.argv)>6 else [150,205,0.3,0.15]
refs=pickle.load(open(S+'/refs.pkl','rb'))
r=load(name); sh=r.shape[:2]
region=poly_mask(sh,polys); ex=poly_mask(sh,excl) if excl else np.zeros(sh,bool)
core=hue_key(r,*key)&region&~ex
core=morphology.remove_small_objects(core,max_size=60)
reg=feathered(morphology.remove_small_holes(core,max_size=3000),grow=4,radius=1.0)*(~ex)*feathered(region,0,1.0)
out,w=recolour2(r,reg,core,refs[target])
save(out,f'{S}/{name}_{target}.png'); overlay(r,w,f'{S}/ov_{name}.png')
compare([IMG%name,f'{S}/ov_{name}.png',f'{S}/{name}_{target}.png'],f'{S}/cmp_{name}.png',2)
