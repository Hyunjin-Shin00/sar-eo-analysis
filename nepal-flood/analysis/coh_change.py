#!/usr/bin/env python
"""
결맞음 변화 탐지 (Coherence Change Detection) — 2026 네팔 홍수

  Δcoh = coh(co-event pair) − coh(baseline pair)

두 쌍 모두 같은 궤도·같은 처리설정(looks/filter)으로 만든 것이라야 비교가 성립한다.
baseline 쌍은 "이 지역·이 계절의 정상 12일 결맞음"을 나타내므로, 몬순 강우·식생에
의한 상시 탈결맞음을 상쇄하고 사건에 기인한 성분만 남긴다.

usage: coh_change.py <TRACK> <baseline_pair> <coevent_pair>
  ex)  coh_change.py ASC_085 20260804_20260816 20260816_20260828
"""
import os, sys, json
os.environ.pop('PYTHONPATH', None)
os.environ.setdefault('PROJ_DATA', os.path.join(os.environ.get('CONDA_PREFIX', ''), 'share/proj'))
os.environ.setdefault('PROJ_LIB', os.environ['PROJ_DATA'])
import numpy as np
from osgeo import gdal
gdal.UseExceptions()

BASE = os.environ.get('DATA_ROOT', '<DATA_ROOT>')
SITES = [
    ('붕괴원점 (Langtang Lirung N)', 85.5194, 28.2765),
    ('Rasuwagadhi / Timure',        85.3792, 28.2810),
    ('Syabrubesi',                  85.3336, 28.1622),
    ('Dhunche',                     85.2971, 28.1004),
    ('Haku Besi / Mailung',         85.2400, 28.0200),
    ('Betrawati',                   85.1836, 27.9704),
    ('Trishuli-3A / Devighat',      85.1667, 27.8933),
    ('Bidur (Nuwakot)',             85.1500, 27.8700),
]
COH_MIN = 0.30   # baseline 결맞음이 이보다 낮으면 Δ 판정 불가(원래 탈결맞음 지역)
DROP    = -0.25  # 유의한 결맞음 저하 임계


def read_cor(path):
    """ISCE .cor 읽기. 2밴드(진폭,결맞음)면 2번째 밴드를 사용."""
    ds = gdal.Open(path)
    n = ds.RasterCount
    band = 2 if n >= 2 else 1
    arr = ds.GetRasterBand(band).ReadAsArray().astype(np.float32)
    gt, proj = ds.GetGeoTransform(), ds.GetProjection()
    return arr, gt, proj, n


def main():
    trk, base_pair, coev_pair = sys.argv[1], sys.argv[2], sys.argv[3]
    work = f'{BASE}/work/stack_{trk}/merged/interferograms'
    fb = f'{work}/{base_pair}/filt_fine.cor.geo'
    fc = f'{work}/{coev_pair}/filt_fine.cor.geo'
    for f in (fb, fc):
        if not os.path.exists(f):
            sys.exit(f'없음: {f}  (geocode_pairs.sh 먼저 실행)')

    cb, gt, proj, nb = read_cor(fb)
    cc, gt2, _, nc = read_cor(fc)
    print(f'baseline {base_pair}: shape={cb.shape} bands={nb}')
    print(f'coevent  {coev_pair}: shape={cc.shape} bands={nc}')
    if cb.shape != cc.shape or gt != gt2:
        sys.exit(f'격자 불일치 — 동일 bbox/looks로 지오코딩해야 함\n {gt}\n {gt2}')

    valid = (cb > 0) & (cc > 0) & np.isfinite(cb) & np.isfinite(cc)
    delta = np.where(valid, cc - cb, np.nan)
    # 판정 가능 영역: baseline이 충분히 결맞은 곳만
    judge = valid & (cb >= COH_MIN)
    loss  = judge & (delta <= DROP)

    print(f'\n유효화소            : {valid.sum():,} ({100*valid.sum()/valid.size:.1f}%)')
    print(f'판정가능(coh_base≥{COH_MIN}): {judge.sum():,} ({100*judge.sum()/max(valid.sum(),1):.1f}% of valid)')
    print(f'유의저하(Δ≤{DROP})   : {loss.sum():,} 화소')
    px_area = abs(gt[1] * gt[5]) * (111320 ** 2) * np.cos(np.deg2rad(28.1))
    print(f'  ≈ {loss.sum()*px_area/1e6:.2f} km²  (화소 ≈ {np.sqrt(px_area):.0f} m)')

    # --- 사이트별 통계 (반경 ~300m 창) ---
    print(f'\n{"지점":<32s} {"coh_base":>9s} {"coh_coev":>9s} {"Δcoh":>8s} {"판정":>10s}')
    print('-' * 74)
    rows = []
    win = max(1, int(round(300 / np.sqrt(px_area))))
    for name, lon, lat in SITES:
        c = int((lon - gt[0]) / gt[1]); r = int((lat - gt[3]) / gt[5])
        if not (0 <= r < cb.shape[0] and 0 <= c < cb.shape[1]):
            print(f'{name:<32s} {"—":>9s} {"—":>9s} {"—":>8s} {"범위밖":>10s}'); continue
        sl = (slice(max(0, r-win), r+win+1), slice(max(0, c-win), c+win+1))
        m = judge[sl]
        if m.sum() < 3:
            b = np.nanmedian(np.where(valid[sl], cb[sl], np.nan))
            print(f'{name:<32s} {b:9.3f} {"—":>9s} {"—":>8s} {"판정불가":>10s}')
            rows.append(dict(site=name, lon=lon, lat=lat, coh_base=float(b) if np.isfinite(b) else None,
                             coh_coev=None, dcoh=None, verdict='판정불가(기준결맞음낮음)'))
            continue
        b = float(np.median(cb[sl][m])); v = float(np.median(cc[sl][m])); d = v - b
        verdict = '유실/교란' if d <= DROP else ('경미' if d <= -0.12 else '변화없음')
        print(f'{name:<32s} {b:9.3f} {v:9.3f} {d:8.3f} {verdict:>10s}')
        rows.append(dict(site=name, lon=lon, lat=lat, coh_base=b, coh_coev=v, dcoh=d, verdict=verdict))

    # --- 산출물 ---
    outdir = f'{BASE}/analysis/{trk}'
    os.makedirs(outdir, exist_ok=True)
    drv = gdal.GetDriverByName('GTiff')
    for nm, arr in [('dcoh', delta),
                    ('coh_baseline', np.where(valid, cb, np.nan)),
                    ('coh_coevent', np.where(valid, cc, np.nan)),
                    ('loss_mask', loss.astype(np.float32))]:
        p = f'{outdir}/{nm}.tif'
        ds = drv.Create(p, cb.shape[1], cb.shape[0], 1, gdal.GDT_Float32,
                        options=['COMPRESS=DEFLATE', 'TILED=YES'])
        ds.SetGeoTransform(gt); ds.SetProjection(proj)
        ds.GetRasterBand(1).WriteArray(arr); ds.GetRasterBand(1).SetNoDataValue(float('nan'))
        ds = None
        print(f'  wrote {p}')
    json.dump(dict(track=trk, baseline_pair=base_pair, coevent_pair=coev_pair,
                   coh_min=COH_MIN, drop_thresh=DROP,
                   loss_pixels=int(loss.sum()), loss_km2=float(loss.sum()*px_area/1e6),
                   sites=rows),
              open(f'{outdir}/summary.json', 'w'), ensure_ascii=False, indent=1)
    print(f'  wrote {outdir}/summary.json')


if __name__ == '__main__':
    main()
