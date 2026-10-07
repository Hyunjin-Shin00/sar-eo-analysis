#!/usr/bin/env python3
# 광역 SBAS 타일 격자 생성 + 타일별 사고 건수 산출
import os, json, csv, argparse, numpy as np
os.environ.pop('PYTHONPATH', None)
from osgeo import gdal
p=argparse.ArgumentParser()
p.add_argument('--merged', default='<DATA_ROOT>/CLAB/regions/seoul/workspace/stamps_seoul/stack/merged')
p.add_argument('--bbox', nargs=4, type=float, default=[37.15,37.85,126.35,127.35], metavar=('S','N','W','E'))
p.add_argument('--nrow', type=int, default=6); p.add_argument('--ncol', type=int, default=5)
p.add_argument('--ov', type=int, default=60)
p.add_argument('--out', required=True)
a=p.parse_args()
lat=gdal.Open(f'{a.merged}/geom_reference/lat.rdr').ReadAsArray()
lon=gdal.Open(f'{a.merged}/geom_reference/lon.rdr').ReadAsArray()
S,N,W,E=a.bbox
m=(lat>=S)&(lat<=N)&(lon>=W)&(lon<=E)
rows=np.any(m,axis=1); cols=np.any(m,axis=0)
R0,R1=int(np.argmax(rows)),int(len(rows)-np.argmax(rows[::-1]))
C0,C1=int(np.argmax(cols)),int(len(cols)-np.argmax(cols[::-1]))
naz,nrg=R1-R0,C1-C0
re=np.linspace(R0,R1,a.nrow+1).astype(int); ce=np.linspace(C0,C1,a.ncol+1).astype(int)
acc=[]
with open('<DATA_ROOT>/CLAB/auxiliary/subsidence_list/subsidence_accidents_geocoded_update.csv',encoding='utf-8-sig') as fh:
    for x in csv.DictReader(fh):
        if x['geocodeType'] in ('parcel','road','kakao_addr','kakao_keyword') and x['lat'] and len(x['sagoDate'])==8:
            acc.append((float(x['lat']),float(x['lon']),x['sagoDate']))
per=[p_ for p_ in acc if '20190109'<=p_[2]<='20260426']
tiles=[]
for i in range(a.nrow):
    for j in range(a.ncol):
        r0=max(R0,re[i]-a.ov); r1=min(R1,re[i+1]+a.ov)
        c0=max(C0,ce[j]-a.ov); c1=min(C1,ce[j+1]+a.ov)
        sub_lat=lat[r0:r1,c0:c1]; sub_lon=lon[r0:r1,c0:c1]
        v=(sub_lat!=0)&(sub_lon!=0)
        if v.sum()==0: continue
        la=sub_lat[v]; lo=sub_lon[v]
        bb=(float(la.min()),float(la.max()),float(lo.min()),float(lo.max()))
        na=sum(1 for q in per if bb[0]<=q[0]<=bb[1] and bb[2]<=q[1]<=bb[3])
        tiles.append(dict(name=f't{i}{j}', win=[int(r0),int(r1),int(c0),int(c1)],
                          px=int((r1-r0)*(c1-c0)), valid=int(v.sum()), bbox=bb, n_acc=na))
json.dump(dict(core=[R0,R1,C0,C1], naz=naz, nrg=nrg, ov=a.ov, tiles=tiles), open(a.out,'w'), indent=1)
print(f'코어창 R{R0}:{R1} C{C0}:{C1} = {naz}x{nrg} = {naz*nrg:,}px')
print(f'타일 {len(tiles)}개  (평균 {np.mean([t["px"] for t in tiles]):,.0f}px, 최대 {max(t["px"] for t in tiles):,}px)')
est=max(t['px'] for t in tiles)*52.4/1e6
print(f'최대 타일 예상 메모리 ~{est:.1f} GB')
for t in sorted(tiles,key=lambda x:-x['n_acc']):
    print(f"  {t['name']} win={t['win']} {t['px']:>7,}px 유효{100*t['valid']/t['px']:>3.0f}% 사고 {t['n_acc']:>3d}  lat {t['bbox'][0]:.2f}~{t['bbox'][1]:.2f} lon {t['bbox'][2]:.2f}~{t['bbox'][3]:.2f}")
