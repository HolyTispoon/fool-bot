import sys; sys.path.insert(0,sys.argv[1]); from kit import *; import pickle
S=sys.argv[1]; refs=pickle.load(open(S+'/refs.pkl','rb')); T=refs['teal']
r=load('Zenith'); sh=r.shape[:2]; Lab=lab(r)
kit=poly_mask(sh,[[(128,72),(140,60),(165,58),(190,55),(205,60),(228,62),(248,62),(268,70),(272,88),(252,95),(240,110),(245,140),(240,158),(250,160),(256,190),(248,220),(228,234),(200,232),(186,205),(174,182),(168,160),(172,140),(170,110),(160,95),(140,95),(130,88)]])
kit&=~poly_mask(sh,[[(185,0),(242,0),(242,62),(228,68),(205,58),(185,40)]])
hw=hue_weight(Lab,308,32,25,8,10)
num=kit&(Lab[...,0]>70)&(np.hypot(Lab[...,1],Lab[...,2])<25)
num=morphology.binary_dilation(morphology.remove_small_objects(num,max_size=10),morphology.disk(1))
w=feathered(kit,0,1.0)*hw*(1-feathered(num,0,0.7))
core=kit&(hw>0.9)&~num
out=recolour_w(r,w,core,T)
save(out,S+'/Zenith_teal.png'); overlay(r,w,S+'/ov_Zenith.png')
compare([IMG%'Zenith',S+'/ov_Zenith.png',S+'/Zenith_teal.png'],S+'/cmp_Zenith.png',1)
