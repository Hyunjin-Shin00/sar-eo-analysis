#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
관측영상 최종화: dark/PRNU 보정 -> 밴드 정합 -> 공통 crop -> 좌우 flip -> 저장.

두 정합 버전을 모두 생성/저장:
  (T) 평행이동(translation)     : *_obs_reg.tiff
  (J) jitter 보정(along-track)  : *_obs_regjit.tiff

정합 설계(요청 반영):
  - 촬영 순서 = [1,2,3,0,7,4,5,6] (Blue,Green,Red,PAN,NIR,RE1,RE2,RE3).
  - 인접쌍 subpixel shift(phase_cross_correlation, high-pass, upsample=10) -> 체인 누적.
  - 최적 기준밴드(anchor) 자동선택(최대 변위 최소).
  - (T) 순수 평행이동(scipy.ndimage.shift).
  - (J) 평행이동 후 남는 자세지터 잔차를 row-의존 매끄러운 곡선으로 추정 ->
        (chain translation + 잔차곡선) 을 '단일 remap' 으로 원본 보정영상에 적용(공통 anchor 격자).
        * 강한 스무딩 + 단일 anchor 기준 => 밴드별 국소 warp 로 인한 공간일치 저하 없음.

phase_cross_correlation(ref, mov): shift(mov, s) 하면 ref 에 정렬 (기존 파이프라인과 동일 규약).
"""
import os
import sys
import math
import argparse
import numpy as np
import tifffile
from skimage.registration import phase_cross_correlation
from scipy.ndimage import shift as nd_shift
from scipy.ndimage import gaussian_filter, gaussian_filter1d, map_coordinates, median_filter

OUT_DIR  = "/mnt/e/bkchoi/prep/data/correction_ref_260606"
TEST_DIR = os.path.join(OUT_DIR, "test_260616")
OBS_DIR  = "/mnt/e/bkchoi/prep/data/260616_193632"
OBS_STEM = "260616_193632"

CAP_ORDER   = [1, 2, 3, 0, 7, 4, 5, 6]
BAND_NAME   = {0: "PAN", 1: "Blue", 2: "Green", 3: "Red", 4: "RE1", 5: "RE2", 6: "RE3", 7: "NIR"}
MS_BANDS    = [1, 2, 3, 4, 5, 6, 7]
UPSAMPLE    = 10
SHIFT_ORDER = 1
SAVE_PAN    = True

# jitter 잔차 추정 파라미터
JIT_WIN   = 1200     # along-track 윈도우 높이(rows)
JIT_STEP  = 400      # 윈도우 스텝(rows)
JIT_SMTH  = 500.0    # 잔차곡선 gaussian 스무딩 sigma(rows) — 강한 스무딩(밴드간 일치 보존)
XC_FRAC   = (0.12, 0.88)   # (row 모드) 텍스처 참고용
NX_BLK    = 7        # (collin 모드) across-track 블록 수 — 컬럼 선형(회전/keystone) 회귀용


def prep_hp(im, sigma=3.0):
    x = im.astype(np.float64)
    return x - gaussian_filter(x, sigma=sigma)


def pcc(ref, mov):
    s, err, _ = phase_cross_correlation(prep_hp(ref), prep_hp(mov), upsample_factor=UPSAMPLE)
    return np.array(s, dtype=np.float64), float(err)


def load_corrected(n):
    raw = tifffile.imread(os.path.join(OBS_DIR, f"{OBS_STEM}_{n}_gray.tiff")).astype(np.float32)
    if n == 0:
        return raw
    dark = tifffile.imread(os.path.join(OUT_DIR, f"MS{n}_dark_ref.tiff")).astype(np.float32).ravel()
    prnu = np.loadtxt(os.path.join(OUT_DIR, f"MS{n}_residul_prnu_coef.dat")).astype(np.float32)
    return (raw - dark[None, :]) * prnu[None, :]


# ---------------------------------------------------------------------------
# 잔차(자세지터+회전) 필드 추정 + 2D warp
# ---------------------------------------------------------------------------
def _smooth_over_rows(rc, val, H):
    """표본(rc,val) -> 전 row 보간 + 강한 gaussian 스무딩."""
    val = median_filter(np.asarray(val, float), size=3)
    rows = np.arange(H)
    c = np.interp(rows, rc, val, left=val[0], right=val[-1])
    return gaussian_filter1d(c, JIT_SMTH)


def residual_field(anchor_img, band_img, H, W, mode):
    """평행이동 정합 후 남는 잔차를 row(+column) 함수로 추정.
       반환: ay(H), ax(H), by(H), bx(H)
         dy(r,c) = ay(r) + by(r)*(c-c0),  dx(r,c) = ax(r) + bx(r)*(c-c0)
       mode='row'    : by=bx=0 (along-track 지터만)
       mode='collin' : across-track 선형(회전 yaw + keystone) 포함."""
    c0 = W / 2.0
    ahp = prep_hp(anchor_img)
    bhp = prep_hp(band_img)
    gstd = ahp.std()
    if mode == "collin":
        xs = np.linspace(0, W, NX_BLK + 1).astype(int)          # across-track 블록
        xcen = np.array([(xs[j] + xs[j + 1]) / 2 for j in range(NX_BLK)])
    rc, AY, AX, BY, BX = [], [], [], [], []
    r = 0
    while r + JIT_WIN <= H:
        rmid = r + JIT_WIN / 2
        if mode == "row":
            at = ahp[r:r + JIT_WIN]; bt = bhp[r:r + JIT_WIN]
            if at.std() >= gstd * 0.5:
                s, _, _ = phase_cross_correlation(at, bt, upsample_factor=UPSAMPLE)
                if np.max(np.abs(s)) <= 6.0:
                    rc.append(rmid); AY.append(s[0]); AX.append(s[1]); BY.append(0.0); BX.append(0.0)
        else:  # collin: 블록별 추정 후 컬럼 선형회귀
            cols_c, dyb, dxb = [], [], []
            for j in range(NX_BLK):
                at = ahp[r:r + JIT_WIN, xs[j]:xs[j+1]]
                bt = bhp[r:r + JIT_WIN, xs[j]:xs[j+1]]
                if at.std() < gstd * 0.4:
                    continue
                s, _, _ = phase_cross_correlation(at, bt, upsample_factor=UPSAMPLE)
                if np.max(np.abs(s)) <= 8.0:
                    cols_c.append(xcen[j] - c0); dyb.append(s[0]); dxb.append(s[1])
            if len(cols_c) >= 3:                                 # 컬럼 선형회귀(회전/keystone)
                cc = np.array(cols_c)
                py = np.polyfit(cc, dyb, 1); px = np.polyfit(cc, dxb, 1)
                rc.append(rmid); AY.append(py[1]); BY.append(py[0]); AX.append(px[1]); BX.append(px[0])
        r += JIT_STEP
    rc = np.array(rc)
    if len(rc) < 3:
        z = np.zeros(H); return z, z, z.copy(), z.copy()
    ay = _smooth_over_rows(rc, AY, H); ax = _smooth_over_rows(rc, AX, H)
    by = _smooth_over_rows(rc, BY, H); bx = _smooth_over_rows(rc, BX, H)
    return ay, ax, by, bx


def field_warp(img, add_dy, add_dx, ay, ax, by, bx):
    """단일 remap: output[r,c] = img[r - tot_dy(r,c), c - tot_dx(r,c)]  (bilinear).
       tot_dy = add_dy + ay(r) + by(r)*(c-c0);  tot_dx = add_dx + ax(r) + bx(r)*(c-c0)."""
    H, W = img.shape
    c0 = W / 2.0
    cols = np.arange(W, dtype=np.float32)[None, :]
    rows = np.arange(H, dtype=np.float32)[:, None]
    dc = cols - c0
    tot_dy = (add_dy + ay[:, None]) + by[:, None] * dc          # (H,W)
    tot_dx = (add_dx + ax[:, None]) + bx[:, None] * dc
    r_coord = rows - tot_dy.astype(np.float32)
    c_coord = cols - tot_dx.astype(np.float32)
    return map_coordinates(img, [r_coord, c_coord], order=1, mode="constant", cval=np.nan)


# ---------------------------------------------------------------------------
def valid_bounds(shifts, H, W):
    top = 0; bot = H - 1; left = 0; right = W - 1
    for (sy, sx) in shifts:
        top   = max(top,  max(0, math.ceil(sy)))
        bot   = min(bot,  (H - 1) + min(0, math.floor(sy)))
        left  = max(left, max(0, math.ceil(sx)))
        right = min(right, (W - 1) + min(0, math.floor(sx)))
    return top, bot, left, right


def main(focus_bands, suffix, jitter_mode):
    os.makedirs(TEST_DIR, exist_ok=True)
    print("=== finalize (focus=%s, suffix='%s', jitter=%s) ===" % (
        "-".join(BAND_NAME[b] for b in focus_bands), suffix, jitter_mode), flush=True)
    print("loading + radiometric correction ...", flush=True)
    img = {n: load_corrected(n) for n in CAP_ORDER}
    H, W = img[CAP_ORDER[0]].shape

    # 1) 인접쌍 shift 체인
    print("estimating adjacent-pair shifts (capture order) ...", flush=True)
    a = []
    for k in range(len(CAP_ORDER) - 1):
        s, err = pcc(img[CAP_ORDER[k]], img[CAP_ORDER[k + 1]])
        a.append(s)
        print("   %-5s <- %-5s : (dy=%.3f, dx=%.3f)" % (
            BAND_NAME[CAP_ORDER[k]], BAND_NAME[CAP_ORDER[k + 1]], s[0], s[1]), flush=True)
    S = {CAP_ORDER[0]: np.array([0.0, 0.0])}
    acc = np.array([0.0, 0.0])
    for k in range(len(CAP_ORDER) - 1):
        acc = acc + a[k]; S[CAP_ORDER[k + 1]] = acc.copy()

    # 2) 최적 anchor : focus_bands 내에서 focus_bands 최대변위 최소화
    def maxdisp(anc): return max(np.hypot(*(S[b] - S[anc])) for b in focus_bands)
    anchor = min(focus_bands, key=maxdisp)
    print("\n*** optimal reference (anchor) = %s (focus max disp %.2f px) ***" % (
        BAND_NAME[anchor], maxdisp(anchor)), flush=True)
    apply_shift = {b: (S[b] - S[anchor]) for b in CAP_ORDER}

    # =========================================================
    # (T) 평행이동 버전
    # =========================================================
    top, bot, left, right = valid_bounds([apply_shift[b] for b in CAP_ORDER], H, W)
    print("[T] common crop rows[%d:%d] cols[%d:%d]" % (top, bot + 1, left, right + 1), flush=True)
    regT = {}
    for b in CAP_ORDER:
        sy, sx = apply_shift[b]
        sh = img[b] if (abs(sy) < 1e-6 and abs(sx) < 1e-6) else \
             nd_shift(img[b], shift=(sy, sx), order=SHIFT_ORDER, mode="constant", cval=0.0, prefilter=False)
        regT[b] = sh[top:bot + 1, left:right + 1]

    # =========================================================
    # (J) jitter(+회전) 보정: 잔차필드 추정(regT 기준) -> 원본에 (chain+필드) 단일 remap
    # =========================================================
    print("[J] estimating residual field (mode=%s) ..." % jitter_mode, flush=True)
    Hc, Wc = regT[anchor].shape
    def to_full(c):
        f = np.zeros(H)
        if len(c) == 0: return f
        f[top:top + len(c)] = c; f[:top] = c[0]; f[top + len(c):] = c[-1]
        return f
    fields = {}
    for b in CAP_ORDER:
        if b == anchor:
            z = np.zeros(H); fields[b] = (z, z, z.copy(), z.copy()); continue
        ay_c, ax_c, by_c, bx_c = residual_field(regT[anchor], regT[b], Hc, Wc, jitter_mode)
        fields[b] = (to_full(ay_c), to_full(ax_c), to_full(by_c), to_full(bx_c))
        print("   %-5s: ay[%.2f,%.2f] by(rot)[%+.2e,%+.2e] ax[%.2f,%.2f] bx[%+.2e,%+.2e]" % (
            BAND_NAME[b], ay_c.min(), ay_c.max(), by_c.min(), by_c.max(),
            ax_c.min(), ax_c.max(), bx_c.min(), bx_c.max()), flush=True)

    # 공통 crop margin (chain + 필드 최대변위, 컬럼항 by*W/2 포함)
    halfW = W / 2.0
    def bmax(b):
        ay, ax, by, bx = fields[b]
        mdy = np.max(np.abs(apply_shift[b][0] + ay) + np.abs(by) * halfW)
        mdx = np.max(np.abs(apply_shift[b][1] + ax) + np.abs(bx) * halfW)
        return mdy, mdx
    max_dy = max(bmax(b)[0] for b in CAP_ORDER)
    max_dx = max(bmax(b)[1] for b in CAP_ORDER)
    mY = int(math.ceil(max_dy)) + 1; mX = int(math.ceil(max_dx)) + 1
    print("[J] common crop margin: rows +-%d cols +-%d" % (mY, mX), flush=True)
    regJ = {}
    for b in CAP_ORDER:
        ay, ax, by, bx = fields[b]
        if b == anchor:
            w = img[b]
        else:
            w = field_warp(img[b], apply_shift[b][0], apply_shift[b][1], ay, ax, by, bx)
        regJ[b] = w[mY:H - mY, mX:W - mX]

    # 3) 검증(잔차 재측정): T vs J
    print("\n[verify] residual RMS to anchor (%s):" % BAND_NAME[anchor], flush=True)
    residT = residual_check(regT, anchor, tag="T")
    residJ = residual_check(regJ, anchor, tag="J")

    # 4) flip + 저장
    for d in (regT, regJ):
        for b in CAP_ORDER:
            d[b] = np.fliplr(d[b])
    for n in MS_BANDS:
        tifffile.imwrite(os.path.join(TEST_DIR, f"MS{n}_obs_reg{suffix}.tiff"), regT[n].astype(np.float32))
        tifffile.imwrite(os.path.join(TEST_DIR, f"MS{n}_obs_regjit{suffix}.tiff"), regJ[n].astype(np.float32))
    if SAVE_PAN:
        tifffile.imwrite(os.path.join(TEST_DIR, f"PAN_obs_reg{suffix}.tiff"), regT[0].astype(np.float32))
        tifffile.imwrite(os.path.join(TEST_DIR, f"PAN_obs_regjit{suffix}.tiff"), regJ[0].astype(np.float32))

    write_shift_csv(anchor, apply_shift, (top, bot, left, right), residT, residJ, suffix)
    make_rgb_preview(regT, regJ, anchor, suffix)
    print("\nDONE. outputs in", TEST_DIR)


def residual_check(reg, anchor, ny=5, nx=4, tag=""):
    Ahp = prep_hp(reg[anchor]); H, W = Ahp.shape
    ys = np.linspace(0, H, ny + 1).astype(int); xs = np.linspace(0, W, nx + 1).astype(int)
    tile_std = np.array([[np.nan_to_num(Ahp[ys[i]:ys[i+1], xs[j]:xs[j+1]]).std()
                          for j in range(nx)] for i in range(ny)])
    thr = np.median(tile_std) * 0.5
    per_band = {}
    for b in reg:
        if b == anchor: continue
        bhp = prep_hp(reg[b]); rr = []
        for i in range(ny):
            for j in range(nx):
                if tile_std[i, j] < thr: continue
                at = np.nan_to_num(Ahp[ys[i]:ys[i+1], xs[j]:xs[j+1]])
                bt = np.nan_to_num(bhp[ys[i]:ys[i+1], xs[j]:xs[j+1]])
                s, _, _ = phase_cross_correlation(at, bt, upsample_factor=UPSAMPLE)
                if np.max(np.abs(s)) > 5.0: continue
                rr.append(s)
        rr = np.array(rr)
        rms = float(np.sqrt((rr ** 2).sum(axis=1).mean())) if len(rr) else float("nan")
        per_band[b] = rms
        print("   [%s] %-5s vs %-5s : RMS=%.3f px" % (tag, BAND_NAME[b], BAND_NAME[anchor], rms), flush=True)
    return per_band


def write_shift_csv(anchor, apply_shift, crop, residT, residJ, suffix=""):
    top, bot, left, right = crop
    path = os.path.join(TEST_DIR, f"registration_shifts{suffix}.csv")
    with open(path, "w") as f:
        f.write("# anchor=%s ; capture_order=%s\n" % (BAND_NAME[anchor], "-".join(BAND_NAME[b] for b in CAP_ORDER)))
        f.write("# T=translation crop rows[%d:%d] cols[%d:%d]\n" % (top, bot + 1, left, right + 1))
        f.write("band,name,shift_dy,shift_dx,resid_T_rms,resid_J_rms\n")
        for b in CAP_ORDER:
            sy, sx = apply_shift[b]
            rt = "0.0" if b == anchor else "%.4f" % residT.get(b, float("nan"))
            rj = "0.0" if b == anchor else "%.4f" % residJ.get(b, float("nan"))
            f.write("%d,%s,%.4f,%.4f,%s,%s\n" % (b, BAND_NAME[b], sy, sx, rt, rj))
    print("wrote", path)


def make_rgb_preview(regT, regJ, anchor, suffix="", ds=20):
    import matplotlib
    matplotlib.use("Agg"); import matplotlib.pyplot as plt
    def norm3(a):
        out = np.zeros_like(a, dtype=np.float32)
        for c in range(3):
            ch = np.nan_to_num(a[..., c]); lo, hi = np.nanpercentile(ch, [2, 98])
            out[..., c] = np.clip((ch - lo) / max(hi - lo, 1e-6), 0, 1)
        return out
    def stk(d):
        h = min(d[3].shape[0], d[2].shape[0], d[1].shape[0])
        w = min(d[3].shape[1], d[2].shape[1], d[1].shape[1])
        return np.stack([d[3][:h, :w], d[2][:h, :w], d[1][:h, :w]], axis=-1)
    T = stk(regT)[::ds, ::ds]; J = stk(regJ)[::ds, ::ds]
    Hs, Ws = J.shape[:2]; zy, zx = int(Hs * 0.30), int(Ws * 0.45)
    zh, zw = min(160, Hs - zy), min(160, Ws - zx)
    fig, ax = plt.subplots(2, 2, figsize=(13, 11))
    fig.suptitle(f"Band registration (anchor={BAND_NAME[anchor]}{suffix})  RGB=MS3/MS2/MS1", fontsize=13)
    ax[0, 0].imshow(norm3(T)); ax[0, 0].set_title("(T) translation only, /%d" % ds)
    ax[0, 1].imshow(norm3(J)); ax[0, 1].set_title("(J) + jitter correction, /%d" % ds)
    ax[1, 0].imshow(norm3(T[zy:zy+zh, zx:zx+zw])); ax[1, 0].set_title("(T) zoom")
    ax[1, 1].imshow(norm3(J[zy:zy+zh, zx:zx+zw])); ax[1, 1].set_title("(J) zoom")
    for a in ax.ravel(): a.set_xticks([]); a.set_yticks([])
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    p = os.path.join(TEST_DIR, f"rgb_reg_preview{suffix}.png"); fig.savefig(p, dpi=110); plt.close(fig)
    print("wrote", p)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--anchor-set", default="all", choices=["all", "rgbn"],
                    help="anchor/jitter 기준을 최적화할 focus 밴드 집합 (all=8밴드, rgbn=Blue/Green/Red/NIR)")
    ap.add_argument("--suffix", default="", help="출력 파일명 접미사 (예: _rgbn) — 결과 별도 저장")
    ap.add_argument("--jitter-mode", default="row", choices=["row", "collin"],
                    help="row=along-track 지터만, collin=across-track 선형(회전 yaw+keystone) 포함")
    args = ap.parse_args()
    focus = CAP_ORDER if args.anchor_set == "all" else [1, 2, 3, 7]
    main(focus, args.suffix, args.jitter_mode)
