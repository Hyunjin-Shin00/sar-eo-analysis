#!/usr/bin/env python3
# PS vs SBAS 비교분석: 공통 격자(300m) 집계 → 공통모드 제거 → 패턴 상관 + 4패널 비교도(지역별 PNG) + 요약
import os, sys
os.environ.pop('PYTHONPATH', None)
import numpy as np, pandas as pd, geopandas as gpd
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt

BASE='<DATA_ROOT>/CLAB'
REGIONS=['Seoul_Gangdong','Seoul_Seodaemun','Gyeonggi_Gwangmyeong','Busan_Mandeok_Centum',
         'Busan_Sasang_Hadan','Incheon_Songdo','Yangyang']
CELL=300.0  # 격자 크기(m)

# region → regions/<group>/<tech>/[<aoi>] (2026-07-19 통합 재정리)
_LAYOUT={'Busan_Mandeok_Centum':('busan','mandeok_centum'),'Busan_Sasang_Hadan':('busan','sasang_hadan'),
 'Seoul_Seodaemun':('seoul','seodaemun'),'Seoul_Gangdong':('seoul','gangdong'),
 'Incheon_Songdo':('incheon','songdo'),'Incheon_Songdo_DSC':('incheon','songdo_dsc'),
 'Incheon_Songdo_baseline':('incheon','songdo_baseline'),
 'Gyeonggi_Gwangmyeong':('gyeonggi',None),'Yangyang':('yangyang',None)}
def rdir(R,tech):
    g,a=_LAYOUT.get(R,(R.lower(),None)); p=f'{BASE}/regions/{g}/{tech}'
    return f'{p}/{a}' if a else p

def vel(shp):
    g=gpd.read_file(shp)
    return (g['Longitude'].to_numpy(float),g['Latitude'].to_numpy(float),g['velocity'].to_numpy(float))

def theil_sen(x,y):
    n=len(x); idx=np.arange(0,n,max(1,n//1500)); xs,ys=x[idx],y[idx]; sl=[]
    for i in range(len(xs)):
        dx=xs[i+1:]-xs[i]; dy=ys[i+1:]-ys[i]; m=np.abs(dx)>1e-9
        if m.any(): sl.append(dy[m]/dx[m])
    sl=np.concatenate(sl) if len(sl) else np.array([1.0]); s=float(np.median(sl))
    return s, float(np.median(y-s*x))

def grid(lon,lat,v,lon0,lat0,kx,ky):
    cx=np.floor((lon-lon0)*kx/CELL).astype(int); cy=np.floor((lat-lat0)*ky/CELL).astype(int)
    df=pd.DataFrame({'cx':cx,'cy':cy,'v':v}).dropna()
    g=df.groupby(['cx','cy']).v.mean()
    # 셀 중심 좌표
    cxc=g.index.get_level_values(0).to_numpy(); cyc=g.index.get_level_values(1).to_numpy()
    clon=lon0+(cxc+0.5)*CELL/kx; clat=lat0+(cyc+0.5)*CELL/ky
    return {(int(a),int(b)):float(val) for (a,b),val in g.items()}, (cxc,cyc,clon,clat,g.to_numpy())

rows=[]
for R in REGIONS:
    ps=f'{rdir(R,"psinsar")}/output_final.shp'; sb=f'{rdir(R,"sbas")}/{R}_sbas_ps_v.shp'
    if not (os.path.exists(ps) and os.path.exists(sb)):
        print('skip(파일없음)',R); continue
    plon,plat,pv=vel(ps); slon,slat,sv=vel(sb)
    lon0=float(np.concatenate([plon,slon]).mean()); lat0=float(np.concatenate([plat,slat]).mean())
    kx=111320*np.cos(np.deg2rad(lat0)); ky=111320.0
    gp,pg=grid(plon,plat,pv,lon0,lat0,kx,ky)
    gs,sg=grid(slon,slat,sv,lon0,lat0,kx,ky)
    common=sorted(set(gp)&set(gs))
    if len(common)<10:
        print('skip(공통셀부족)',R,len(common)); continue
    a=np.array([gp[k] for k in common]); b=np.array([gs[k] for k in common])  # a=PS, b=SBAS
    r=float(np.corrcoef(a,b)[0,1]); slope,off=theil_sen(a,b)
    med_off=float(np.median(b-a)); rms=float(np.sqrt(np.mean((b-a-med_off)**2)))
    # 공통셀 중심좌표(차분/산점도용)
    clon=np.array([lon0+(k[0]+0.5)*CELL/kx for k in common]); clat=np.array([lat0+(k[1]+0.5)*CELL/ky for k in common])
    diff=b-a-med_off
    rows.append((R,len(common),r,slope,med_off,rms,float(np.nanmedian(np.abs(a))),float(np.nanmedian(np.abs(b)))))

    # ---- 4패널 ----
    vmax=max(1.0,float(np.nanpercentile(np.abs(np.concatenate([a,b])),95)))
    dmax=max(0.5,float(np.nanpercentile(np.abs(diff),95)))
    fig,ax=plt.subplots(2,2,figsize=(15,12)); fig.suptitle(f'{R}: PS vs SBAS (grid {int(CELL)} m, n={len(common)} cells)',fontsize=14,fontweight='bold')
    sc0=ax[0,0].scatter(pg[2],pg[3],c=pg[4],s=10,cmap='RdBu_r',vmin=-vmax,vmax=vmax); ax[0,0].set_title('PS velocity (mm/yr)'); plt.colorbar(sc0,ax=ax[0,0])
    sc1=ax[0,1].scatter(sg[2],sg[3],c=sg[4],s=14,cmap='RdBu_r',vmin=-vmax,vmax=vmax); ax[0,1].set_title('SBAS velocity (mm/yr)'); plt.colorbar(sc1,ax=ax[0,1])
    sc2=ax[1,0].scatter(clon,clat,c=diff,s=16,cmap='PuOr',vmin=-dmax,vmax=dmax); ax[1,0].set_title(f'Difference SBAS-PS (offset {med_off:+.1f} removed)'); plt.colorbar(sc2,ax=ax[1,0])
    ax[1,1].scatter(a,b,s=8,alpha=0.4,c='#2166ac'); lim=max(vmax,float(np.nanpercentile(np.abs(np.concatenate([a,b])),99)))
    xx=np.array([-lim,lim]); ax[1,1].plot(xx,xx,'k--',lw=1,label='1:1'); ax[1,1].plot(xx,slope*xx+off,'r-',lw=1.2,label=f'fit slope={slope:.2f}')
    ax[1,1].set_xlim(-lim,lim); ax[1,1].set_ylim(-lim,lim); ax[1,1].set_xlabel('PS (mm/yr)'); ax[1,1].set_ylabel('SBAS (mm/yr)')
    ax[1,1].set_title(f'gridded scatter  r={r:.2f}  offset={med_off:+.1f}  RMS(after)={rms:.1f} mm/yr'); ax[1,1].legend(loc='upper left'); ax[1,1].grid(alpha=0.3)
    for a_ in [ax[0,0],ax[0,1],ax[1,0]]: a_.set_xlabel('lon'); a_.set_ylabel('lat'); a_.ticklabel_format(useOffset=False)
    out=f'{rdir(R,"reports")}/{R}_PS_vs_SBAS_compare.png'; fig.savefig(out,dpi=105,bbox_inches='tight'); plt.close(fig)
    print(f'{R:<22} n={len(common):>4} r={r:+.2f} slope={slope:.2f} offset={med_off:+.2f} RMS={rms:.1f} → {out}')

# 요약 저장
import io
S=io.StringIO()
S.write('PS vs SBAS 비교분석 요약 (공통 300m 격자, 공통모드=중앙오프셋 제거 후 패턴 비교)\n')
S.write(f"{'region':<22}{'cells':>6}{'r(패턴)':>8}{'slope':>7}{'offset':>8}{'RMS후':>7}{'PS|v|중앙':>9}{'SBAS|v|중앙':>11}\n")
S.write('-'*80+'\n')
for R,n,r,sl,mo,rms,pa,sa in rows:
    S.write(f"{R:<22}{n:>6}{r:>+8.2f}{sl:>7.2f}{mo:>+8.2f}{rms:>7.1f}{pa:>9.2f}{sa:>11.2f}\n")
S.write('\n해석 지침:\n')
S.write('- r(패턴): 격자 집계 후 상관. 0.5+ 양호, 0.3~0.5 보통, <0.3 약함(이질/노이즈).\n')
S.write('- slope<1: SBAS가 PS보다 진폭 작게(공간평균 평활). offset: 두 기준점 차이(제거함).\n')
S.write('- RMS후: 공통모드 제거 뒤 잔차. 클수록 국소 불일치(이질 침하/언랩/서로 다른 산란체).\n')
open(f'{BASE}/_PS_vs_SBAS_summary.txt','w').write(S.getvalue())
print('\n'+S.getvalue())
