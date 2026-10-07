#!/usr/bin/env python3
# 광역 SBAS 타일 병합 + 타일간 기준 보정.
# 각 타일은 자기 타일 내 최대결맞음 픽셀을 기준으로 삼고 타일별로 deramp(평면 제거)를 하므로
# 인접 타일 사이에 상수 단차가 아니라 '평면' 차이가 생긴다. 중첩부 공통픽셀로
# 타일별 보정평면 (a + b*X + c*Y)를 최소제곱으로 풀어 하나의 기준으로 묶는다(앵커 타일 고정).
import os, sys, json, glob, argparse, numpy as np, pandas as pd
os.environ.pop('PYTHONPATH', None)

p=argparse.ArgumentParser()
p.add_argument('--root', default='<WORK_ROOT>/CLAB_WIDE/capital_asc')
p.add_argument('--out',  default='<DATA_ROOT>/CLAB/regions/capital_wide/sbas')
p.add_argument('--region', default='capital_wide')
p.add_argument('--maxov', type=int, default=20000, help='타일쌍당 사용할 중첩픽셀 상한')
p.add_argument('--minov', type=int, default=100, help='연결로 인정할 최소 대응점 수')
p.add_argument('--rad', type=float, default=300.0, help='타일간 대응점 최대 거리(m)')
p.add_argument('--no-subtiles', action='store_true', help='재처리 서브타일을 무시하고 원본 30타일만 병합')
p.add_argument('--plane', action='store_true', help='상수 오프셋 대신 평면(a+bX+cY) 보정. 기본은 오프셋 전용 — 평면은 얇은 연결에서 계수가 폭주한다')
p.add_argument('--no-ts', action='store_true', help='시계열 열 보정 생략(속도만)')
a=p.parse_args()
os.makedirs(a.out, exist_ok=True)
LOGP=f'{a.out}/merge_status.txt'
def LOG(*x):
    import datetime
    s='[%s] '%datetime.datetime.now().strftime('%F %T')+' '.join(str(v) for v in x)
    print(s,flush=True); open(LOGP,'a').write(s+'\n')

# 원본 타일 + 재처리 서브타일을 함께 읽는다. 4분할이 모두 끝난 부모는 제외한다 —
# 부모와 서브타일은 기준점이 달라 같은 지역에 섞이면 국지 단차가 생기고,
# 서브타일 합이 부모보다 픽셀이 훨씬 많아(평균 3.7배) 부모를 남길 이득이 없다.
metas=sorted(glob.glob(f'{a.root}/tiles/*/tile_meta.json'))
submetas=sorted(glob.glob(f'{a.root}/subtiles/*/tile_meta.json'))
subdone=set()
for m in submetas:
    subdone.add(os.path.basename(os.path.dirname(m)))
drop=set()
spath=f'{a.root}/subtiles.json'
if os.path.exists(spath) and not a.no_subtiles:
    sj=json.load(open(spath))
    bypar={}
    for t in sj['tiles']: bypar.setdefault(t['parent'],[]).append(t['name'])
    for par,kids in bypar.items():
        have=[k for k in kids if k in subdone]
        if len(have)==len(kids): drop.add(par)
        elif have: LOG(f'   {par}: 서브타일 {len(have)}/{len(kids)}만 완료 → 부모 유지(혼재 주의)')
    if drop: LOG(f'4분할 완료로 제외되는 부모 타일 {len(drop)}개: {sorted(drop)}')

tiles=[]
for m in (metas if a.no_subtiles else metas+submetas):
    d=json.load(open(m))
    # 타일 식별은 디렉토리명으로 한다. region 문자열은 지역별 접두어(capital_/busan_)가 붙어
    # 특정 접두어만 벗기면 다른 지역에서 부모 제외가 조용히 실패한다.
    tname=os.path.basename(os.path.dirname(m))
    nm=d.get('region', tname)
    if tname in drop: continue
    if not d.get('ok'): LOG(f"skip {nm} (양호0)"); continue
    csv=glob.glob(os.path.join(os.path.dirname(m),'*_sbas.csv.gz'))
    if not csv: LOG(f"skip {nm} (csv 없음)"); continue
    d['csv']=csv[0]; tiles.append(d)
LOG(f'타일 {len(tiles)}개 로드 시작')
if len(tiles)==0: sys.exit('타일 없음')

DF={}
for d in tiles:
    df=pd.read_csv(d['csv'])
    DF[d['region']]=df
    LOG(f"  {d['region']}: {len(df):,}px  win={d['win']}")
names=[d['region'] for d in tiles]
dcols=[c for c in DF[names[0]].columns if c.startswith('D2')]
LOG(f'시계열 열 {len(dcols)}개')

# --- 중첩부 수집 ---
key={n:(DF[n]['row'].values.astype(np.int64)*100000+DF[n]['col'].values.astype(np.int64)) for n in names}
idx={n:{k:i for i,k in enumerate(key[n])} for n in names}
NT=len(names); ti={n:i for i,n in enumerate(names)}
# 중첩 연결: 정확히 같은 (row,col)이 양쪽에서 채택돼야만 인정하면, 채택률 낮은 타일이
# 네트워크에서 고립된다(t13/t34/t42/t43 사례). 변형장은 100m 규모에서 매끄러우므로
# KD-tree로 반경 내 최근접 픽셀끼리 묶는다. 인덱스는 한 번만 계산해 시계열 196열에 재사용.
from scipy.spatial import cKDTree
RAD = a.rad/111000.0
XY={n:np.c_[DF[n].Longitude.values, DF[n].Latitude.values] for n in names}
TREE={n:cKDTree(XY[n]) for n in names}
ROWC={n:DF[n]['row'].values.astype(np.float64) for n in names}
COLC={n:DF[n]['col'].values.astype(np.float64) for n in names}
allrow=np.concatenate([ROWC[n] for n in names]); allcol=np.concatenate([COLC[n] for n in names])
R0M, C0M = allrow.mean(), allcol.mean()
SC=1000.0
OV=[]; ov_px=0
for i in range(NT):
    for j in range(i+1,NT):
        ni,nj=names[i],names[j]
        d,jj=TREE[nj].query(XY[ni], distance_upper_bound=RAD)
        sel=np.isfinite(d)
        if sel.sum()<a.minov: continue
        ii=np.where(sel)[0]; jj=jj[sel]
        if len(ii)>a.maxov:
            k=np.linspace(0,len(ii)-1,a.maxov).astype(int); ii=ii[k]; jj=jj[k]
        X=(ROWC[ni][ii]-R0M)/SC; Y=(COLC[ni][ii]-C0M)/SC
        OV.append((i,j,ii,jj,X,Y)); ov_px+=len(ii)
        LOG(f'   연결 {ni}-{nj}: {len(ii):,}점')
ov_pairs=len(OV)
rhs_v=[DF[names[j]]['velocity'].values[jj]-DF[names[i]]['velocity'].values[ii] for i,j,ii,jj,X,Y in OV]
conn=set()
for i,j,*_ in OV: conn.add(names[i]); conn.add(names[j])
iso=[n for n in names if n not in conn]
if iso: LOG(f'★ 고립 타일(보정 불가, 자체 기준 유지): {iso}')
LOG(f'중첩 타일쌍 {ov_pairs}개, 대응점 {ov_px:,}')

if ov_pairs==0:
    LOG('연결 없음 → 보정 생략'); G=None; NP_=1
else:
    NP_=3 if a.plane else 1
    NR=ov_px; G=np.zeros((NR,NP_*NT),np.float64)
    r0=0
    for i,j,ii,jj,X,Y in OV:
        n=len(X); sl=slice(r0,r0+n)
        G[sl,NP_*i]=1.0; G[sl,NP_*j]=-1.0
        if NP_==3:
            G[sl,3*i+1]=X; G[sl,3*i+2]=Y; G[sl,3*j+1]=-X; G[sl,3*j+2]=-Y
        r0+=n
    anchor=int(np.argmax([len(DF[n]) for n in names]))
    LOG(f'앵커 타일 = {names[anchor]} (보정 0 고정)')
    # 연결 성분 판정: 앵커와 이어지지 않은 타일은 정규화항이 임의 값을 채워넣어
    # 조용히 틀린 보정이 들어간다(t03/t13이 서로만 연결돼 ±동일값을 나눠가진 사례).
    par_=list(range(NT))
    def find(x):
        while par_[x]!=x: par_[x]=par_[par_[x]]; x=par_[x]
        return x
    for i,j,*_ in OV:
        a_,b_=find(i),find(j)
        if a_!=b_: par_[a_]=b_
    root=find(anchor)
    linked=[k for k in range(NT) if find(k)==root]
    unlinked=[names[k] for k in range(NT) if find(k)!=root]
    if unlinked: LOG(f'★ 앵커 미연결 타일(자체 기준 유지): {unlinked}')
    LOG(f'앵커 성분에 연결된 타일 {len(linked)}/{NT}')
    keep=[c for c in range(NP_*NT) if (c//NP_)!=anchor and (c//NP_) in set(linked)]
    Gk=G[:,keep]
    GtG=Gk.T@Gk + 1e-6*np.eye(Gk.shape[1]); Ginv=np.linalg.inv(GtG)@Gk.T

def solve(rhs):
    par=np.zeros(NP_*NT)
    par[keep]=Ginv@rhs
    P=np.zeros((NT,3)); P[:,:NP_]=par.reshape(NT,NP_)
    return P

out=[]
if G is not None:
    Pv=solve(np.concatenate(rhs_v))
    LOG('속도 보정계수 (a mm/yr, b, c):')
    for n in names: LOG(f'   {n}: a={Pv[ti[n],0]:+.3f} b={Pv[ti[n],1]:+.4f} c={Pv[ti[n],2]:+.4f}')
    # 잔차
    res=(G@(Pv[:,:NP_].reshape(-1)))-np.concatenate(rhs_v)
    LOG(f'중첩 잔차 RMS {np.sqrt((res**2).mean()):.3f} mm/yr, 중앙 |res| {np.median(np.abs(res)):.3f}')
else:
    Pv=np.zeros((NT,3)); NP_=1

# 시계열 보정계수(동일 설계행렬, RHS만 교체)
Pts=None
if not a.no_ts and G is not None:
    Pts=np.zeros((len(dcols),NT,3))
    for c_i,c in enumerate(dcols):
        rhs=np.concatenate([DF[names[j]][c].values[jj]-DF[names[i]][c].values[ii]
                            for i,j,ii,jj,X,Y in OV])
        Pts[c_i]=solve(rhs)
        if (c_i+1)%40==0: LOG(f'   시계열 보정 {c_i+1}/{len(dcols)}')

for n in names:
    df=DF[n].copy(); i=ti[n]
    X=(df['row'].values-R0M)/SC; Y=(df['col'].values-C0M)/SC
    df['velocity']=df['velocity']+Pv[i,0]+Pv[i,1]*X+Pv[i,2]*Y
    if Pts is not None:
        for c_i,c in enumerate(dcols):
            df[c]=df[c]+Pts[c_i,i,0]+Pts[c_i,i,1]*X+Pts[c_i,i,2]*Y
    df['tile']=n
    df['tie']=('anchor' if ti[n]==(anchor if G is not None else -1) else ('linked' if (G is not None and ti[n] in set(linked)) else 'unlinked'))
    out.append(df)
M=pd.concat(out,ignore_index=True)
LOG(f'병합 전 {len(M):,}px (중첩 포함)')
M=M.sort_values('tcoh',ascending=False).drop_duplicates(subset=['row','col'],keep='first').reset_index(drop=True)
LOG(f'중첩 제거 후 {len(M):,}px')
M['velocity']=M['velocity'].round(4)
base=f'{a.out}/{a.region}_sbas_ps_v'
M.to_csv(base+'.csv.gz',index=False,compression='gzip')
LOG(f'저장 {base}.csv.gz')
try:
    import geopandas as gpd
    keepc=['Longitude','Latitude','velocity','tcoh','tile']
    gpd.GeoDataFrame(M[keepc],geometry=gpd.points_from_xy(M.Longitude,M.Latitude),crs=4326).to_file(base+'.shp')
    LOG(f'저장 {base}.shp (속도만, {len(M):,}px)')
except Exception as e:
    LOG('shp 저장 실패:',e)
json.dump({'n_px':int(len(M)),'n_tiles':len(names),'dates':len(dcols),
           'anchor':names[int(np.argmax([len(DF[n]) for n in names]))] if G is not None else None,
           'vel_range':[float(M.velocity.min()),float(M.velocity.max())]},
          open(f'{a.out}/{a.region}_merge_meta.json','w'),indent=2)
LOG('MERGE DONE')
