import sys; sys.path.insert(0,sys.argv[1]); from kit import *; import pickle
S=sys.argv[1]; refs=pickle.load(open(S+'/refs.pkl','rb')); T=refs['black']
r=load('Umbrik'); sh=r.shape[:2]; Lab=lab(r)
kit=poly_mask(sh,[[(138,88),(150,72),(165,70),(180,75),(195,95),(210,110),(225,95),(240,78),(262,72),(285,76),(300,90),(306,108),(295,122),(272,126),(268,168),(285,180),(282,205),(262,208),(245,195),(215,190),(190,205),(165,205),(155,190),(170,172),(168,128),(150,122),(138,108)]])
hw=hue_weight(Lab,305,32,25,4,6)
w=feathered(kit,0,1.2)*hw
core=kit&(hw>0.9)
out=recolour_w(r,w,core,T)
save(out,S+'/Umbrik_black.png'); overlay(r,w,S+'/ov_Umbrik.png')
compare([IMG%'Umbrik',S+'/ov_Umbrik.png',S+'/Umbrik_black.png'],S+'/cmp_Umbrik.png',1)
