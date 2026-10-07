"""사상 2단(선별 게이트 + 경보) 규칙을 lead_time_bk npz 로 독립 재계산."""
import sys, numpy as np, warnings
warnings.filterwarnings("ignore")
NPZ = sys.argv[1]
MODE = sys.argv[2] if len(sys.argv)>2 else "slice_then_derive"
FE = ["cum1","cum1a","cum2","cum2a","cumF","cumFa","vel","vela","vtr","dv","ivfrac","ivimm"]
names = FE + [f+"_d%d"%m for m in (1,3,6) for f in FE] + [f+"_z%d"%m for m in (3,6) for f in FE]
def derive(F):
    F = np.where(np.asarray(F,float) <= -1e17, np.nan, np.asarray(F,float)); T=F.shape[1]; parts=[F]
    for m in (1,3,6):
        D=np.full_like(F,np.nan)
        if T>m: D[:,m:]=F[:,m:]-F[:,:-m]
        parts.append(D)
    for m in (3,6):
        Z=np.full_like(F,np.nan)
        for t in range(m,T):
            w=F[:,t-m:t]; mu=np.nanmean(w,1); sd=np.nanstd(w,1)
            sd=np.where(np.isfinite(sd)&(sd>1e-6),sd,np.nan); Z[:,t]=(F[:,t]-mu)/sd
        parts.append(Z)
    X=np.vstack(parts); return np.where(np.isfinite(X),X,-1e18)
def first(ok,K):
    r=0
    for i,h in enumerate(ok):
        r=r+1 if h else 0
        if r>=K: return i
    return -1
z=np.load(NPZ,allow_pickle=True); A=list(z["A"]); B=list(z["B"])
gf=[0,9]  # cum1, dv
srt=[np.sort(np.concatenate([F[f][np.isfinite(F[f])] for (_,F) in B])) for f in range(12)]
def gscore(F):
    P=[]
    for f in gf:
        v=F[f]; p=np.full(len(v),np.nan); fin=np.isfinite(v)&(v>-1e17)
        p[fin]=(np.searchsorted(srt[f],v[fin],"left")+np.searchsorted(srt[f],v[fin],"right"))/(2*len(srt[f]))
        P.append(p)
    return np.nanmean(np.vstack(P),0)
pa=np.array([np.nanmax(gscore(a["F"])) for a in A]); pb=np.array([np.nanmax(gscore(F)) for (_,F) in B])
from itertools import product
auc=np.mean([(x>y)+0.5*(x==y) for x,y in product(pa,pb)])
cand=np.unique(np.concatenate([pa,pb])); th=max(cand,key=lambda t:np.mean(pa>=t)-np.mean(pb>=t))
print(f"gate AUC={auc:.3f} Youden th={th:.5f} gate pass acc={np.sum(pa>=th)}/{len(A)} bg={np.sum(pb>=th)}/{len(B)}")
conds=[(names.index("cumF_d3"),2.296),(names.index("cum1_d1"),1.52),(names.index("cumF_z3"),1.099)]; K=2
leads=[]; viol=0
for a in A:
    j=first(np.nan_to_num(gscore(a["F"]),nan=-1)>=th,1)
    if j<0: leads.append(None); continue
    X=derive(a["F"][:,j:]) if MODE=="slice_then_derive" else derive(a["F"])[:,j:]; ok=np.ones(X.shape[1],bool)
    for f,t in conds: ok&=X[f]>=t
    k=first(ok,K)
    if k<0: leads.append(None); continue
    L=(a["t_acc"]-a["t"][j+k])*365.25; leads.append(L); print("  ",a["date"],round(L,1)); viol+= L<a["gap_d"]-0.01
d=[x for x in leads if x is not None]
print(f"alarm detect={len(d)}/{len(A)} ({100*len(d)/len(A):.1f}%) median lead={np.median(d):.1f}d min={min(d):.1f} gap-viol={viol}")
nb=0
for (t,F) in B:
    j=first(np.nan_to_num(gscore(F),nan=-1)>=th,1)
    if j<0: continue
    X=derive(F[:,j:]) if MODE=="slice_then_derive" else derive(F)[:,j:]; ok=np.ones(X.shape[1],bool)
    for f,tt in conds: ok&=X[f]>=tt
    nb+= first(ok,K)>=0
print(f"background operational FP = {nb}/{len(B)} ({100*nb/len(B):.1f}%)")
