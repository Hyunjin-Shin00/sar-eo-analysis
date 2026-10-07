#!/usr/bin/env python3
# 광역 타일 SBAS — run_sbas.py의 수식을 그대로 쓰되 입력을 lat/lon bbox 대신
# 멀티룩 픽셀창(R0 R1 C0 C1)으로 받는다. 회전된 프레임을 bbox로 자르면 창이 과도하게
# 커지므로 광역 타일링에서는 픽셀창이 맞다. 출력은 CSV만(타일 병합은 별도 단계).
# usage: run_sbas_tile.py --merged DIR --win R0 R1 C0 C1 --out DIR --region NAME [--keep-cache]
import os, sys
os.environ.pop('PYTHONPATH', None)
os.environ['OMP_NUM_THREADS']='1'; os.environ['OPENBLAS_NUM_THREADS']='1'; os.environ['MKL_NUM_THREADS']='1'
import glob, subprocess, json, datetime, argparse, re, numpy as np
from osgeo import gdal

p=argparse.ArgumentParser()
p.add_argument('--merged', required=True)
p.add_argument('--win', nargs=4, type=int, required=True, metavar=('R0','R1','C0','C1'))
p.add_argument('--out', required=True)
p.add_argument('--region', required=True)
p.add_argument('--rgl', type=int, default=9); p.add_argument('--azl', type=int, default=3)
p.add_argument('--cmax', type=int, default=4); p.add_argument('--tmax', type=int, default=72)
p.add_argument('--coh_min', type=float, default=0.30); p.add_argument('--tcoh_min', type=float, default=0.70)
p.add_argument('--lam', type=float, default=0.055465763)
p.add_argument('--keep-cache', action='store_true')
a=p.parse_args()

M=a.merged; OUT=a.out; os.makedirs(OUT, exist_ok=True)
WK=f'{OUT}/_sbas_work_{os.getpid()}'; os.makedirs(WK, exist_ok=True)
ST=f'{OUT}/sbas_status.txt'
SNAPHU='/usr/local/GMTSAR/bin/snaphu'
RGL,AZL=a.rgl,a.azl; CMAX,TMAX=a.cmax,a.tmax; COH_MIN,TCOH_MIN=a.coh_min,a.tcoh_min; LAM=a.lam
def LOG(*x):
    s='[%s] '%datetime.datetime.now().strftime('%F %T')+' '.join(str(v) for v in x)
    print(s,flush=True); open(ST,'a').write(s+'\n')
assert os.path.exists(SNAPHU), f'snaphu 없음 {SNAPHU}'

R0,R1,C0,C1=a.win
naz,nrg=R1-R0,C1-C0; xoff,yoff,xs,ys=C0*RGL,R0*AZL,nrg*RGL,naz*AZL
LOG(f'{a.region} tile win R{R0}:{R1} C{C0}:{C1} ({naz}x{nrg}={naz*nrg}px)')

# .slc.full.vrt는 burst vrt 체인 끝에서 삭제된 원본 zip(/vsizip)에 닿는 날짜가 있어 사용 불가.
# .slc.full 바이너리를 memmap으로 직접 읽는다. 전체 크기는 vrt 헤더에서만 파싱.
slcs=sorted(glob.glob(f'{M}/SLC/*/2*.slc.full')); dates=[os.path.basename(f)[:8] for f in slcs]; nd=len(dates)
_hdr=open(slcs[0]+'.vrt').read(300)
FW=int(re.search(r'rasterXSize="(\d+)"',_hdr).group(1)); FH=int(re.search(r'rasterYSize="(\d+)"',_hdr).group(1))
for _f in slcs:
    if os.path.getsize(_f)!=FW*FH*8: sys.exit(f'ERROR: 크기 불일치 {_f}')
dt=[datetime.date(int(d[:4]),int(d[4:6]),int(d[6:8])) for d in dates]
pairs=[(i,j) for i in range(nd) for j in range(i+1,min(i+1+CMAX,nd)) if (dt[j]-dt[i]).days<=TMAX or j==i+1]
LOG(f'nd={nd} pairs={len(pairs)}')

# 간섭쌍이 j<=i+CMAX로 제한되므로 전체 날짜를 메모리에 올릴 필요가 없다.
# CMAX+1개 날짜만 유지하는 슬라이딩 윈도우로 타일당 ~13GB -> ~0.4GB. 디스크 읽기 횟수는 동일(날짜당 1회).
LOG(f'[1] SLC 슬라이딩 윈도우 {CMAX+1}일 (memmap {FW}x{FH})')
BUF={}
PBUF={}
def getF(k):
    if k not in BUF:
        mm=np.memmap(slcs[k],dtype=np.complex64,mode='r',shape=(FH,FW))
        BUF[k]=np.array(mm[yoff:yoff+ys, xoff:xoff+xs]); del mm
    return BUF[k]
def getP(k):
    # 날짜별 멀티룩 파워는 그 날짜가 낀 모든 쌍(최대 2*CMAX개)에서 동일하다.
    # 쌍마다 재계산하면 내부루프 연산의 2/3가 중복 → 메모이즈(연산 동일하므로 결과 불변).
    if k not in PBUF:
        PBUF[k]=(np.abs(getF(k))**2).reshape(naz,AZL,nrg,RGL).sum((1,3))
    return PBUF[k]
LOG(f'[2] 간섭도+unwrap {len(pairs)}쌍'); UNW=np.empty((len(pairs),naz,nrg),np.float32); COH=np.empty_like(UNW)
conf=f'{WK}/snaphu.conf'
for q,(i,j) in enumerate(pairs):
    for k in list(BUF):
        if k<i: del BUF[k]
    for k in list(PBUF):
        if k<i: del PBUF[k]
    pm=getP(i); ps=getP(j)
    Fi=getF(i); Fj=getF(j)
    igf=Fi*np.conj(Fj); ig=igf.reshape(naz,AZL,nrg,RGL).sum((1,3))
    COH[q]=(np.abs(ig)/np.sqrt(pm*ps+1e-20)).astype(np.float32)
    (ig/(np.abs(ig)+1e-20)).astype(np.complex64).tofile(f'{WK}/p.int'); COH[q].tofile(f'{WK}/p.cor')
    open(conf,'w').write(f"INFILE {WK}/p.int\nLINELENGTH {nrg}\nOUTFILE {WK}/p.unw\nCORRFILE {WK}/p.cor\nINFILEFORMAT COMPLEX_DATA\nCORRFILEFORMAT FLOAT_DATA\nOUTFILEFORMAT FLOAT_DATA\nSTATCOSTMODE DEFO\nINITMETHOD MCF\n")
    subprocess.run([SNAPHU,'-f',conf],capture_output=True,cwd=WK)
    UNW[q]=np.fromfile(f'{WK}/p.unw',np.float32).reshape(naz,nrg)
    if (q+1)%100==0: LOG(f'   unwrap {q+1}/{len(pairs)}')
BUF.clear(); PBUF.clear()
if a.keep_cache: np.savez(f'{OUT}/cache.npz',UNW=UNW,COH=COH); LOG('   캐시 저장')

npair=len(pairs); Npix=naz*nrg
Uall=UNW.reshape(npair,Npix); Cf=COH.reshape(npair,Npix); mcoh=Cf.mean(0)
ref=int(np.argmax(mcoh)); LOG(f'[3] 기준픽셀 max-coh px#{ref} coh={mcoh[ref]:.3f}')
B=np.zeros((npair,nd-1))
for q,(i,j) in enumerate(pairs):
    if i>0: B[q,i-1]=-1.0
    B[q,j-1]=1.0
w=np.clip(Cf.mean(1),1e-3,None); Bw=w[:,None]*B; Binv=np.linalg.pinv(Bw)
def gr(n):
    ds=gdal.Open(f'{M}/geom_reference/{n}'); v=ds.ReadAsArray()[R0:R1,C0:C1].reshape(-1); ds=None; return v
lat=gr('lat.rdr'); lon=gr('lon.rdr')
t=np.array([(d-dt[0]).days for d in dt])/365.25; tc=t-t.mean()
yy,xx=np.divmod(np.arange(Npix),nrg); A=np.c_[np.ones(Npix),xx,yy]
import pandas as pd
U=Uall.copy(); off=U[:,ref].copy(); U-=off[:,None]
phi=np.zeros((nd,Npix),np.float32); phi[1:]=Binv@(w[:,None]*U)
# tcoh: 전 픽셀을 한 번에 하면 resid(float64)+exp(complex128)로 픽셀당 24B*npair가 잡혀
# 실측 피크의 대부분을 차지한다. 픽셀 방향 청크로 나눈다(축소축이 아니므로 결과는 동일).
tcoh=np.empty(Npix,np.float64); CH=50000
for s0 in range(0,Npix,CH):
    e0=min(s0+CH,Npix)
    r=U[:,s0:e0]-(B@phi[1:,s0:e0])
    tcoh[s0:e0]=np.abs(np.exp(1j*r).mean(0))
del r
good=(mcoh>=COH_MIN)&(tcoh>=TCOH_MIN)
if int(good.sum())==0:
    LOG('양호0 skip'); json.dump({'ok':False,'n':0},open(f'{OUT}/tile_meta.json','w')); sys.exit(0)
Ag=A[good]
for k in range(1,nd):
    c,*_=np.linalg.lstsq(Ag,phi[k,good],rcond=None); phi[k]-=A@c
phi-= phi[:,ref][:,None]
disp=(-LAM/(4*np.pi)*phi*1000.0).astype(np.float32)
vel=((tc[:,None]*disp).sum(0)/(tc**2).sum()).astype(np.float32)
gp=np.where(good)[0]
LOG(f'채택 {int(good.sum())}/{Npix} tcoh중앙 {np.median(tcoh):.3f} 속도[{vel[good].min():.2f},{vel[good].max():.2f}]')
df=pd.DataFrame({'Longitude':np.round(lon[gp],6),'Latitude':np.round(lat[gp],6),'incidence':0.0,
                 'velocity':np.round(vel[gp],4),'tcoh':np.round(tcoh[gp],3)})
df['row']=(gp//nrg)+R0; df['col']=(gp%nrg)+C0
for k,d in enumerate(dates): df[f'D{d}']=np.round(disp[k,gp],4)
df['is_ref']=0
if ref in gp: df.loc[np.where(gp==ref)[0][0],'is_ref']=1
df.to_csv(f'{OUT}/{a.region}_sbas.csv.gz',index=False,compression='gzip')
json.dump({'ok':True,'region':a.region,'win':[R0,R1,C0,C1],'n':int(good.sum()),'Npix':Npix,
           'ref_px':ref,'ref_lon':float(lon[ref]),'ref_lat':float(lat[ref]),
           'ref_row':int(ref//nrg)+R0,'ref_col':int(ref%nrg)+C0,'nd':nd,'npair':npair},
          open(f'{OUT}/tile_meta.json','w'),ensure_ascii=False,indent=2)
import shutil
shutil.rmtree(WK, ignore_errors=True)
LOG('TILE DONE')
