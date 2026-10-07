import os
import numpy as np, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
plt.rcParams.update({"font.size":11,"axes.spines.top":False,"axes.spines.right":False,"axes.edgecolor":"#52514e","text.color":"#0b0b0b","axes.labelcolor":"#52514e","xtick.color":"#52514e","ytick.color":"#52514e"})
fig,ax=plt.subplots(1,2,figsize=(13,5.2),gridspec_kw={"width_ratios":[1.25,1]},facecolor="#fcfcfb")
for a in ax: a.set_facecolor("#fcfcfb")
lab=["EMSR884 Damaged\n(n=78)","EMSR884 Possibly\n(n=12)","Optical AI: destroyed\n(n=151)","Optical AI: partial\n(n=2,742)","Optical AI: minor/none\n(n=27,665)","All AOI pixels\n(70.0 km²)"]
val=[84.6,91.7,84.8,63.6,62.4,37.2]
col=["#2a78d6"]*3+["#86b6ef"]*2+["#c3c2b7"]
y=np.arange(len(val))[::-1]
ax[0].barh(y,val,color=col,height=0.62); ax[0].set_ylim(-0.8,len(val)-0.4)
for yi,v in zip(y,val): ax[0].text(v+1,yi,f"{v:.1f}%",va="center",fontsize=10)
ax[0].axvline(62.4,color="#52514e",ls="--",lw=1); ax[0].text(63.5,-0.55,"building baseline 62.4%",fontsize=9,color="#52514e",ha="left")
ax[0].set_yticks(y); ax[0].set_yticklabels(lab,fontsize=9.5); ax[0].set_xlim(0,105)
ax[0].set_xlabel("Share inside SAR change zone (ΔCoh ≥ 0.1, %)")
ax[0].set_title("A. CCD hit rate vs. baseline (Catia La Mar AOI)",loc="left",fontsize=12)
z=np.load("left_vs_ems.npz"); o=z["ours"]; e=z["ems"]; m=np.isfinite(o)&np.isfinite(e)
yy,xx=np.mgrid[0:o.shape[0],0:o.shape[1]]
def dr(a):
    A=np.c_[xx[m],yy[m],np.ones(m.sum())]; c,*_=np.linalg.lstsq(A,a[m],rcond=None); return a[m]-A@c
od,ed=dr(o)*100,dr(e)*100; r=np.corrcoef(od,ed)[0,1]
hb=ax[1].hexbin(ed,od,gridsize=70,extent=(-20,20,-50,50),bins="log",cmap="Blues",mincnt=1)
ax[1].plot([-20,20],[-20,20],color="#eb6834",lw=1.5,label="1:1")
ax[1].set_xlabel("Copernicus EMS ground-movement LOS (cm, plane removed)"); ax[1].set_ylabel("Own 1-day DInSAR LOS (cm, plane removed)")
ax[1].set_title(f"B. Own DInSAR vs. EMS reference  r = {r:.2f}",loc="left",fontsize=12)
ax[1].text(-19,44,"raw (before plane removal) r = 0.11\nown residual std 13.6 cm vs EMS 5.1 cm",fontsize=9,color="#52514e",va="top")
ax[1].legend(loc="lower right",frameon=False)
fig.tight_layout(); fig.savefig("validation.png",dpi=130,facecolor=fig.get_facecolor())
print("r",r)
