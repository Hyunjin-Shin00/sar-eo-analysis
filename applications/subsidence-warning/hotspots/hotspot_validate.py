#!/usr/bin/env python3
"""핫스팟 검증 — 허위양성인지 가린다.

CSK 로는 확인이 어렵다.  핫스팟 크기가 -2~-3 mm/yr 인데 CSK 는 0.72년밖에
못 봐서 누적 -1.5~-2.2 mm, 이는 CSK 잡음 1.75 mm 와 같은 수준이다.  확인
실패가 곧 허위를 뜻하지 않는다.  그래서 S1 자체의 독립 반쪽으로 가른다.

세 가지 시험:
  A 홀/짝 에폭 분할 — 같은 기간·같은 계절 커버리지로 독립 추정 2개.
    실제 지반신호면 둘 다 음수로 재현된다.  대기잡음이면 재현되지 않는다.
  B 격자 내 PS 산포로 구한 표준오差 → 군집 평균의 t 값.
  C 공간구조를 깬 귀무분포 — 같은 임계에서 우연히 생길 군집 수.
"""
import json
import sys

import numpy as np
from scipy import ndimage

sys.path.insert(0, '<DATA_ROOT>/CSK_PSInSAR/code')
from compare_all import CSK, S1, load_ps, reref
from hotspots import (CELL_M, K_SIGMA, MIN_CELLS, MPD_LAT, MPD_LON, NMIN_S1,
                      deplane, rsigma, to_grid)

H = json.load(open(f'{CSK}/results/compare/hotspots.json'))
G = np.load(f'{CSK}/results/compare/hotspot_grids.npz')
lab = G['lab']
lo0, la0 = float(G['lo0']), float(G['la0'])

P = load_ps(f'{S1}/results/seoul_s1_ps.npz')
reref(P)
day = P['day'].astype('datetime64[D]')
t = (day - day[0]).astype(int) / 365.25
kv = P['kv']


def secular(idx):
    A = np.column_stack([t[idx], np.ones(idx.size), np.cos(2 * np.pi * t[idx]),
                         np.sin(2 * np.pi * t[idx]), np.cos(4 * np.pi * t[idx]),
                         np.sin(4 * np.pi * t[idx])])
    sol, *_ = np.linalg.lstsq(A, P['disp'][:, idx].T, rcond=None)
    return sol[0] * kv


print('[A] 홀/짝 에폭 분할', flush=True)
n = t.size
odd, even = np.arange(0, n, 2), np.arange(1, n, 2)
vo, ve = secular(odd), secular(even)
bounds = (lo0, la0, lo0 + lab.shape[1] * CELL_M / MPD_LON,
          la0 + lab.shape[0] * CELL_M / MPD_LAT)
Go, _, _ = to_grid(P['lon'], P['lat'], vo, NMIN_S1, bounds)
Ge, _, _ = to_grid(P['lon'], P['lat'], ve, NMIN_S1, bounds)
ny0, nx0 = lab.shape
Go, Ge = Go[:ny0, :nx0], Ge[:ny0, :nx0]      # bounds 를 ceil 로 되살리면 1칸 넓어진다
Ro, Re = deplane(Go)[0], deplane(Ge)[0]
m = np.isfinite(Ro) & np.isfinite(Re)
print(f'    에폭 {len(odd)}/{len(even)}  전역 격자상관 r = '
      f'{np.corrcoef(Ro[m], Re[m])[0,1]:+.3f}', flush=True)

print('[B] 격자내 산포 → 군집 t 값', flush=True)
v = secular(np.arange(n))
ix = ((P['lon'] - lo0) * MPD_LON / CELL_M).astype(int)
iy = ((P['lat'] - la0) * MPD_LAT / CELL_M).astype(int)
ny, nx = lab.shape
ok = (ix >= 0) & (ix < nx) & (iy >= 0) & (iy < ny) & np.isfinite(v)
flat = iy[ok] * nx + ix[ok]
cnt = np.bincount(flat, minlength=ny * nx).astype(float)
s1 = np.bincount(flat, weights=v[ok], minlength=ny * nx)
s2 = np.bincount(flat, weights=v[ok] ** 2, minlength=ny * nx)
with np.errstate(invalid='ignore', divide='ignore'):
    var = (s2 - s1 ** 2 / cnt) / np.maximum(cnt - 1, 1)
var = var.reshape(ny, nx)
cnt2 = cnt.reshape(ny, nx)

print('[C] 공간구조 파괴 귀무분포 (100회)', flush=True)
R1 = G['R1']
fin = np.isfinite(R1)
vals = R1[fin]
thr = -K_SIGMA * rsigma(R1)
rng = np.random.default_rng(0)
null = []
for _ in range(100):
    sh = np.full_like(R1, np.nan)
    sh[fin] = rng.permutation(vals)
    l2, _ = ndimage.label(np.isfinite(sh) & (sh <= thr), structure=np.ones((3, 3)))
    sz = np.bincount(l2.ravel())[1:]
    null.append(int((sz >= MIN_CELLS).sum()))
null = np.array(null)
print(f'    관측 {H["n_hotspot"]}개  vs  귀무 {null.mean():.1f} ± {null.std():.1f} '
      f'(최대 {null.max()})', flush=True)

rows = []
for r in H['hotspots']:
    mm = lab == r['id'] if False else None
rec = {h['id']: h for h in H['hotspots']}
# lab 은 필터 전 번호라 다시 매칭: 면적·중심으로 찾는다
l2, nlab = ndimage.label(np.isfinite(R1) & (R1 <= thr), structure=np.ones((3, 3)))
cents = {}
for i in range(1, nlab + 1):
    mk = l2 == i
    if mk.sum() < MIN_CELLS:
        continue
    yy, xx = np.nonzero(mk)
    cents[i] = (lo0 + (xx.mean() + .5) * CELL_M / MPD_LON,
                la0 + (yy.mean() + .5) * CELL_M / MPD_LAT, mk)
for h in H['hotspots']:
    best = min(cents, key=lambda i: (cents[i][0] - h['lon']) ** 2 + (cents[i][1] - h['lat']) ** 2)
    mk = cents[best][2]
    o, e = float(np.nanmean(Ro[mk])), float(np.nanmean(Re[mk]))
    sem = float(np.sqrt(np.nansum(var[mk] / np.maximum(cnt2[mk], 1))) / mk.sum())
    h['odd'] = round(o, 2); h['even'] = round(e, 2)
    h['repro'] = bool(o < 0 and e < 0)
    h['sem'] = round(sem, 3)
    h['t'] = round(h['s1_anom'] / sem, 1) if sem > 0 else None
    rows.append(h)

rep = sum(h['repro'] for h in rows)
sig = sum((h['t'] or 0) <= -3 for h in rows)
neg = sum((h['csk_anom'] or 0) < 0 for h in rows)
print(f'\n[결과] 핫스팟 {len(rows)}개', flush=True)
print(f'    A 홀/짝 양쪽 음수 재현 : {rep}/{len(rows)}', flush=True)
print(f'    B t <= -3             : {sig}/{len(rows)}', flush=True)
print(f'    C 귀무 기대            : {null.mean():.1f}개', flush=True)
print(f'    CSK 부호일치(음수)     : {neg}/{len(rows)}  '
      f'(동전던지기면 {len(rows)/2:.0f})', flush=True)
try:
    from scipy.stats import binomtest
    print(f'    CSK 부호 이항검정 p    = {binomtest(neg, len(rows), 0.5, "greater").pvalue:.2g}',
          flush=True)
except Exception:
    pass

H['validation'] = dict(split_half_global_r=round(float(np.corrcoef(Ro[m], Re[m])[0, 1]), 3),
                       null_mean=float(null.mean()), null_std=float(null.std()),
                       null_max=int(null.max()), n_repro=rep, n_t3=sig, n_csk_neg=neg)
H['hotspots'] = rows
json.dump(H, open(f'{CSK}/results/compare/hotspots.json', 'w'), ensure_ascii=False, indent=1)
print('\n   ID 구       면적    S1이상  홀    짝    t      CSK   재현', flush=True)
for h in rows[:20]:
    print(f"   {h['id']:2d} {h['gu']:6s} {h['area_km2']:5.2f} {h['s1_anom']:+6.2f} "
          f"{h['odd']:+6.2f} {h['even']:+6.2f} {str(h['t']):>6s} "
          f"{str(h['csk_anom']):>6s}  {'O' if h['repro'] else 'X'}", flush=True)
