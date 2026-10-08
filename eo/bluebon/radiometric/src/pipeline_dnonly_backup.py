#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BlueBON 관측영상 전처리 파이프라인 — 최종 v5 (dark/PRNU 보정 + 밴드 정합).

  입력 : <INPUT_DIR> 하위 8밴드 raw TIFF  (YYMMDD_HHMMSS_{0..7}_gray.tiff)
  처리 : ① 전 밴드(PAN 포함) 복사보정 = (raw - dark_ref[col]) * flat_prnu[col] - δ_persistent[col]
              · dark_ref      : 야간 원양 dark 평균 (가산)
              · flat_prnu     : Libya-4 full-width flat (곱셈, PRNU+vignetting), 기본 --prnu-mode flat
              · δ_persistent  : 다중 장면 평균 고주파 열 잔차 (가산, 미세 세로줄무늬 제거), 기본 on
         ② 밴드 정합 = RGBN(Blue/Green/Red/NIR) 중심 anchor 자동선택
                     + jitter+회전(collin) 보정 (regjit_rgbn_rot 방식)
         ③ 공통 crop -> 좌우 flip
  출력 : <INPUT_DIR>/radiometric_v5/   (--out-name 으로 변경 가능)
         - MS{0..7}_DN_dark_Rc_p.tiff        (개별밴드 uint16, DN 보존)
         - bb_l1a_20<stem>_8band.tiff     (병합 8밴드, uint16, DN 보존)
         - registration_shifts.csv, bb_l1a-rgb_20<stem>.png (원해상도 RGB)

사용법:
  python3 pipeline.py <INPUT_DIR>
  옵션: --prnu-mode flat|residual (기본 flat) · --no-delta (δ 끄기) · --out-name <dir>

정합 규약: phase_cross_correlation(ref, mov) -> shift(mov, s) 하면 ref 에 정렬.
참조 데이터: REF_DIR 의 {PAN,MS1..7}_dark_ref.tiff / _prnu_flat_coef.dat / _delta_persistent.dat
자세한 내용: PIPELINE.md
"""
import os
import sys
import glob
import math
import argparse
import numpy as np
import tifffile
from skimage.registration import phase_cross_correlation
from scipy.ndimage import shift as nd_shift
from scipy.ndimage import gaussian_filter, gaussian_filter1d, map_coordinates, median_filter

REF_DIR = "<WORK_ROOT>/working/radiometric_correction/ref/master"   # dark/PRNU 참조

CAP_ORDER = [1, 2, 3, 0, 7, 4, 5, 6]                         # 촬영 순서
BAND_NAME = {0: "PAN", 1: "Blue", 2: "Green", 3: "Red", 4: "RE1", 5: "RE2", 6: "RE3", 7: "NIR"}
MS_BANDS  = [1, 2, 3, 4, 5, 6, 7]
RGBN      = [1, 2, 3, 7]                                     # anchor/jitter 기준 focus
UPSAMPLE  = 10
SHIFT_ORDER = 1
# jitter(collin) 파라미터
JIT_WIN, JIT_STEP, JIT_SMTH, NX_BLK = 1200, 400, 500.0, 7


# --------------------------------------------------------------------------
def prep_hp(im, sigma=3.0):
    x = im.astype(np.float64)
    return x - gaussian_filter(x, sigma=sigma)


def pcc(ref, mov):
    s, _, _ = phase_cross_correlation(prep_hp(ref), prep_hp(mov), upsample_factor=UPSAMPLE)
    return np.array(s, dtype=np.float64)


def ref_name(n):
    return "PAN" if n == 0 else f"MS{n}"


def load_corrected(obs_dir, stem, n, prnu_mode="flat", use_delta=True):
    raw = tifffile.imread(os.path.join(obs_dir, f"{stem}_{n}_gray.tiff")).astype(np.float32)
    rn = ref_name(n)                                        # PAN 포함 전 밴드 dark/PRNU 보정
    dark = tifffile.imread(os.path.join(REF_DIR, f"{rn}_dark_ref.tiff")).astype(np.float32).ravel()
    coef = f"{rn}_prnu_flat_coef.dat" if prnu_mode == "flat" else f"{rn}_residul_prnu_coef.dat"
    prnu = np.loadtxt(os.path.join(REF_DIR, coef)).astype(np.float32)
    out = (raw - dark[None, :]) * prnu[None, :]            # dark + PRNU
    if use_delta:                                          # 지속 가산 잔차(δ) 제거 = dark 보강
        dpath = os.path.join(REF_DIR, f"{rn}_delta_persistent.dat")
        if os.path.exists(dpath):
            out = out - np.loadtxt(dpath).astype(np.float32)[None, :]
    return out


def _smooth_rows(rc, val, H):
    val = median_filter(np.asarray(val, float), size=3)
    c = np.interp(np.arange(H), rc, val, left=val[0], right=val[-1])
    return gaussian_filter1d(c, JIT_SMTH)


def residual_field(anchor_img, band_img, H, W):
    """collin: across-track 블록별 잔차 -> 컬럼 선형회귀(회전/keystone) -> row 스무딩.
       반환 ay,ax,by,bx :  dy(r,c)=ay(r)+by(r)*(c-c0),  dx(r,c)=ax(r)+bx(r)*(c-c0)."""
    c0 = W / 2.0
    ahp, bhp = prep_hp(anchor_img), prep_hp(band_img)
    gstd = ahp.std()
    xs = np.linspace(0, W, NX_BLK + 1).astype(int)
    xcen = np.array([(xs[j] + xs[j + 1]) / 2 for j in range(NX_BLK)])
    rc, AY, AX, BY, BX = [], [], [], [], []
    r = 0
    while r + JIT_WIN <= H:
        cc, dyb, dxb = [], [], []
        for j in range(NX_BLK):
            at = ahp[r:r + JIT_WIN, xs[j]:xs[j + 1]]
            bt = bhp[r:r + JIT_WIN, xs[j]:xs[j + 1]]
            if at.std() < gstd * 0.4:
                continue
            s, _, _ = phase_cross_correlation(at, bt, upsample_factor=UPSAMPLE)
            if np.max(np.abs(s)) <= 8.0:
                cc.append(xcen[j] - c0); dyb.append(s[0]); dxb.append(s[1])
        if len(cc) >= 3:
            cc = np.array(cc)
            py = np.polyfit(cc, dyb, 1); px = np.polyfit(cc, dxb, 1)
            rc.append(r + JIT_WIN / 2)
            AY.append(py[1]); BY.append(py[0]); AX.append(px[1]); BX.append(px[0])
        r += JIT_STEP
    rc = np.array(rc)
    if len(rc) < 3:
        z = np.zeros(H); return z, z, z.copy(), z.copy()
    return (_smooth_rows(rc, AY, H), _smooth_rows(rc, AX, H),
            _smooth_rows(rc, BY, H), _smooth_rows(rc, BX, H))


def field_warp(img, add_dy, add_dx, ay, ax, by, bx):
    H, W = img.shape
    c0 = W / 2.0
    cols = np.arange(W, dtype=np.float32)[None, :]
    rows = np.arange(H, dtype=np.float32)[:, None]
    dc = cols - c0
    tot_dy = (add_dy + ay[:, None]) + by[:, None] * dc
    tot_dx = (add_dx + ax[:, None]) + bx[:, None] * dc
    r_coord = rows - tot_dy.astype(np.float32)
    c_coord = cols - tot_dx.astype(np.float32)
    return map_coordinates(img, [r_coord, c_coord], order=1, mode="constant", cval=np.nan)


def to_u16(x):
    """DN 보존 uint16 변환: NaN->0, 반올림, clip[0,65535] (스케일/정규화 없음)."""
    return np.clip(np.rint(np.nan_to_num(x, nan=0.0)), 0, 65535).astype(np.uint16)


def valid_bounds(shifts, H, W):
    top, bot, left, right = 0, H - 1, 0, W - 1
    for (sy, sx) in shifts:
        top = max(top, max(0, math.ceil(sy)));  bot = min(bot, (H - 1) + min(0, math.floor(sy)))
        left = max(left, max(0, math.ceil(sx))); right = min(right, (W - 1) + min(0, math.floor(sx)))
    return top, bot, left, right


def detect_stem(obs_dir):
    hits = sorted(glob.glob(os.path.join(obs_dir, "*_0_gray.tiff")))
    if not hits:
        sys.exit(f"[ERROR] '{obs_dir}' 하위에 *_0_gray.tiff 없음")
    base = os.path.basename(hits[0])
    return base[:-len("_0_gray.tiff")]


# --------------------------------------------------------------------------
def main(obs_dir, prnu_mode="flat", out_name="radiometric_v5", use_delta=True):
    stem = detect_stem(obs_dir)
    out_dir = os.path.join(obs_dir, out_name)
    os.makedirs(out_dir, exist_ok=True)
    print(f"=== pipeline: {obs_dir}\n    stem={stem}  out={out_dir}  prnu={prnu_mode} delta={use_delta} ===", flush=True)

    # ① 로드 + dark/PRNU (+ δ persistent 가산 잔차 제거)
    print("① dark/PRNU correction (prnu=%s, delta=%s) ..." % (prnu_mode, use_delta), flush=True)
    img = {n: load_corrected(obs_dir, stem, n, prnu_mode, use_delta) for n in CAP_ORDER}
    H, W = img[CAP_ORDER[0]].shape

    # ②-a 인접쌍 shift 체인 -> RGBN 중 최적 anchor
    print("② registration: chain shifts + RGBN anchor ...", flush=True)
    a = [pcc(img[CAP_ORDER[k]], img[CAP_ORDER[k + 1]]) for k in range(len(CAP_ORDER) - 1)]
    S = {CAP_ORDER[0]: np.array([0.0, 0.0])}
    acc = np.array([0.0, 0.0])
    for k in range(len(CAP_ORDER) - 1):
        acc = acc + a[k]; S[CAP_ORDER[k + 1]] = acc.copy()
    anchor = min(RGBN, key=lambda anc: max(np.hypot(*(S[b] - S[anc])) for b in RGBN))
    apply_shift = {b: (S[b] - S[anchor]) for b in CAP_ORDER}
    print("   anchor = %s" % BAND_NAME[anchor], flush=True)

    # ②-b 평행이동(base) — 잔차필드 추정용
    top, bot, left, right = valid_bounds([apply_shift[b] for b in CAP_ORDER], H, W)
    regT = {}
    for b in CAP_ORDER:
        sy, sx = apply_shift[b]
        sh = img[b] if (abs(sy) < 1e-6 and abs(sx) < 1e-6) else \
             nd_shift(img[b], shift=(sy, sx), order=SHIFT_ORDER, mode="constant", cval=0.0, prefilter=False)
        regT[b] = sh[top:bot + 1, left:right + 1]

    # ②-c jitter+회전(collin) 필드 추정
    print("   jitter+rotation field (collin) ...", flush=True)
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
        ay, ax, by, bx = residual_field(regT[anchor], regT[b], Hc, Wc)
        fields[b] = (to_full(ay), to_full(ax), to_full(by), to_full(bx))

    # ②-d 단일 remap warp + 공통 crop
    halfW = W / 2.0
    def bmax(b):
        ay, ax, by, bx = fields[b]
        return (np.max(np.abs(apply_shift[b][0] + ay) + np.abs(by) * halfW),
                np.max(np.abs(apply_shift[b][1] + ax) + np.abs(bx) * halfW))
    mY = int(math.ceil(max(bmax(b)[0] for b in CAP_ORDER))) + 1
    mX = int(math.ceil(max(bmax(b)[1] for b in CAP_ORDER))) + 1
    reg = {}
    for b in CAP_ORDER:
        ay, ax, by, bx = fields[b]
        w = img[b] if b == anchor else field_warp(img[b], apply_shift[b][0], apply_shift[b][1], ay, ax, by, bx)
        reg[b] = np.fliplr(w[mY:H - mY, mX:W - mX])          # ③ crop + 좌우 flip

    # 저장: 개별밴드(uint16, DN 보존) + 병합 8밴드(f32/u16)
    print("saving ...", flush=True)
    for n in MS_BANDS:
        tifffile.imwrite(os.path.join(out_dir, f"MS{n}_DN_dark_rc_p.tiff"),
                         to_u16(reg[n]), photometric="minisblack")
    tifffile.imwrite(os.path.join(out_dir, "MS0_DN_dark_rc_p.tiff"),
                     to_u16(reg[0]), photometric="minisblack")

    order = [0, 1, 2, 3, 4, 5, 6, 7]                          # band 0..7
    stack = np.stack([reg[n] for n in order], axis=0)
    #f32 = os.path.join(out_dir, f"{stem}_regjit_rgbn_rot_8band_f32.tiff")
    u16 = os.path.join(out_dir, f"bb_l1a_20{stem}_8band.tiff")
    #tifffile.imwrite(f32, stack, photometric="minisblack", planarconfig="separate")
    u16arr = to_u16(stack)
    tifffile.imwrite(u16, u16arr, photometric="minisblack", planarconfig="separate")

    write_csv(out_dir, anchor, apply_shift, (mY, mX), stack.shape)
    save_rgb_png(out_dir, stem, reg)
    print("   f32 min=%.1f max=%.1f  u16 min=%d max=%d  shape=%s" % (
        float(stack.min()), float(stack.max()), int(u16arr.min()), int(u16arr.max()), stack.shape))
    print("DONE. band order 0..7 = PAN,Blue,Green,Red,RE1,RE2,RE3,NIR ->", out_dir)


def write_csv(out_dir, anchor, apply_shift, margin, shape):
    with open(os.path.join(out_dir, "registration_shifts.csv"), "w") as f:
        f.write("# anchor=%s (RGBN 중심) ; jitter=collin(회전+keystone)\n" % BAND_NAME[anchor])
        f.write("# output shape (band,H,W)=%s ; crop margin rows+-%d cols+-%d\n" % (shape, margin[0], margin[1]))
        f.write("band,name,shift_dy,shift_dx\n")
        for b in CAP_ORDER:
            f.write("%d,%s,%.4f,%.4f\n" % (b, BAND_NAME[b], apply_shift[b][0], apply_shift[b][1]))


def save_rgb_png(out_dir, stem, reg, pct=(0.01, 99.999), gamma=2.2):
    """원해상도 RGB 합성 PNG 저장 (이미지만; 축/타이틀/여백 없음).
       R=MS3, G=MS2, B=MS1. 채널별 percentile 스트레치 + mild gamma -> uint8."""
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None                            # 대형 이미지 허용
    h = min(reg[3].shape[0], reg[2].shape[0], reg[1].shape[0])
    w = min(reg[3].shape[1], reg[2].shape[1], reg[1].shape[1])
    chans = [reg[3][:h, :w], reg[2][:h, :w], reg[1][:h, :w]]  # R,G,B
    out = np.zeros((h, w, 3), dtype=np.uint8)
    for c, ch in enumerate(chans):
        ch = np.nan_to_num(ch.astype(np.float32))
        lo, hi = np.nanpercentile(ch, pct)
        v = np.clip((ch - lo) / max(hi - lo, 1e-6), 0, 1) ** (1.0 / gamma)
        out[..., c] = np.rint(v * 255).astype(np.uint8)
    Image.fromarray(out).save(os.path.join(out_dir, f"bb_l1a-rgb_20{stem}.png"))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("input_dir",
                    help="8밴드 raw TIFF 가 있는 관측 디렉터리")
    ap.add_argument("--prnu-mode", default="flat", choices=["residual", "flat"],
                    help="flat(기본)=full-width(넓은 vignetting 포함), residual=고주파 검출기 FPN만")
    ap.add_argument("--out-name", default="radiometric_v5", help="출력 하위폴더명")
    ap.add_argument("--no-delta", action="store_true", help="지속 가산 잔차(δ) 제거 끄기")
    args = ap.parse_args()
    main(args.input_dir, args.prnu_mode, args.out_name, use_delta=not args.no_delta)
