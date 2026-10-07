import os
import numpy as np
z=np.load("left_vs_ems.npz"); o=z["ours"]; e=z["ems"]; m=np.isfinite(o)&np.isfinite(e)
yy,xx=np.mgrid[0:o.shape[0],0:o.shape[1]]
for nm,arr in [("ours",o),("ems",e)]:
    A=np.c_[xx[m],yy[m],np.ones(m.sum())]; c,*_=np.linalg.lstsq(A,arr[m],rcond=None)
    globals()[nm+"_d"]=arr[m]-A@c; print(nm,"plane coef (m/px)",c[:2],"resid std %.3f m"%globals()[nm+"_d"].std())
print("평면 램프 제거 후 r = %.3f"%np.corrcoef(ours_d,ems_d)[0,1])
# 공간 저주파만 비교 (32x32 블록 평균)
def blk(a,k=32):
    h,w=(a.shape[0]//k)*k,(a.shape[1]//k)*k; return np.nanmean(a[:h,:w].reshape(h//k,k,w//k,k),axis=(1,3))
ob,eb=blk(np.where(m,o,np.nan)),blk(np.where(m,e,np.nan)); mb=np.isfinite(ob)&np.isfinite(eb)
print("블록평균(~4km) r = %.3f, n=%d"%(np.corrcoef(ob[mb],eb[mb])[0,1],mb.sum()))
