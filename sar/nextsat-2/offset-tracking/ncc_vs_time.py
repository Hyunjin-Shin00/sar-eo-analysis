"""모든 오프셋 트래킹 쌍의 NCC 중앙값 vs 시간차 — 탈상관 진단 종합 그래프."""
import json, numpy as np, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
OT="<DATA_ROOT>/N2_InSAR/N2/taean_OT/"
AL=["n2off_0511x0515","n2off_0614x0706","n2off_0515x0614","n2off_0511x0706"]
AR=["n2off_0402x0406","n2off_0518x0529","n2off_0402x0613"]
S1=["s1off_0519x0613"]
def load(lst):
    out=[]
    for p in lst:
        try: d=json.load(open(OT+p+"_summary.json")); out.append((d["days"],d["ncc_median"],d["az_1sigma_m"],d["rg_1sigma_m"],p))
        except: pass
    return sorted(out)
al=load(AL); ar=load(AR); s1=load(S1)
fig,ax=plt.subplots(1,2,figsize=(15,5.6))
for grp,mk,col,lab in [(al,'o','tab:blue','N2 A_L (asc, left-look)'),(ar,'s','tab:red','N2 A_R (asc, right-look)')]:
    d=[x[0] for x in grp]; n=[x[1] for x in grp]; ax[0].plot(d,n,mk+'-',color=col,label=lab,ms=9)
    for x in grp: ax[0].annotate("%dd"%x[0],(x[0],x[1]),textcoords="offset points",xytext=(0,7),fontsize=8,ha='center')
for x in s1: ax[0].plot(x[0],x[1],'*',color='tab:green',ms=16,label='S1 C-band (25d)')
ax[0].axhspan(0.06,0.10,color='0.85',zorder=0); ax[0].text(40,0.10,"N2 noise floor ~0.08",fontsize=9,color='0.4')
ax[0].axhline(0.4,ls='--',color='green',lw=1); ax[0].text(3,0.42,"'trackable' threshold ~0.4",fontsize=9,color='green')
ax[0].set_xlabel("temporal baseline (days)"); ax[0].set_ylabel("NCC median (match quality)")
ax[0].set_title("Match quality vs time — flat ~0.08 for all N2 pairs\n(decorrelation already total at 4 days, any geometry)")
ax[0].set_ylim(0,0.5); ax[0].legend(fontsize=9); ax[0].grid(alpha=.3)
# 우: 방위/거리 잡음 1sigma
for grp,col,lab in [(al,'tab:blue','A_L'),(ar,'tab:red','A_R')]:
    d=[x[0] for x in grp]; ax[1].plot(d,[x[2] for x in grp],'o-',color=col,label=lab+" azimuth 1σ",ms=7)
    ax[1].plot(d,[x[3] for x in grp],'s--',color=col,alpha=.6,label=lab+" range 1σ",ms=6)
ax[1].axhspan(0,1,color='honeydew',zorder=0); ax[1].text(30,0.5,"expected dune motion (<~1m/月)",fontsize=9,color='green')
ax[1].set_xlabel("temporal baseline (days)"); ax[1].set_ylabel("offset noise 1σ (m)")
ax[1].set_title("Noise floor (1σ) — all >> plausible dune signal"); ax[1].legend(fontsize=8); ax[1].grid(alpha=.3)
plt.suptitle("Taean dune — N2/S1 amplitude offset tracking: match quality & noise vs temporal baseline (8 pairs)",fontsize=12)
plt.tight_layout(); plt.savefig(OT+"OT_ncc_vs_time.png",dpi=115); print("saved OT_ncc_vs_time.png")
