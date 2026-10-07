#!/usr/bin/env python3
# 채택률이 낮은 타일을 NxN으로 재분할한 창 목록 생성.
# 큰 창(427x740)에서는 snaphu 언랩 오류가 누적돼 tcoh가 무너진다(같은 지역이
# 100x300 창에서 33% 채택, 427x740 안에서는 0%). 분할하면 회복된다.
import json, argparse, os, glob, csv, numpy as np
os.environ.pop('PYTHONPATH', None)
from shapely.geometry import Point

p=argparse.ArgumentParser()
p.add_argument('--tiles', default='<WORK_ROOT>/CLAB_WIDE/capital_asc/tiles.json')
p.add_argument('--root',  default='<WORK_ROOT>/CLAB_WIDE/capital_asc')
p.add_argument('--split', type=int, default=2, help='각 타일을 split x split 로 분할')
p.add_argument('--ov', type=int, default=40, help='서브타일 간 중첩(px)')
p.add_argument('--maxrate', type=float, default=20.0, help='채택률(%%) 이 값 미만인 타일만 대상')
p.add_argument('--min-acc', type=int, default=1, help='사고가 이 수 이상인 타일만 대상')
p.add_argument('--out', required=True)
a=p.parse_args()

G=json.load(open(a.tiles))
info={t['name']:t for t in G['tiles']}
rows=[]
for t in G['tiles']:
    mp=f"{a.root}/tiles/{t['name']}/tile_meta.json"
    if not os.path.exists(mp): 
        print(f"  {t['name']}: 미완료 → 건너뜀"); continue
    m=json.load(open(mp))
    if not m.get('ok') or 'Npix' not in m:   # 채택 0건 타일은 메타에 Npix가 없다
        print(f"  {t['name']}: 채택 0 → 4분할"); rate=0.0
    else:
        rate=100.0*m['n']/m['Npix']
    if rate>=a.maxrate or t['n_acc']<a.min_acc:
        continue
    R0,R1,C0,C1=t['win']
    re_=np.linspace(R0,R1,a.split+1).astype(int); ce_=np.linspace(C0,C1,a.split+1).astype(int)
    for i in range(a.split):
        for j in range(a.split):
            r0=max(R0,re_[i]-a.ov); r1=min(R1,re_[i+1]+a.ov)
            c0=max(C0,ce_[j]-a.ov); c1=min(C1,ce_[j+1]+a.ov)
            rows.append(dict(name=f"{t['name']}s{i}{j}", parent=t['name'], win=[int(r0),int(r1),int(c0),int(c1)],
                             px=int((r1-r0)*(c1-c0)), parent_rate=round(rate,1), parent_acc=t['n_acc']))
    print(f"  {t['name']}: 채택 {rate:.1f}% 사고 {t['n_acc']}건 → {a.split*a.split}분할")
json.dump(dict(split=a.split, ov=a.ov, tiles=rows), open(a.out,'w'), indent=1)
tot=sum(r['px'] for r in rows)
print(f"\n서브타일 {len(rows)}개, 평균 {np.mean([r['px'] for r in rows]):,.0f}px (원본 대비 1/{a.split**2}), 총 {tot:,}px")
print(f"예상 메모리/서브타일 ~{np.max([r['px'] for r in rows])*52.4/1e6:.1f} GB")
