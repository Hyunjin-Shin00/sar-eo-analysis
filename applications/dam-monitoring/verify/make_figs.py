#!/usr/bin/env python3
# Handoff figures for usoi-dam, rendered directly from MintPy h5 (read-only on source).
import os
ROOT=os.environ.get('DATA_ROOT','<DATA_ROOT>')  # dir containing SBAS/ and sentinel1/
import numpy as np, h5py, datetime, os, io
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm, LightSource
from PIL import Image
B=ROOT+'/SBAS'; OUT=os.environ.get('OUT_DIR','./img'); os.makedirs(OUT,exist_ok=True)
AOI=(38.1559,38.3414,72.5162,72.7164); DAM=(38.271,72.607); PT=(38.2574,72.6091); REF=(38.282375,72.607)
plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
INK='#222'; MUTED='#666'

def save(fig,name):
    buf=io.BytesIO(); fig.savefig(buf,dpi=150,bbox_inches='tight',facecolor='white'); plt.close(fig)
    im=Image.open(buf).convert('RGB')
    if im.width>1600: im=im.resize((1600,round(im.height*1600/im.width)),Image.LANCZOS)
    im.save(f'{OUT}/{name}','WEBP',quality=84,method=5); print(name,im.size,os.path.getsize(f'{OUT}/{name}'))

def geo(track,ts=None):
    G=f'{B}/{track}/mintpy/geo'
    f=h5py.File(f'{G}/geo_velocity.h5','r'); a=f.attrs
    g=(float(a['Y_FIRST']),float(a['X_FIRST']),float(a['Y_STEP']),float(a['X_STEP']))
    v=f['velocity'][:]*1000
    tc=h5py.File(f'{G}/geo_temporalCoherence.h5','r')['temporalCoherence'][:]
    hg=h5py.File(f'{G}/geo_geometryRadar.h5','r')['height'][:].astype(float)
    return g,v,tc,hg
def ext(g,shape): y0,x0,dy,dx=g; return [x0,x0+dx*shape[1],y0+dy*shape[0],y0]
def rc(g,la,lo): y0,x0,dy,dx=g; return int(round((la-y0)/dy)),int(round((lo-x0)/dx))
def wmask(hg,g):
    y0,x0,dy,dx=g; mlat=abs(dy)*111320; mlon=abs(dx)*111320*np.cos(np.deg2rad(y0))
    gy,gx=np.gradient(hg,mlat,mlon); s=np.degrees(np.arctan(np.hypot(gy,gx))); return (s<2)&(hg<3330)
def hill(hg,g):
    y0,x0,dy,dx=g; h=np.where(np.isfinite(hg)&(hg!=0),hg,np.nan); h=np.where(np.isnan(h),np.nanmedian(h),h)
    return LightSource(315,40).hillshade(h,vert_exag=1,dx=abs(dx)*111320*np.cos(np.deg2rad(y0)),dy=abs(dy)*111320)
def aoibox(ax):
    S,N,W,E=AOI; ax.plot([W,E,E,W,W],[S,S,N,N,S],color='k',lw=1.2,ls='--')

# ---------- DSC corrected field (reproduces export_dsc_corrected.py) ----------
gD,vD,tcD,hD=geo('DSC'); watD=wmask(hD,gD)
rel=np.isfinite(vD)&(vD!=0)&(tcD>0.5)&(~watD); hh=hD[rel]; vv=vD[rel]; keep=np.ones(hh.size,bool)
for _ in range(3):
    a1,b1=np.polyfit(hh[keep],vv[keep],1); res=vv-(a1*hh+b1); keep=np.abs(res)<2*np.std(res[keep])
vc=vD-a1*hD; r,c=rc(gD,*REF); vc=vc-vc[r,c]
valD=np.isfinite(vD)&(vD!=0)&(tcD>0.3)&(~watD)

# 00-key: corrected DSC LOS over hillshade, AOI zoom
S,N,W,E=AOI
r0,c0=rc(gD,N,W); r1,c1=rc(gD,S,E); sl=(slice(r0,r1),slice(c0,c1))
gs=(gD[0]+gD[2]*r0,gD[1]+gD[3]*c0,gD[2],gD[3])
fig,ax=plt.subplots(figsize=(7.2,8.6))
ax.imshow(hill(hD,gD)[sl],cmap='gray',extent=ext(gs,vc[sl].shape),vmin=0,vmax=1)
lake=watD[sl]; ax.imshow(np.where(lake,1,np.nan),cmap='Blues',vmin=0,vmax=1.6,extent=ext(gs,lake.shape),alpha=.75)
m=np.where(valD[sl],vc[sl],np.nan)
im=ax.imshow(m,cmap='RdBu_r',norm=TwoSlopeNorm(vmin=-30,vcenter=0,vmax=30),extent=ext(gs,m.shape),alpha=.85,interpolation='nearest')
ax.plot(DAM[1],DAM[0],marker='v',ms=12,mfc='#ffd400',mec='k'); ax.annotate('Usoi dam',(DAM[1],DAM[0]),xytext=(8,6),textcoords='offset points',fontweight='bold')
ax.plot(REF[1],REF[0],marker='s',ms=7,mfc='w',mec='k'); ax.annotate('ref (stable rock)',(REF[1],REF[0]),xytext=(8,4),textcoords='offset points',fontsize=8)
ax.text(72.655,38.215,'Lake Sarez',color='#08306b',fontsize=10,style='italic')
cb=fig.colorbar(im,ax=ax,shrink=.7,extend='both'); cb.set_label('DSC LOS velocity (mm/yr, + = toward satellite)')
ax.set_aspect(1/np.cos(np.deg2rad(38.25)))
ax.set_xlabel('Longitude (°E)'); ax.set_ylabel('Latitude (°N)')
ax.set_title('Sentinel-1 DSC SBAS 2019-01 – 2026-06 (223 dates)\nERA5 + empirical height detrend, tcoh>0.3, lake masked',fontsize=10,loc='left')
save(fig,'00-key.webp')

# ---------- 02: temporal coherence ASC vs DSC ----------
gA,vA,tcA,hA=geo('ASC')
fig,axs=plt.subplots(1,2,figsize=(13,5.2))
for ax,(t,g,tc,hg) in zip(axs,[('ASC (track ascending, 97 dates kept)',gA,tcA,hA),('DSC (track descending, 223 dates)',gD,tcD,hD)]):
    ax.imshow(hill(hg,g),cmap='gray',extent=ext(g,tc.shape),vmin=0,vmax=1)
    t2=np.where(np.isfinite(hg)&(hg!=0),tc,np.nan)
    im=ax.imshow(t2,cmap='viridis',vmin=0,vmax=1,extent=ext(g,tc.shape),alpha=.85)
    aoibox(ax); ax.plot(DAM[1],DAM[0],'v',ms=9,mfc='#ffd400',mec='k')
    ax.set_title(t,loc='left',fontsize=10); ax.set_xlabel('Longitude (°E)')
axs[0].set_ylabel('Latitude (°N)')
cb=fig.colorbar(im,ax=axs,shrink=.85); cb.set_label('SBAS temporal coherence')
fig.suptitle('Temporal coherence: ASC collapses inside the AOI (dashed) — mean 0.004 vs DSC usable',x=0.42,y=0.98,fontsize=11)
save(fig,'02-temporal-coherence.webp')

# ---------- 03: seasonal 12-day coherence ----------
import collections
fig,ax=plt.subplots(figsize=(8,4))
mon='J F M A M J J A S O N D'.split()
for t,col,mk in [('ASC','#1b7837','o'),('DSC','#2166ac','s')]:
    rows=[l.split() for l in open(f'{B}/{t}/mintpy/coherenceSpatialAvg.txt') if not l.startswith('#') and l.strip()]
    bym=collections.defaultdict(list)
    for rr_ in rows:
        if int(rr_[2])<=12 and rr_[1]!='nan': bym[int(rr_[0][4:6])].append(float(rr_[1]))
    y=[np.mean(bym[M]) for M in range(1,13)]
    ax.plot(range(1,13),y,marker=mk,ms=7,lw=2,color=col,label=f'{t} (12-day pairs)')
    ax.annotate(t,(12,y[-1]),xytext=(6,0),textcoords='offset points',color=INK,va='center')
ax.set_xticks(range(1,13)); ax.set_xticklabels(mon); ax.set_ylim(0.3,0.8)
ax.set_ylabel('scene-mean coherence'); ax.set_xlabel('month of first acquisition'); ax.grid(axis='y',color='#ddd',lw=.6)
ax.legend(frameon=False,loc='upper left')
ax.set_title('Seasonal coherence (12-day pairs): Jan–Apr 0.40–0.56, Jun–Sep 0.63–0.74',loc='left',fontsize=10)
save(fig,'03-seasonal-coherence.webp')

# ---------- 04: velocity vs elevation, before/after ----------
vmsk_hc=None
fig,axs=plt.subplots(1,2,figsize=(12,4.6),sharey=True)
relE=np.isfinite(vD)&(vD!=0)&(tcD>0.7)&(~watD)
for ax,(lab,vel) in zip(axs,[('ERA5-corrected MintPy velocity',vD),('+ empirical height detrend, re-referenced',vc)]):
    x=hD[relE]; y=vel[relE]
    ax.hexbin(x,y,gridsize=90,bins='log',cmap='Greys',extent=(x.min(),x.max(),-150,100),mincnt=1)
    cc=np.corrcoef(x,y)[0,1]; s,b=np.polyfit(x,y,1); xx=np.array([x.min(),x.max()])
    ax.plot(xx,s*xx+b,color='#b2182b',lw=2)
    ax.set_title(f'{lab}\nr = {cc:.2f}, slope = {s:.4f} mm/yr/m, median = {np.median(y):.1f}',loc='left',fontsize=9.5)
    ax.set_xlabel('elevation (m, ellipsoid)'); ax.set_ylim(-150,100); ax.axhline(0,color=MUTED,lw=.6)
axs[0].set_ylabel('DSC LOS velocity (mm/yr)')
fig.suptitle(f'Topography-correlated tropospheric residual (DSC, tcoh>0.7, {relE.sum():,} px)',x=0.35,y=1.04,fontsize=11)
save(fig,'04-tropo-vs-elevation.webp')

# ---------- 05: decomposition attempt (existing product, re-plotted) ----------
D=f'{B}/DECOMP'
def L(f):
    h=h5py.File(f'{D}/{f}','r'); a=h.attrs; v=h['velocity'][:]*1000
    g=(float(a['Y_FIRST']),float(a['X_FIRST']),float(a['Y_STEP']),float(a['X_STEP']))
    return np.where((v==0)|~np.isfinite(v),np.nan,v),g
gh=h5py.File(f'{D}/DSC_geom_geo.h5','r')['height'][:].astype(float)
fig,axs=plt.subplots(1,3,figsize=(15,4.4))
for ax,(t,f) in zip(axs,[('ASC LOS (2021-09 – 2024-11)','ASC_vel_geo.h5'),('Vertical (up +)','up.h5'),('East–west (east +)','hz.h5')]):
    v,g=L(f); ax.imshow(hill(gh,g),cmap='gray',extent=ext(g,v.shape),vmin=0,vmax=1)
    im=ax.imshow(v,cmap='RdBu_r',norm=TwoSlopeNorm(vmin=-40,vcenter=0,vmax=40),extent=ext(g,v.shape),interpolation='nearest')
    ax.plot(DAM[1],DAM[0],'v',ms=9,mfc='#ffd400',mec='k'); ax.set_title(t,loc='left',fontsize=10)
    ax.text(0.02,0.95,f'{int(np.isfinite(v).sum()):,} px',transform=ax.transAxes,fontsize=8,bbox=dict(fc='white',lw=0,alpha=.8))
    ax.set_xlabel('Longitude (°E)')
cb=fig.colorbar(im,ax=axs,shrink=.85,extend='both'); cb.set_label('mm/yr')
fig.suptitle('ASC+DSC decomposition: only 23,444 px (7.1 % of grid) overlap, all south of the dam — no vertical/E–W estimate at the dam',x=0.43,y=0.95,fontsize=11)
save(fig,'05-decomposition-coverage.webp')

# ---------- 06: point time series ----------
G=f'{B}/DSC/mintpy/geo'; ts=h5py.File(f'{G}/geo_timeseries_ERA5_ramp_demErr.h5','r')
dates=[datetime.datetime.strptime(d.decode(),'%Y%m%d') for d in ts['date'][:]]
pr,pc=rc(gD,*PT); rr2,cc2=rc(gD,*DAM)
fig,ax=plt.subplots(figsize=(10,4))
def yr(d): return d.year+(d.timetuple().tm_yday-1)/365.25
t=np.array([yr(d) for d in dates])
for (la,lo),lab,col in [(PT,'slope point 38.2574N 72.6091E','#2166ac'),(DAM,'dam crest area 38.271N 72.607E','#b35806')]:
    r_,c_=rc(gD,la,lo); d=ts['timeseries'][:,r_,c_]*1000; d=d-d[0]
    k=np.polyfit(t-t[0],d,1)
    ax.plot(dates,d,'o',ms=3,color=col,alpha=.7)
    ax.plot(dates,np.polyval(k,t-t[0]),'-',lw=2,color=col,label=f'{lab}: {k[0]:+.1f} mm/yr (tcoh {tcD[r_,c_]:.2f})')
ax.axhline(0,color=MUTED,lw=.6); ax.set_ylabel('cumulative DSC LOS (mm)'); ax.grid(axis='y',color='#ddd',lw=.6)
ax.legend(frameon=False,fontsize=9,loc='upper left')
ax.set_title('DSC LOS time series (ERA5+ramp+DEM-error corrected; relative to MintPy reference, no height detrend)',loc='left',fontsize=10)
save(fig,'06-point-timeseries.webp')

# ---------- 01: workflow ----------
fig,ax=plt.subplots(figsize=(13,3.2)); ax.axis('off')
steps=[('Sentinel-1 IW SLC','ASC 140 scenes\nDSC 225 scenes\nPOEORB orbits'),
       ('ISCE2 topsStack','IW2 only\ngeometry coreg\n3x9 looks, snaphu'),
       ('Network','ASC 550 / DSC 433\nkeep <=24 days\ncoherence >= 0.3'),
       ('MintPy SBAS','per-track ref pixel\nno unwrap-error fix\ntcoh >= 0.3'),
       ('Troposphere','height_corr -> ERA5\n+ empirical\nheight detrend'),
       ('Products','DSC LOS velocity\nASC+DSC up / E-W\n(partial)')]
n=len(steps)
for i,(h,b) in enumerate(steps):
    x=i/n+0.005
    ax.add_patch(plt.Rectangle((x,0.2),1/n-0.03,0.6,transform=ax.transAxes,fc='#f2f5fa',ec='#2166ac',lw=1.2))
    ax.text(x+(1/n-0.03)/2,0.68,h,ha='center',va='center',fontweight='bold',fontsize=10,transform=ax.transAxes)
    ax.text(x+(1/n-0.03)/2,0.38,b,ha='center',va='center',fontsize=9,color=INK,transform=ax.transAxes)
    if i<n-1: ax.annotate('',xy=((i+1)/n+0.003,0.5),xytext=(x+1/n-0.03,0.5),xycoords='axes fraction',arrowprops=dict(arrowstyle='->',color=MUTED,lw=1.4))
save(fig,'01-workflow.webp')
