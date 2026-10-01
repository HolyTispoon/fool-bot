import sys; sys.path.insert(0,sys.argv[1]); from kit import *; import pickle
S=sys.argv[1]; refs=pickle.load(open(S+'/refs.pkl','rb'))
r=load('Quantor'); sh=r.shape[:2]
region=poly_mask(sh,[[(118,50),(160,38),(250,45),(300,95),(300,150),(215,178),(150,178),(112,150),(118,110)]])
lens=poly_mask(sh,[[(118,50),(146,50),(146,78),(118,78)],[(112,155),(130,147),(150,145),(165,147),(175,153),(180,175),(150,178),(115,175)]])
core=hue_key(r,150,205,0.3,0.15)&region&~lens
core=morphology.remove_small_objects(core,max_size=60)
reg=feathered(morphology.remove_small_holes(core,max_size=3000),grow=4,radius=1.0)*(~lens)
out,w=recolour2(r,reg,core,refs['purple'])
save(out,S+'/Quantor_purple.png'); overlay(r,w,S+'/ov_Quantor.png')
compare(['d12ball/images/player_images/Quantor.png',S+'/ov_Quantor.png',S+'/Quantor_purple.png'],S+'/cmp_Quantor.png',2)
