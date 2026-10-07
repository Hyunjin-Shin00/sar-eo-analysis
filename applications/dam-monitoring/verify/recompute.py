#!/usr/bin/env python3
# Independent re-computation of Usoi Dam SBAS numbers from MintPy h5 (read-only).
import os
ROOT=os.environ.get('DATA_ROOT','<DATA_ROOT>')  # dir containing SBAS/ and sentinel1/
import numpy as np, h5py, json, datetime
B=ROOT+'/SBAS'
D=f'{B}/DECOMP'
AOI=(38.1559, 38.3414, 72.5162, 72.7164)
DAM=(38.271, 72.607)          # plot_decomp.py dam marker
PT=(38.2574, 72.6091)
REF=(38.282375, 72.607)

def grid(f):
    a=h5py.File(f,'r').attrs
    return float(a['Y_FIRST']),float(a['X_FIRST']),float(a['Y_STEP']),float(a['X_STEP'])
def rc(g,la,lo): y0,x0,dy,dx=g; return int(round((la-y0)/dy)),int(round((lo-x0)/dx))
def aoi_slice(g,shape):
    y0,x0,dy,dx=g; S,N,W,E=AOI
    r0,r1=max(0,int(round((N-y0)/dy))),min(shape[0],int(round((S-y0)/dy)))
    c0,c1=max(0,int(round((W-x0)/dx))),min(shape[1],int(round((E-x0)/dx)))
    return slice(r0,r1),slice(c0,c1)
def stats(x):
    x=x[np.isfinite(x)]
    return dict(n=int(x.size), median=round(float(np.median(x)),2), p2=round(float(np.percentile(x,2)),1),
                p98=round(float(np.percentile(x,98)),1), std=round(float(np.std(x)),1))
def water_mask(hgt,g):
    y0,x0,dy,dx=g
    mlat=abs(dy)*111320.0; mlon=abs(dx)*111320.0*np.cos(np.deg2rad(y0))
    gy,gx=np.gradient(hgt,mlat,mlon); slope=np.degrees(np.arctan(np.hypot(gy,gx)))
    return (slope<2.0)&(hgt<3330), slope
out={}

# ---------- 1. ASC (AOI-referenced rerun 07-22) ----------
G=f'{B}/ASC/mintpy/geo'; g=grid(f'{G}/geo_velocity.h5')
v=h5py.File(f'{G}/geo_velocity.h5','r')['velocity'][:]*1000
tc=h5py.File(f'{G}/geo_temporalCoherence.h5','r')['temporalCoherence'][:]
sc=h5py.File(f'{G}/geo_avgSpatialCoh.h5','r')['coherence'][:]
hgt=h5py.File(f'{G}/geo_geometryRadar.h5','r')['height'][:].astype(float)
sh=h5py.File(f'{G}/geo_geometryRadar.h5','r')['shadowMask'][:]
rs,cs=aoi_slice(g,v.shape); fin=np.isfinite(hgt[rs,cs])&(hgt[rs,cs]!=0)
wat,_=water_mask(hgt,g); land=fin&~wat[rs,cs]
o=dict(aoi_px=int(fin.sum()),
       tcoh_mean_aoi=round(float(np.nanmean(tc[rs,cs][fin])),4),
       tcoh_median_aoi=round(float(np.nanmedian(tc[rs,cs][fin])),4),
       spcoh_mean_aoi=round(float(np.nanmean(sc[rs,cs][fin])),3),
       spcoh_land_frac_gt03=round(float(np.mean(sc[rs,cs][land]>0.3)),3),
       shadow_frac_aoi=round(float(np.mean(sh[rs,cs][fin]>0)),3),
       frac_tcoh_gt03=round(float(np.mean(tc[rs,cs][fin]>0.3)),4),
       frac_tcoh_gt005=round(float(np.mean(tc[rs,cs][fin]>0.05)),4))
fw=np.isfinite(tc)&(hgt!=0)
o['scene_frac_tcoh_gt03']=round(float(np.mean(tc[fw]>0.3)),4)
o['scene_tcoh_mean']=round(float(np.nanmean(tc[fw])),4)
out['ASC_geo_aoi']=o

# ---------- 2. DSC ERA5 velocity: topo correlation ----------
G=f'{B}/DSC/mintpy/geo'; g=grid(f'{G}/geo_velocity.h5')
v=h5py.File(f'{G}/geo_velocity.h5','r')['velocity'][:]*1000
tc=h5py.File(f'{G}/geo_temporalCoherence.h5','r')['temporalCoherence'][:]
hgt=h5py.File(f'{G}/geo_geometryRadar.h5','r')['height'][:].astype(float)
wat,slope=water_mask(hgt,g)
rel=np.isfinite(v)&(v!=0)&(tc>0.7)&(~wat)
c=np.corrcoef(hgt[rel],v[rel])[0,1]; s,b=np.polyfit(hgt[rel],v[rel],1)
out['DSC_ERA5_scene']=dict(n_tcoh07=int(rel.sum()), median=round(float(np.median(v[rel])),2),
    corr_vel_hgt=round(float(c),3), slope_mm_yr_per_m=round(float(s),4),
    frac_valid_tcoh03=round(float(np.mean((tc>0.3)[np.isfinite(hgt)&(hgt!=0)])),3))
# compare to velocity_msk (height_correlation version, pre-ERA5) in radar coords
vm=h5py.File(f'{B}/DSC/mintpy/velocity_msk.h5','r')['velocity'][:]*1000
hr=h5py.File(f'{B}/DSC/mintpy/inputs/geometryRadar.h5','r')['height'][:].astype(float)
tr=h5py.File(f'{B}/DSC/mintpy/temporalCoherence.h5','r')['temporalCoherence'][:]
m=np.isfinite(vm)&(vm!=0)&(tr>0.7)&(hr>3330)   # crude land (above lake level) for radar grid
c2=np.corrcoef(hr[m],vm[m])[0,1]; s2,_=np.polyfit(hr[m],vm[m],1)
out['DSC_hgtcorr_radar_pre_ERA5']=dict(n=int(m.sum()),median=round(float(np.median(vm[m])),2),
    corr=round(float(c2),3),slope=round(float(s2),4),note='radar grid, h>3330 m only, ref at time of 07-19 decompose')

# ---------- 3. Reproduce export_dsc_corrected.py numbers ----------
rel=np.isfinite(v)&(v!=0)&(tc>0.5)&(~wat); hh=hgt[rel]; vv=v[rel]; keep=np.ones(hh.size,bool)
for _ in range(3):
    a1,b1=np.polyfit(hh[keep],vv[keep],1); res=vv-(a1*hh+b1); keep=np.abs(res)<2*np.std(res[keep])
vc=v-a1*hgt; rr,cc=rc(g,*REF); vc=vc-vc[rr,cc]
rs,cs=aoi_slice(g,v.shape)
val=(np.isfinite(v)&(v!=0)&(tc>0.3)&(~wat))[rs,cs]; sub=vc[rs,cs]
o=dict(topo_slope=round(float(a1),4), n_land=int(val.sum()), pct=round(100*val.mean(),1), **stats(sub[val]))
o['frac_abs_lt5']=round(float(np.mean(np.abs(sub[val])<5)),3)
o['frac_lt_-10']=round(float(np.mean(sub[val]<-10)),3)
# dam neighbourhood: 1 km radius around DAM
y0,x0,dy,dx=g; ny,nx=v.shape
LA=y0+dy*np.arange(ny)[:,None]; LO=x0+dx*np.arange(nx)[None,:]
dist=np.hypot((LA-DAM[0])*111.32,(LO-DAM[1])*111.32*np.cos(np.deg2rad(DAM[0])))
for R in (0.5,1.0):
    mk=(dist<=R)&np.isfinite(v)&(v!=0)&(tc>0.3)&(~wat)
    o[f'dam_r{R}km']=dict(**stats(vc[mk]), tcoh_mean=round(float(np.mean(tc[mk])),2) if mk.any() else None,
                          hgt_range=[round(float(hgt[mk].min())),round(float(hgt[mk].max()))] if mk.any() else None)
pr,pc=rc(g,*PT); o['point_tcoh']=round(float(tc[pr,pc]),2); o['point_vc']=round(float(vc[pr,pc]),2)
o['ref_tcoh']=round(float(tc[rr,cc]),2)
out['DSC_corrected_AOI']=o

# time series at point (ERA5 ramp demErr) -> linear + seasonal
ts=h5py.File(f'{G}/geo_timeseries_ERA5_ramp_demErr.h5','r')
dates=[d.decode() for d in ts['date'][:]]
disp=ts['timeseries'][:,pr,pc]*1000; disp=disp-disp[0]
def yr(d): dt=datetime.datetime.strptime(d,'%Y%m%d'); return dt.year+(dt.timetuple().tm_yday-1)/365.25
t=np.array([yr(d) for d in dates]); A=np.vstack([t-t[0],np.ones_like(t)]).T
k=np.linalg.lstsq(A,disp,rcond=None)[0]; r=disp-A@k
w=2*np.pi; Bm=np.vstack([np.sin(w*t),np.cos(w*t),np.sin(2*w*t),np.cos(2*w*t),np.ones_like(t)]).T
q=np.linalg.lstsq(Bm,r,rcond=None)[0]; amp1=float(np.hypot(q[0],q[1]))
phi=np.arctan2(q[0],q[1]); peak=(datetime.date(2024,1,1)+datetime.timedelta(days=float((phi/w)%1.0*365.25))).strftime('%m-%d')
out['DSC_point_ts']=dict(n_dates=len(dates),first=dates[0],last=dates[-1],
    fit_vel_raw_ref=round(float(k[0]),2), rmse_lin=round(float(np.sqrt(np.mean(r**2))),2),
    annual_amp=round(amp1,1), semiannual_amp=round(float(np.hypot(q[2],q[3])),1), annual_peak=peak,
    rmse_lin_seas=round(float(np.sqrt(np.mean((r-Bm@q)**2))),2),
    note='ts is relative to MintPy ref 38.2821,72.6066 (not re-referenced, not topo-detrended)')
# monthly gaps (snow?) : number of acquisitions per month
mon=np.array([int(d[4:6]) for d in dates]); out['DSC_dates_per_month']={int(M):int((mon==M).sum()) for M in range(1,13)}

# ---------- 4. Decomposition re-derivation ----------
def L(f,ds='velocity'): return h5py.File(f'{D}/{f}','r')[ds][:]
va=L('ASC_vel_geo.h5'); vd=L('DSC_vel_geo.h5')
ga=h5py.File(f'{D}/ASC_geom_geo.h5','r'); gd=h5py.File(f'{D}/DSC_geom_geo.h5','r')
ia,aa=np.deg2rad(ga['incidenceAngle'][:]),np.deg2rad(ga['azimuthAngle'][:])
idd,ad=np.deg2rad(gd['incidenceAngle'][:]),np.deg2rad(gd['azimuthAngle'][:])
# MintPy convention: los = -E*sin(inc)*sin(az) + N*sin(inc)*cos(az) + U*cos(inc);  assume N=0 (horz_az=-90 => E-W)
# Re-reference both to the common point stored in up.h5 attrs
ua=h5py.File(f'{D}/up.h5','r'); rY,rX=int(ua.attrs['REF_Y']),int(ua.attrs['REF_X'])
va_r=va-va[rY,rX]; vd_r=vd-vd[rY,rX]
ok=np.isfinite(va)&np.isfinite(vd)&(va!=0)&(vd!=0)&np.isfinite(ia)&np.isfinite(idd)
U=np.full(va.shape,np.nan); E=np.full(va.shape,np.nan)
for (i,j) in zip(*np.where(ok)):
    Gm=np.array([[-np.sin(ia[i,j])*np.sin(aa[i,j]), np.cos(ia[i,j])],
                 [-np.sin(idd[i,j])*np.sin(ad[i,j]), np.cos(idd[i,j])]])
    E[i,j],U[i,j]=np.linalg.solve(Gm,[va_r[i,j],vd_r[i,j]])
up=L('up.h5'); hz=L('hz.h5'); m2=ok&np.isfinite(up)&(up!=0)
def cmp(a,b):
    d=(a-b)*1000; return dict(n=int(m2.sum()),maxabs_diff_mm=round(float(np.nanmax(np.abs(d[m2]))),3),
                             r=round(float(np.corrcoef(a[m2],b[m2])[0,1]),5))
out['decomp_check']=dict(up=cmp(U,up),hz=cmp(E,hz),
    asc_inc_mean=round(float(np.degrees(np.nanmean(ia[ok]))),1), dsc_inc_mean=round(float(np.degrees(np.nanmean(idd[ok]))),1),
    asc_az_mean=round(float(np.degrees(np.nanmean(aa[ok]))),1), dsc_az_mean=round(float(np.degrees(np.nanmean(ad[ok]))),1),
    asc_valid=int((np.isfinite(va)&(va!=0)).sum()), dsc_valid=int((np.isfinite(vd)&(vd!=0)).sum()),
    overlap=int(ok.sum()), grid=int(va.size),
    up_stats=stats(up[m2]*1000), hz_stats=stats(hz[m2]*1000),
    asc_period=[ga.attrs.get('START_DATE',''), h5py.File(f'{D}/ASC_vel_geo.h5','r').attrs['END_DATE']],
    dsc_period=[h5py.File(f'{D}/DSC_vel_geo.h5','r').attrs['START_DATE'], h5py.File(f'{D}/DSC_vel_geo.h5','r').attrs['END_DATE']])
gu=grid(f'{D}/up.h5'); y0,x0,dy,dx=gu; ny,nx=up.shape
LA=y0+dy*np.arange(ny)[:,None]; LO=x0+dx*np.arange(nx)[None,:]
dist=np.hypot((LA-DAM[0])*111.32,(LO-DAM[1])*111.32*np.cos(np.deg2rad(DAM[0])))
mk=(dist<=1.0)&m2
out['decomp_check']['dam_r1km']=dict(n=int(mk.sum()), up=stats(up[mk]*1000) if mk.sum()>2 else None,
                                     hz=stats(hz[mk]*1000) if mk.sum()>2 else None)
print(json.dumps(out,indent=1,default=str))
json.dump(out,open('recompute_out.json','w'),indent=1,default=str)
