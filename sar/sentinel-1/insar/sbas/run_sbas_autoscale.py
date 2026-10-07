#!/usr/bin/env python3
# 일반화 정밀 SBAS (MintPy식) — run_sbas.py 패치판.
#   차이점: merged geom(lat/lon.rdr)↔SLC.full 배율을 자동감지(mrg,maz)하여
#   geom이 full-res(1x1, 예: -r1 -z1 스택)든 멀티룩(9x3, ASC류)이든 모두 올바른 창을 읽음.
#   RGL/AZL은 순수 SBAS 멀티룩(전해상도 기준)으로만 사용. ASC류(9x3)에서는 기존 run_sbas.py와 동일 동작.
# usage: run_sbas_autoscale.py --merged DIR --bbox S N W E --out DIR --region NAME [--rgl 9 --azl 3]
import os, sys
os.environ.pop('PYTHONPATH', None)
import glob, subprocess, json, datetime, argparse, numpy as np
from osgeo import gdal

def parse():
    p=argparse.ArgumentParser()
    p.add_argument('--merged', required=True)
    p.add_argument('--bbox', nargs=4, type=float, required=True, metavar=('S','N','W','E'))
    p.add_argument('--out', required=True)
    p.add_argument('--region', required=True)
    p.add_argument('--rgl', type=int, default=9); p.add_argument('--azl', type=int, default=3)
    p.add_argument('--cmax', type=int, default=4); p.add_argument('--tmax', type=int, default=72)
    p.add_argument('--coh_min', type=float, default=0.30); p.add_argument('--tcoh_min', type=float, default=0.70)
    p.add_argument('--lam', type=float, default=0.055465763)
    return p.parse_args()

a=parse()
M=a.merged; OUT=a.out; os.makedirs(OUT, exist_ok=True)
WK=f'{OUT}/_sbas_work'; os.makedirs(WK, exist_ok=True)
CACHE=f'{OUT}/cache.npz'; ST=f'{OUT}/sbas_status.txt'
SNAPHU='/usr/local/GMTSAR/bin/snaphu'
RGL,AZL=a.rgl,a.azl; CMAX,TMAX=a.cmax,a.tmax; COH_MIN,TCOH_MIN=a.coh_min,a.tcoh_min; LAM=a.lam
def LOG(*x):
    s='[%s] '%datetime.datetime.now().strftime('%F %T')+' '.join(str(v) for v in x)
    print(s,flush=True); open(ST,'a').write(s+'\n')
assert os.path.exists(SNAPHU), f'snaphu 없음 {SNAPHU}'

# --- bbox -> crop창 (geom lat/lon.rdr, geom↔SLC 배율 자동감지) ---
S,N,W,E=a.bbox
lat_full=gdal.Open(f'{M}/geom_reference/lat.rdr').ReadAsArray()
lon_full=gdal.Open(f'{M}/geom_reference/lon.rdr').ReadAsArray()
Hg,Wg=lat_full.shape
mask=(lat_full>=S)&(lat_full<=N)&(lon_full>=W)&(lon_full<=E)
if not mask.any(): LOG('ERROR: bbox가 merged 범위 밖'); sys.exit(2)
rows=np.any(mask,axis=1); cols=np.any(mask,axis=0)
R0,R1=int(np.argmax(rows)),int(len(rows)-np.argmax(rows[::-1]))
C0,C1=int(np.argmax(cols)),int(len(cols)-np.argmax(cols[::-1]))
# geom↔SLC.full 배율 (ASC류 멀티룩geom→9x3 / full-res geom→1x1)
_slc0=sorted(glob.glob(f'{M}/SLC/*/2*.slc.full.vrt'))[0]
_ds=gdal.Open(_slc0); Wf,Hf=_ds.RasterXSize,_ds.RasterYSize; _ds=None
mrg=max(1,round(Wf/Wg)); maz=max(1,round(Hf/Hg))
# 전해상도 읽기창 = geom bbox × 배율, SBAS 멀티룩(RGL,AZL) 나눠떨어지게 trim
xoff,yoff=C0*mrg,R0*maz
xs0,ys0=(C1-C0)*mrg,(R1-R0)*maz
nrg,naz=xs0//RGL,ys0//AZL
xs,ys=nrg*RGL,naz*AZL
LOG(f'{a.region} geom {Wg}x{Hg} SLC {Wf}x{Hf} 배율 mrg={mrg} maz={maz}')
LOG(f'{a.region} SBAS window full[x {xoff}:{xoff+xs}, y {yoff}:{yoff+ys}] → 멀티룩 {naz}x{nrg}={naz*nrg}px')

slcs=sorted(glob.glob(f'{M}/SLC/*/2*.slc.full.vrt')); dates=[os.path.basename(f)[:8] for f in slcs]; nd=len(dates)
dt=[datetime.date(int(d[:4]),int(d[4:6]),int(d[6:8])) for d in dates]
pairs=[(i,j) for i in range(nd) for j in range(i+1,min(i+1+CMAX,nd)) if (dt[j]-dt[i]).days<=TMAX or j==i+1]
LOG(f'nd={nd} pairs={len(pairs)}')

if os.path.exists(CACHE):
    LOG('[캐시] 로드'); z=np.load(CACHE); UNW=z['UNW']; COH=z['COH']
    if UNW.shape[1]!=naz or UNW.shape[2]!=nrg:
        LOG('캐시 창 불일치 → 재생성'); os.remove(CACHE); UNW=None
    else: UNW=z['UNW']
else: UNW=None
if UNW is None:
    LOG(f'[1] SLC {nd} crop'); F=np.empty((nd,ys,xs),np.complex64)
    for k,f in enumerate(slcs):
        ds=gdal.Open(f); F[k]=ds.GetRasterBand(1).ReadAsArray(xoff,yoff,xs,ys); ds=None
    LOG(f'[2] 간섭도+unwrap {len(pairs)}쌍'); UNW=np.empty((len(pairs),naz,nrg),np.float32); COH=np.empty_like(UNW)
    conf=f'{WK}/snaphu.conf'
    for p,(i,j) in enumerate(pairs):
        igf=F[i]*np.conj(F[j]); ig=igf.reshape(naz,AZL,nrg,RGL).sum((1,3))
        pm=(np.abs(F[i])**2).reshape(naz,AZL,nrg,RGL).sum((1,3)); ps=(np.abs(F[j])**2).reshape(naz,AZL,nrg,RGL).sum((1,3))
        COH[p]=(np.abs(ig)/np.sqrt(pm*ps+1e-20)).astype(np.float32)
        (ig/(np.abs(ig)+1e-20)).astype(np.complex64).tofile(f'{WK}/p.int'); COH[p].tofile(f'{WK}/p.cor')
        open(conf,'w').write(f"INFILE {WK}/p.int\nLINELENGTH {nrg}\nOUTFILE {WK}/p.unw\nCORRFILE {WK}/p.cor\nINFILEFORMAT COMPLEX_DATA\nCORRFILEFORMAT FLOAT_DATA\nOUTFILEFORMAT FLOAT_DATA\nSTATCOSTMODE DEFO\nINITMETHOD MCF\n")
        subprocess.run([SNAPHU,'-f',conf],capture_output=True,cwd=WK)
        UNW[p]=np.fromfile(f'{WK}/p.unw',np.float32).reshape(naz,nrg)
        if (p+1)%50==0: LOG(f'   unwrap {p+1}/{len(pairs)}')
    np.savez(CACHE,UNW=UNW,COH=COH); LOG('   캐시 저장')

npair=len(pairs); Npix=naz*nrg
Uall=UNW.reshape(npair,Npix); Cf=COH.reshape(npair,Npix); mcoh=Cf.mean(0)
ref=int(np.argmax(mcoh)); LOG(f'[3] 기준픽셀 max-coh px#{ref} coh={mcoh[ref]:.3f}')
B=np.zeros((npair,nd-1))
for p,(i,j) in enumerate(pairs):
    if i>0: B[p,i-1]=-1.0
    B[p,j-1]=1.0
w=np.clip(Cf.mean(1),1e-3,None); Bw=w[:,None]*B; Binv=np.linalg.pinv(Bw)
def gr(n):
    ds=gdal.Open(f'{M}/geom_reference/{n}'); arr=ds.ReadAsArray(); ds=None
    grow=np.clip(((yoff+(np.arange(naz)*AZL)+AZL//2)//maz).astype(int),0,Hg-1)
    gcol=np.clip(((xoff+(np.arange(nrg)*RGL)+RGL//2)//mrg).astype(int),0,Wg-1)
    return arr[np.ix_(grow,gcol)].reshape(-1)
lat=gr('lat.rdr'); lon=gr('lon.rdr')
t=np.array([(d-dt[0]).days for d in dt])/365.25; tc=t-t.mean()
yy,xx=np.divmod(np.arange(Npix),nrg); A=np.c_[np.ones(Npix),xx,yy]
import pandas as pd, geopandas as gpd
def run(suffix,tag):
    U=Uall.copy(); off=U[:,ref]; U=U-off[:,None]  # 표준 기준점: 최대결맞음 단일픽셀 차감
    phi=np.zeros((nd,Npix),np.float32); phi[1:]=Binv@(w[:,None]*U)
    resid=U-(B@phi[1:]); tcoh=np.abs(np.exp(1j*resid).mean(0))
    good=(mcoh>=COH_MIN)&(tcoh>=TCOH_MIN)
    if int(good.sum())==0: LOG(f'[{tag}] 양호0 skip'); return
    Ag=A[good]
    for k in range(1,nd):
        c,*_=np.linalg.lstsq(Ag,phi[k,good],rcond=None); phi[k]-=A@c
    phi-= phi[:,ref][:,None]
    disp=(-LAM/(4*np.pi)*phi*1000.0).astype(np.float32)
    vel=((tc[:,None]*disp).sum(0)/(tc**2).sum()).astype(np.float32)
    gp=np.where(good)[0]
    LOG(f'[{tag}] 채택 {int(good.sum())}/{Npix} tcoh중앙 {np.median(tcoh):.3f} 속도[{vel[good].min():.2f},{vel[good].max():.2f}]')
    df=pd.DataFrame({'Longitude':np.round(lon[gp],6),'Latitude':np.round(lat[gp],6),'incidence':0.0,
                     'velocity':np.round(vel[gp],4),'tcoh':np.round(tcoh[gp],3)})
    for k,d in enumerate(dates): df[f'D{d}']=np.round(disp[k,gp],4)
    df['is_ref']=0
    if ref in gp: df.loc[np.where(gp==ref)[0][0],'is_ref']=1
    base=f'{OUT}/{a.region}_sbas_ps_v'+suffix
    df.to_csv(base+'.csv',index=False)
    gpd.GeoDataFrame(df,geometry=gpd.points_from_xy(df.Longitude,df.Latitude),crs=4326).to_file(base+'.shp')
    LOG(f'[{tag}] 저장 {base}.shp ({len(df)}px)')
run('','차감후')
json.dump({'ok':True,'ref_lon':float(lon[ref]),'ref_lat':float(lat[ref]),'ref_radius_m':60.0,
           'n_ps_in_ref':1,'mean_abs_v_mm_yr':0.0,'mean_resid_std_mm':0.0,'note':'SBAS max-coh ref pixel'},
          open(f'{OUT}/{a.region}_sbas_ref_for_clickmap.json','w'),ensure_ascii=False,indent=2)
LOG('SBAS DONE')
