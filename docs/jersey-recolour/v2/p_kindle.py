import sys; sys.path.insert(0,sys.argv[1]); from kit import *; import pickle
S=sys.argv[1]; refs=pickle.load(open(S+'/refs.pkl','rb')); T=refs['teal']
r=load('Kindlefinger'); sh=r.shape[:2]; Lab=lab(r)
face=poly_mask(sh,[[(145,92),(205,92),(216,128),(206,152),(185,146),(165,136),(148,120)]])
shirt=poly_mask(sh,[[(140,172),(140,145),(157,127),(180,110),(197,104),(215,128),(225,100),(245,90),(268,88),(292,92),(300,105),(298,130),(285,135),(288,175),(300,205),(300,258),(260,264),(215,252),(190,236),(185,190),(170,180),(160,185)]])&~poly_mask(sh,[[(178,100),(200,100),(212,125),(205,150),(190,148),(178,120)]])&~face
num=number_mask(Lab,shirt,hmin=55,cmin=15,lmin=40)
hw=hue_weight(Lab,43,10,10,8,10)
w=feathered(shirt,0,1.0)*hw*(1-feathered(num,1,0.8))
core=shirt&(hw>0.9)&~num
H=hue_deg(Lab); C=np.hypot(Lab[...,1],Lab[...,2]); L=Lab[...,0]
# orange flecks left on the shirt: small warm blobs, never the neck or the number
warm=shirt&~face&~morphology.binary_dilation(num,morphology.disk(3))&(H>44)&(H<75)&(C>22)&(L>28)
fleck=warm&~morphology.remove_small_objects(warm,max_size=40)
w=np.maximum(w,feathered(fleck,1,0.6))
out=recolour_w(r,w,core,T)
# the shorts keep their dark cloth; the orange patches on them become that cloth
shorts=poly_mask(sh,[[(165,236),(188,228),(215,232),(265,236),(300,246),(312,272),(306,300),(286,306),(256,300),(232,290),(216,300),(200,304),(186,290),(170,262)]])&~shirt
cloth=shorts&(C<14)&(L<45)
thigh=poly_mask(sh,[[(160,228),(205,228),(205,268),(160,268)]])
patch=shorts&~thigh&(C>24)&(H>30)&(H<78)&(L>30)
patch&=~morphology.remove_small_objects(patch,max_size=80)
patch=morphology.binary_dilation(patch,morphology.disk(1))&shorts
rgb8=(np.clip(out[...,:3],0,1)*255).astype(np.uint8)
filled=cv2.inpaint(np.ascontiguousarray(rgb8[...,::-1]),patch.astype(np.uint8)*255,2,cv2.INPAINT_TELEA)[...,::-1].astype(float)/255
out[...,:3]=np.where(patch[...,None],filled,out[...,:3])
save(out,S+'/Kindlefinger_teal.png'); overlay(r,w,S+'/ov_Kindlefinger.png')
compare([IMG%'Kindlefinger',S+'/ov_Kindlefinger.png',S+'/Kindlefinger_teal.png'],S+'/cmp_Kindlefinger.png',1)
