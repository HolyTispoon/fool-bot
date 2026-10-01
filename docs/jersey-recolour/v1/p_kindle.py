import sys; sys.path.insert(0,sys.argv[1]); from kit import *; import pickle
S=sys.argv[1]; refs=pickle.load(open(S+'/refs.pkl','rb')); T=refs['teal']
r=load('Kindlefinger'); sh=r.shape[:2]; Lab=lab(r)
shirt=poly_mask(sh,[[(140,172),(140,145),(157,127),(180,110),(197,104),(215,128),(225,100),(245,90),(268,88),(292,92),(300,105),(298,130),(285,135),(288,175),(300,205),(300,258),(260,264),(215,252),(190,236),(185,190),(170,180),(160,185)]])&~poly_mask(sh,[[(178,100),(200,100),(212,125),(205,150),(190,148),(178,120)]])
num=number_mask(Lab,shirt,hmin=55,cmin=15,lmin=40)
hw=hue_weight(Lab,41,6,10,8,10)
w=feathered(shirt,0,1.0)*hw*(1-feathered(num,1,0.8))
core=shirt&(hw>0.9)&~num
out=recolour_w(r,w,core,T)
save(out,S+'/Kindlefinger_teal.png'); overlay(r,w,S+'/ov_Kindlefinger.png')
compare([IMG%'Kindlefinger',S+'/ov_Kindlefinger.png',S+'/Kindlefinger_teal.png'],S+'/cmp_Kindlefinger.png',1)
