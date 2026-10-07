"""Step 7. DEM 기반 SAR 지형 시뮬레이션 + 실영상 멀티룩 + 2D 정합.

시뮬레이션 원리
  DEM 셀(면요소) 하나하나를 엄밀모델 geo2rdr 로 영상좌표 (line, sample) 에 떨어뜨리고,
  레이더가 보는 투영면적 A·cos(국지입사각) 을 그 위치의 bin 에 누적한다.
  * 센서를 향한 급경사(국지입사각 작음) -> 밝음, 등을 돌린 면 -> 0
  * 여러 면요소가 한 bin 에 겹치면(레이오버) 자연히 밝아진다
  * 차폐(그림자)는 계산하지 않는다 — 32° 입사에서 58° 이상 경사가 필요해 드물다
  DEM 은 30 m 이므로 bin 도 ~30 m 로 잡는다 (방위 27 line x 거리 16 sample).

정합
  sim 과 real 을 log/dB 로 만들고 저주파를 제거한 뒤 시프트를 바꿔가며 마스크된 피어슨 상관을 계산,
  피크를 포물선 적합으로 서브빈 추정한다.
  규약: real(l, s) ≈ sim(l − dl, s − ds)  →  모델이 (l', s') 에 예측한 지형이 실제로는 (l'+dl, s'+ds) 에 있음.
"""
import numpy as np
from scipy.ndimage import gaussian_filter
from geometry import geodetic_to_ecef, _unit


# --------------------------------------------------------------------------- 시뮬레이션
def simulate(rd, blk, bin_l, bin_s, n_lines, n_samples):
    """blk = DEM.block() 결과. 반환 dict: sim(투영면적 누적), cnt(면요소 수), hsum(높이합), 격자 크기"""
    P = geodetic_to_ecef(blk["lat"], blk["lon"], blk["h_ell"])
    t, R, line, samp = rd.geo2rdr(P)
    S = rd.orb.position(t)
    los = _unit(S - P)                                   # 지표 -> 위성
    cos_loc = np.sum(blk["n_ecef"] * los, axis=-1)       # 국지입사각의 cos
    w = blk["area"] * np.clip(cos_loc, 0.0, None)        # 레이더가 보는 투영면적

    nbl, nbs = n_lines // bin_l, n_samples // bin_s
    il = np.floor(line / bin_l).astype(int); is_ = np.floor(samp / bin_s).astype(int)
    ok = (il >= 0) & (il < nbl) & (is_ >= 0) & (is_ < nbs) & np.isfinite(w)
    flat = il[ok] * nbs + is_[ok]
    sim = np.bincount(flat, weights=w[ok], minlength=nbl * nbs).reshape(nbl, nbs)
    cnt = np.bincount(flat, minlength=nbl * nbs).reshape(nbl, nbs)
    hsum = np.bincount(flat, weights=blk["h_ortho"][ok], minlength=nbl * nbs).reshape(nbl, nbs)
    return dict(sim=sim, cnt=cnt, hmean=np.where(cnt > 0, hsum / np.maximum(cnt, 1), np.nan),
                nbl=nbl, nbs=nbs, bin_l=bin_l, bin_s=bin_s,
                line=line, samp=samp, cos_loc=cos_loc)


# --------------------------------------------------------------------------- 실영상 멀티룩
def multilook_intensity(sc, bin_l, bin_s, chunk_bins=100, verbose=True):
    """존재하는 전 라인을 (bin_l x bin_s) 로 멀티룩한 강도. 반환 (nbl, nbs) float32"""
    nbl = sc.n_avail // bin_l; nbs = sc.ncols // bin_s
    out = np.zeros((nbl, nbs), np.float32)
    for b0 in range(0, nbl, chunk_bins):
        b1 = min(nbl, b0 + chunk_bins)
        z, _ = sc.read_slc(b0 * bin_l, b1 * bin_l, 0, nbs * bin_s)
        I = (z.real ** 2 + z.imag ** 2).reshape(b1 - b0, bin_l, nbs, bin_s).mean(axis=(1, 3))
        out[b0:b1] = I
        if verbose:
            print(f"    멀티룩 {b1}/{nbl} bins", end="\r")
    if verbose:
        print()
    return out


# --------------------------------------------------------------------------- 정합
def _hp(img, sigma):
    return img - gaussian_filter(img, sigma)


def _peak2d(cc, i, j, half=2):
    """피크 주변 (2*half+1)^2 창에 2차 곡면을 최소제곱 적합해 서브빈 피크 위치 반환 (di, dj)."""
    H, W = cc.shape
    i0, i1 = max(0, i - half), min(H, i + half + 1); j0, j1 = max(0, j - half), min(W, j + half + 1)
    sub = cc[i0:i1, j0:j1]
    if sub.shape[0] < 3 or sub.shape[1] < 3 or not np.all(np.isfinite(sub)):
        return 0.0, 0.0
    yy, xx = np.mgrid[i0:i1, j0:j1]; y = (yy - i).ravel().astype(float); x = (xx - j).ravel().astype(float)
    A = np.stack([np.ones_like(x), x, y, x * x, x * y, y * y], 1)
    c, *_ = np.linalg.lstsq(A, sub.ravel(), rcond=None)
    _, cx, cy, cxx, cxy, cyy = c
    Hm = np.array([[2 * cxx, cxy], [cxy, 2 * cyy]])
    if np.linalg.det(Hm) <= 0 or cxx >= 0 or cyy >= 0:      # 극대가 아니면 포기
        return 0.0, 0.0
    dx, dy = np.linalg.solve(Hm, -np.array([cx, cy]))
    if abs(dx) > half or abs(dy) > half:
        return 0.0, 0.0
    return float(dy), float(dx)


def match(real_db, sim, mask, search, sigma=(4.0, 4.0), peak_half=2):
    """마스크된 피어슨 상관을 시프트 격자에서 계산. 반환 (dl, ds, r_peak, cc_surface, dls, dss)
    규약: real(l,s) ≈ sim(l-dl, s-ds).   sigma = 고역통과 가우시안 (라인bins, 샘플bins)"""
    sim_db = 10.0 * np.log10(np.where(sim > 0, sim, np.nan))
    a = _hp(np.nan_to_num(real_db, nan=np.nanmean(real_db)), sigma)
    b = _hp(np.nan_to_num(sim_db, nan=np.nanmean(sim_db)), sigma)
    m0 = mask & np.isfinite(real_db) & np.isfinite(sim_db)
    dls = np.arange(-search[0], search[0] + 1); dss = np.arange(-search[1], search[1] + 1)
    cc = np.full((len(dls), len(dss)), np.nan)
    H, W = a.shape
    for i, dl in enumerate(dls):
        for j, ds in enumerate(dss):
            # sim(l-dl, s-ds) 를 real 격자에 맞춰 잘라내기
            l0, l1 = max(0, dl), min(H, H + dl)
            s0, s1 = max(0, ds), min(W, W + ds)
            if l1 - l0 < 20 or s1 - s0 < 20:
                continue
            A = a[l0:l1, s0:s1]; B = b[l0 - dl:l1 - dl, s0 - ds:s1 - ds]
            M = m0[l0:l1, s0:s1] & m0[l0 - dl:l1 - dl, s0 - ds:s1 - ds]
            if M.sum() < 200:
                continue
            x = A[M]; y = B[M]
            x = x - x.mean(); y = y - y.mean()
            d = np.sqrt((x * x).sum() * (y * y).sum())
            cc[i, j] = (x * y).sum() / d if d > 0 else np.nan
    k = np.nanargmax(cc); i, j = np.unravel_index(k, cc.shape)
    di, dj = _peak2d(cc, i, j, peak_half)          # 2D 2차곡면 서브빈
    return float(dls[i]) + di, float(dss[j]) + dj, float(cc[i, j]), cc, dls, dss
