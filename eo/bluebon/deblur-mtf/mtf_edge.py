#!/usr/bin/env python3
"""경사 에지법(ISO 12233 계열)으로 원본/deblur 영상의 MTF 를 측정한다.

절차
  1) Canny + 확률적 Hough 로 긴 직선을 능동 검출한다. 무작위 샘플링으로는
     ALONG px 길이의 단일 직선 에지를 만날 확률이 매우 낮다
     (실측: 적합 RMS 중위값 10.8px = 사실상 무작위).
  2) 검출된 직선에 ROI 를 중심 정렬하고, 에지 위치 탐색을 ROI 중심 밴드로
     제한한다. 제한하지 않으면 행마다 인접 에지로 튀어 적합이 깨진다.
  3) 에지 직선 (a, b) 은 원본에서 한 번만 적합해 원본과 모든 alpha 결과에
     동일하게 재사용한다. deblur 는 에지를 옮기지 않으므로 기하를 고정해야
     공정한 비교가 된다.
  4) 각 픽셀을 에지 법선 좌표로 투영해 0.25px 빈에 누적 -> 초해상 ESF
  5) ESF 미분 -> LSF -> Hamming 창 -> FFT -> DC 정규화 -> MTF
     1차 차분 필터 자체의 감쇠 sinc(f*dx) 는 나눠 보정한다.

방향 정의
  near-vertical 에지(x 방향 gradient) -> across-track(x) MTF
  near-horizontal 에지(y 방향 gradient) -> along-track(y) MTF

usage: python3 mtf_edge.py [--n=12] [--band=2] [--dump]
"""
import sys
import warnings

import numpy as np
import rasterio
from rasterio.windows import Window

warnings.filterwarnings("ignore")

ROOT = "<WORK_ROOT>/working/debulr"
ALPHAS = ["1000", "3000", "5000"]
ACROSS, ALONG = 56, 80      # 에지 횡단 / 에지 따라가는 길이
BAND0 = 16                  # 1단 탐색 밴드(중심 고정, 넓게)
BAND1 = 3                   # 2단 탐색 밴드(1단 직선을 따라가며 좁게)
ANG_MIN, ANG_MAX = 2.0, 12.0  # 사용할 경사 범위(도). ISO 12233 은 ~5도 권장.
DX = 0.25                   # ESF 빈 폭 (4배 오버샘플)
PLAT = (5, 14)              # 평탄부로 볼 에지로부터의 거리 범위(px)
# 품질 게이트. 이 장면에는 ISO 규격 같은 균일 평탄부가 드물어 (평탄부 노이즈
# 중위값 236 DN vs 대비 중위값 173 DN) 현실적인 값으로 완화했다. 대신 에지
# 다수의 중위값과 IQR 을 함께 보고해 불확실성을 그대로 드러낸다.
G_RMS, G_CONTRAST, G_FLAT = 0.50, 300.0, 0.50


def src_path(b, tag):
    return (f"{ROOT}/input/MS{b}_DN_dark_rc_p.tiff" if tag == "orig"
            else f"{ROOT}/output/de_ms{b}_k31_i5_a{tag}.tiff")


def read_roi(path, x, y, w, h):
    with rasterio.open(path) as s:
        return s.read(1, window=Window(x, y, w, h)).astype(np.float64)


def _centroids(g, centers, band):
    """행별로 centers[i] +-band 안에서 |gradient| 최대점 주변 무게중심을 구한다."""
    h, wm1 = g.shape
    cen = np.full(h, np.nan)
    for i in range(h):
        lo_b = int(max(0, np.floor(centers[i] - band)))
        hi_b = int(min(wm1, np.ceil(centers[i] + band) + 1))
        if hi_b - lo_b < 3:
            continue
        seg = g[i, lo_b:hi_b]
        if seg.max() <= 0:
            continue
        pk = lo_b + int(seg.argmax())
        lo, hi = max(0, pk - 2), min(wm1, pk + 3)
        s_ = g[i, lo:hi]
        if s_.sum() <= 0:
            continue
        cen[i] = (s_ * np.arange(lo, hi)).sum() / s_.sum() + 0.5
    return cen


def _robust_fit(rows, vals, h):
    keep = np.ones(len(rows), bool)
    a = b = 0.0
    for _ in range(4):
        a, b = np.polyfit(rows[keep], vals[keep], 1)
        r = vals - (a * rows + b)
        s = max(1.4826 * np.median(np.abs(r - np.median(r))), 1e-3)
        new = np.abs(r) < 2.5 * s
        if new.sum() < h * 0.7 or (new == keep).all():
            break
        keep = new
    a, b = np.polyfit(rows[keep], vals[keep], 1)
    rms = float(np.sqrt(np.mean((vals[keep] - (a * rows[keep] + b)) ** 2)))
    return float(a), float(b), rms, keep


def fit_edge(roi):
    """2단 적합으로 에지 직선 x = a*row + b 를 구한다.

    1단은 중심 고정 밴드(넓게), 2단은 1단 직선을 따라가는 좁은 밴드.
    밴드를 중심에 고정하면 경사가 큰 에지가 ROI 양 끝에서 밴드를 벗어나
    적합이 깨진다 (80행 x tan9도 = 12.7px 이동).
    """
    h, w = roi.shape
    g = np.abs(np.diff(roi, axis=1))                  # (h, w-1)
    c0 = (w - 1) / 2.0

    cen = _centroids(g, np.full(h, c0), BAND0)
    ok = ~np.isnan(cen)
    if ok.sum() < h * 0.9:
        return None
    rows = np.arange(h)[ok]
    a, b, _, _ = _robust_fit(rows, cen[ok], h)

    # 2단: 1단 직선을 따라가는 좁은 밴드로 재탐색
    cen = _centroids(g, a * np.arange(h) + b, BAND1)
    ok = ~np.isnan(cen)
    if ok.sum() < h * 0.9:
        return None
    rows = np.arange(h)[ok]
    a, b, rms, keep = _robust_fit(rows, cen[ok], h)

    # 에지 법선 거리 기준 평탄부 통계
    rr, cc = np.mgrid[0:h, 0:w]
    d = cc - (a * rr + b)
    left = (d <= -PLAT[0]) & (d >= -PLAT[1])
    right = (d >= PLAT[0]) & (d <= PLAT[1])
    if left.sum() < 100 or right.sum() < 100:
        return None
    lv, rv = roi[left], roi[right]
    contrast = abs(rv.mean() - lv.mean())
    flat = max(lv.std(), rv.std())
    return dict(a=float(a), b=float(b), rms=rms,
                contrast=float(contrast), flat=float(flat),
                frac=float(keep.sum() / len(keep)))


def esf(roi, a, b):
    """에지 법선 좌표로 투영해 초해상 ESF 를 만든다."""
    h, w = roi.shape
    rr, cc = np.mgrid[0:h, 0:w]
    d = (cc - (a * rr + b)).ravel()
    lim = w / 2 - 2 - abs(a) * h / 2
    if lim < 8:
        return None
    edges = np.arange(-lim, lim + DX, DX)
    n = len(edges) - 1
    idx = np.digitize(d, edges) - 1
    v = roi.ravel()
    m = (idx >= 0) & (idx < n)
    cnt = np.bincount(idx[m], minlength=n)
    if cnt.min() < 1:
        return None
    acc = np.bincount(idx[m], weights=v[m], minlength=n)
    return acc / cnt


def mtf_from_esf(prof):
    """ESF -> LSF -> MTF. 1차 차분 필터 응답 보정 포함."""
    lsf = np.diff(prof)
    if lsf.sum() < 0:
        lsf = -lsf
    lsf = lsf - np.median(np.concatenate([lsf[:6], lsf[-6:]]))
    n = len(lsf)
    F = np.abs(np.fft.rfft(lsf * np.hamming(n)))
    if F[0] <= 0:
        return None
    F = F / F[0]
    f = np.fft.rfftfreq(n, d=DX)
    corr = np.sinc(f * DX)
    F = np.where(corr > 0.05, F / corr, np.nan)
    return f, F


def overshoot(prof):
    """ESF 의 오버슈트(링잉) 비율 %. 계단 진폭 대비 최대 초과량."""
    p = prof if prof[-1] > prof[0] else prof[::-1]
    k = max(4, len(p) // 10)
    lo, hi = p[:k].mean(), p[-k:].mean()
    amp = hi - lo
    if amp <= 0:
        return float("nan")
    return float(max(0.0, (p.max() - hi)) / amp * 100)


def summarize(f, F):
    nyq = float(np.interp(0.5, f, F))
    q = float(np.interp(0.25, f, F))
    # MTF50: 처음 0.5 를 하향 교차하는 지점 (노이즈로 재상승해도 최초값 사용)
    m50 = float("nan")
    for i in range(1, len(f)):
        if F[i] < 0.5 <= F[i - 1]:
            f0, f1, y0, y1 = f[i - 1], f[i], F[i - 1], F[i]
            m50 = float(f0 + (0.5 - y0) * (f1 - f0) / (y1 - y0))
            break
    return nyq, q, m50


def detect_steps(path, vertical, block=2400, min_contrast=300.0):
    """계단 에지 후보를 직접 겨냥해 찾는다.

    Canny+Hough 는 얇은 선형 지물(도로, 경계선)을 대량으로 잡아내는데, 그런
    지물은 양쪽 평탄부 레벨이 같아 MTF 측정에 쓸 수 없다 (실측 대비 중위값
    3.3 DN). 그래서 '에지로부터 PLAT 거리의 양측 평균 차이'를 이미지 전체에서
    누적합으로 직접 계산하고, 그 값이 큰 지점만 후보로 삼는다.

    반환: [(cx, cy, score), ...] score 내림차순
    """
    from scipy.ndimage import maximum_filter, uniform_filter1d

    p0, p1 = PLAT
    npl = p1 - p0 + 1
    with rasterio.open(path) as ds:
        W, H = ds.width, ds.height
        cands = []
        for y0 in range(0, H, block):
            h = min(block + ALONG, H - y0)
            if h < ALONG + 2 * p1:
                break
            a = ds.read(1, window=Window(0, y0, W, h)).astype(np.float64)
            img = a if vertical else a.T
            hh, ww = img.shape
            if ww < 2 * p1 + 4:
                continue
            # x 방향 누적합으로 평탄부 평균/분산
            C = np.zeros((hh, ww + 1))
            C2 = np.zeros((hh, ww + 1))
            np.cumsum(img, axis=1, out=C[:, 1:])
            np.cumsum(img ** 2, axis=1, out=C2[:, 1:])

            def win(lo, hi):
                """각 x 에 대해 [x+lo, x+hi] 구간의 평균, 표준편차."""
                n = hi - lo + 1
                s = np.full((hh, ww), np.nan)
                q = np.full((hh, ww), np.nan)
                xs = np.arange(ww)
                v = (xs + lo >= 0) & (xs + hi < ww)
                i0 = xs[v] + lo
                i1 = xs[v] + hi + 1
                s[:, v] = (C[:, i1] - C[:, i0]) / n
                q[:, v] = (C2[:, i1] - C2[:, i0]) / n - s[:, v] ** 2
                return s, np.sqrt(np.maximum(q, 0))

            L, sL = win(-p1, -p0)
            R, sR = win(p0, p1)
            d = R - L
            score = np.abs(d) / (1.0 + np.maximum(sL, sR))
            score[np.abs(d) < min_contrast] = 0
            score = np.nan_to_num(score)
            # 에지 방향(y)으로 연장된 지물을 선호
            score = uniform_filter1d(score, size=ALONG // 2, axis=0,
                                     mode="nearest")
            mx = maximum_filter(score, size=(ALONG // 2, 2 * p1 + 1))
            ys, xs = np.nonzero((score == mx) & (score > 0))
            for yy, xx in zip(ys, xs):
                gy = y0 + (yy if vertical else xx)
                gx = (xx if vertical else yy)
                cands.append((gx, gy, float(score[yy, xx])))
            del C, C2, L, R, sL, sR, d, score, mx
    cands.sort(key=lambda t: -t[2])
    # 공간적 비최대 억제
    out, taken = [], []
    for cx, cy, s in cands:
        if all(abs(cx - tx) > 30 or abs(cy - ty) > 60 for tx, ty in taken):
            out.append((cx, cy, s))
            taken.append((cx, cy))
        if len(out) >= 3000:
            break
    return out


def detect_lines(path, vertical, block=3000):
    import cv2
    with rasterio.open(path) as s:
        W, H = s.width, s.height
    segs = []
    minlen = int(ALONG * 0.8)
    for y0 in range(0, H, block):
        h = min(block, H - y0)
        if h < ALONG * 2:
            break
        a = read_roi(path, 0, y0, W, h)
        lo, hi = np.percentile(a, (1, 99))
        u8 = (np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1) * 255).astype(np.uint8)
        e = cv2.Canny(u8, 15, 55, L2gradient=True)
        ls = cv2.HoughLinesP(e, 1, np.pi / 720, threshold=35,
                             minLineLength=minlen, maxLineGap=6)
        if ls is None:
            continue
        for x1, y1, x2, y2 in ls[:, 0]:
            dx, dy = float(x2 - x1), float(y2 - y1)
            if np.hypot(dx, dy) < minlen:
                continue
            if vertical:
                if abs(dy) < 1e-6:
                    continue
                ang = np.degrees(np.arctan(abs(dx / dy)))
            else:
                if abs(dx) < 1e-6:
                    continue
                ang = np.degrees(np.arctan(abs(dy / dx)))
            if not (ANG_MIN - 1 <= ang <= ANG_MAX + 2):
                continue
            segs.append((( x1 + x2) / 2, y0 + (y1 + y2) / 2,
                         np.hypot(dx, dy), ang))
    segs.sort(key=lambda t: -t[2])
    return segs


def find_rois(band, vertical, want, verbose=True):
    path = src_path(band, "orig")
    w_, h_ = (ACROSS, ALONG) if vertical else (ALONG, ACROSS)
    segs = detect_steps(path, vertical)
    ds = rasterio.open(path)
    W, H = ds.width, ds.height

    def rd(x, y, w, h):
        return ds.read(1, window=Window(x, y, w, h)).astype(np.float64)

    if verbose:
        print(f"  계단 에지 후보 {len(segs)}개")
    out = []
    for cx, cy, _s in segs:
        x = int(round(cx - w_ / 2))
        y = int(round(cy - h_ / 2))
        fit = None
        # 후보 좌표가 정확하지 않으므로 적합된 에지 위치로 재중심화한다
        for _pass in range(3):
            if not (10 <= x <= W - w_ - 10 and 10 <= y <= H - h_ - 10):
                fit = None
                break
            roi = rd(x, y, w_, h_)
            if (roi <= 0).any():
                fit = None
                break
            r = roi if vertical else roi.T
            fit = fit_edge(r)
            if fit is None:
                break
            # ROI 중심 행에서의 에지 위치
            mid = fit["a"] * (ALONG - 1) / 2 + fit["b"]
            shift = int(round(mid - (ACROSS - 1) / 2))
            if shift == 0:
                break
            if vertical:
                x += shift
            else:
                y += shift
        if fit is None:
            continue
        ang = np.degrees(np.arctan(abs(fit["a"])))
        if not (ANG_MIN <= ang <= ANG_MAX):
            continue
        if fit["rms"] > G_RMS:
            continue
        if fit["contrast"] < G_CONTRAST or fit["flat"] > fit["contrast"] * G_FLAT:
            continue
        mid = fit["a"] * (ALONG - 1) / 2 + fit["b"]
        if abs(mid - (ACROSS - 1) / 2) > 2.0:
            continue
        out.append(dict(x=x, y=y, ang=ang, score=fit["contrast"] /
                        (fit["flat"] + 1e-6) / (1 + fit["rms"]), **fit))
    out.sort(key=lambda d: -d["score"])
    sel = []
    for c in out:
        if all(abs(c["x"] - s2["x"]) > 100 or abs(c["y"] - s2["y"]) > 200
               for s2 in sel):
            sel.append(c)
        if len(sel) >= want:
            break
    return sel


def main():
    opt = {}
    for a in sys.argv[1:]:
        if a.startswith("--"):
            k, _, v = a[2:].partition("=")
            opt[k] = v or "1"
    want = int(opt.get("n", 12))
    sb = int(opt.get("band", 2))

    res, roiset = {}, {}
    for vertical, dirn in ((True, "across-track(x)"), (False, "along-track(y)")):
        print(f"\n=== {dirn}: MS{sb} 에서 경사 에지 탐색 ===")
        rois = find_rois(sb, vertical, want)
        print(f"  품질 조건 통과 {len(rois)}곳")
        for r in rois:
            print(f"   x={r['x']:5d} y={r['y']:6d} 각도={r['ang']:5.2f}deg "
                  f"대비={r['contrast']:6.0f}DN 평탄노이즈={r['flat']:5.0f}DN "
                  f"적합RMS={r['rms']:.3f}px")
        if not rois:
            continue
        roiset[dirn] = rois
        w_, h_ = (ACROSS, ALONG) if vertical else (ALONG, ACROSS)
        for b in (1, 2, 3):
            for tag in ["orig"] + ALPHAS:
                acc = []
                for r in rois:
                    roi = read_roi(src_path(b, tag), r["x"], r["y"], w_, h_)
                    rr = roi if vertical else roi.T
                    p = esf(rr, r["a"], r["b"])       # 기하는 원본 적합값 재사용
                    if p is None:
                        continue
                    out = mtf_from_esf(p)
                    if out is None:
                        continue
                    f, F = out
                    if np.isnan(F[f <= 0.5]).any():
                        continue
                    acc.append(summarize(f, F) + (overshoot(p),))
                if acc:
                    v = np.array(acc)
                    res[(dirn, b, tag)] = (np.nanmedian(v, axis=0),
                                           np.nanpercentile(v, 25, axis=0),
                                           np.nanpercentile(v, 75, axis=0),
                                           len(acc))

    print(f"\n\n=== 경사 에지 MTF 측정 (에지 다수의 중위값, Nyquist=0.5 cyc/px) ===")
    print("MTF@Nyq / MTF@0.25 는 [p25-p75] 범위 병기, 오버슈트는 ESF 링잉 %\n")
    hdr = (f"{'방향':<16s} {'밴드':<5s} {'영상':<7s} {'MTF@Nyq':>22s} "
           f"{'MTF@0.25':>22s} {'MTF50':>7s} {'오버슈트':>9s} {'n':>3s}")
    print(hdr)
    print("-" * 108)
    for dirn in ("across-track(x)", "along-track(y)"):
        for b in (1, 2, 3):
            for tag in ["orig"] + ALPHAS:
                k = (dirn, b, tag)
                if k not in res:
                    continue
                md, p25, p75, n = res[k]
                lab = "원본" if tag == "orig" else f"a={tag}"
                print(f"{dirn:<16s} MS{b:<4d} {lab:<7s} "
                      f"{md[0]:7.4f} [{p25[0]:.3f}-{p75[0]:.3f}] "
                      f"{md[1]:7.4f} [{p25[1]:.3f}-{p75[1]:.3f}] "
                      f"{md[2]:7.4f} {md[3]:8.1f}% {n:3d}")
            print()


if __name__ == "__main__":
    main()
