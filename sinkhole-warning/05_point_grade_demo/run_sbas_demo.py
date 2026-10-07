#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""데모용 고속 SBAS — 부산 사상~하단 (Sentinel-1 ASC track 54)

PROJ 운영 파이프라인(analysis/insar_bin/run_sbas.py)과 **수식·파라미터 동일**.
차이는 입력과 병렬화뿐:
  · 입력  : 원본 merged 스택(115GB, /data0) → AOI 크롭 스택(559MB, 01_sar_input/slc_stack_crop.npy)
  · 언래핑: snaphu 824쌍 직렬(69초) → 프로세스 병렬(기본 24) ~5초
결과 CSV는 운영본과 동일(검증: --verify).

usage
  python3 run_sbas_demo.py --cache             # 언래핑 캐시로 역산(전달자료 기본) — 약 1~2초
  python3 run_sbas_demo.py                     # 라이브 실행 — SLC 스택 필요 · 약 6초
  python3 run_sbas_demo.py --precomputed       # 계산 생략, 사전결과를 out/ 으로 복사(즉시)
  python3 run_sbas_demo.py --cache             # unwrap 캐시 재사용(약 8초)
  python3 run_sbas_demo.py --verify            # 운영 결과와 수치 일치 검증
  python3 run_sbas_demo.py --jobs 16 --shp     # 병렬수 지정 / SHP 도 출력
"""
import os
os.environ.pop("PYTHONPATH", None)
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")
import sys, json, glob, time, shutil, argparse, datetime, tempfile, subprocess
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.dirname(HERE)
IN   = os.path.join(DEMO, "01_sar_input")
OUT  = os.path.join(HERE, "out")
PRE  = os.path.join(HERE, "precomputed")
CACHE = os.path.join(HERE, "cache_unw.npz")
SNAPHU = os.environ.get("SNAPHU_BIN") or shutil.which("snaphu") or "snaphu"
REGION = "Busan_Sasang_Hadan"

# ── 운영 파이프라인과 동일한 처리 파라미터 (run_sbas.py 기본값 + T2k 권장조건) ──
RGL, AZL = 9, 3          # 멀티룩 (range, azimuth)
CMAX, TMAX = 4, 72       # 간섭쌍 망: 각 영상당 최대 4연결 · 최대 72일 (연속쌍은 무조건 포함)
COH_MIN, TCOH_MIN = 0.30, 0.70    # ★T2k 권장 통일조건
LAM = 0.055465763        # Sentinel-1 C-band 파장(m)

_F = _CONF = None        # 워커 전역(fork 상속)


def parse():
    p = argparse.ArgumentParser()
    p.add_argument("--precomputed", action="store_true", help="계산 없이 사전결과 사용(폴백)")
    p.add_argument("--cache", action="store_true", help="unwrap 캐시 재사용")
    p.add_argument("--verify", action="store_true", help="운영(PROJ) 결과와 일치 검증")
    p.add_argument("--jobs", type=int, default=min(24, os.cpu_count() or 8))
    p.add_argument("--shp", action="store_true", help="SHP 도 출력(느림)")
    p.add_argument("--snaphu", default=SNAPHU,
                   help="snaphu 실행파일 경로(기본: $SNAPHU_BIN → PATH → GMTSAR 기본위치)")
    p.add_argument("--out", default=OUT)
    return p.parse_args()


def log(msg, t0=None):
    s = "[%s] %s" % (datetime.datetime.now().strftime("%H:%M:%S"), msg)
    if t0 is not None:
        s += "  (+%.1fs)" % (time.time() - t0)
    print(s, flush=True)
    return s


# ────────────────────────────────────────────────────────── 간섭도 + 언래핑(워커)
def _init(F, naz, nrg):
    global _F, _CONF
    _F = F
    d = tempfile.mkdtemp(prefix="snaphu_", dir="/dev/shm" if os.path.isdir("/dev/shm") else None)
    conf = os.path.join(d, "snaphu.conf")
    open(conf, "w").write(
        "INFILE {0}/p.int\nLINELENGTH {1}\nOUTFILE {0}/p.unw\nCORRFILE {0}/p.cor\n"
        "INFILEFORMAT COMPLEX_DATA\nCORRFILEFORMAT FLOAT_DATA\nOUTFILEFORMAT FLOAT_DATA\n"
        "STATCOSTMODE DEFO\nINITMETHOD MCF\n".format(d, nrg))
    _CONF = (d, conf, naz, nrg)


def _pair(ij):
    """run_sbas.py 와 동일: 공액곱 → 9x3 합 멀티룩 → 코히런스 → snaphu(DEFO/MCF)."""
    i, j = ij
    d, conf, naz, nrg = _CONF
    A, B = _F[i], _F[j]
    ig = (A * np.conj(B)).reshape(naz, AZL, nrg, RGL).sum((1, 3))
    pm = (np.abs(A) ** 2).reshape(naz, AZL, nrg, RGL).sum((1, 3))
    ps = (np.abs(B) ** 2).reshape(naz, AZL, nrg, RGL).sum((1, 3))
    coh = (np.abs(ig) / np.sqrt(pm * ps + 1e-20)).astype(np.float32)
    (ig / (np.abs(ig) + 1e-20)).astype(np.complex64).tofile(os.path.join(d, "p.int"))
    coh.tofile(os.path.join(d, "p.cor"))
    subprocess.run([SNAPHU, "-f", conf], capture_output=True, cwd=d)
    unw = np.fromfile(os.path.join(d, "p.unw"), np.float32).reshape(naz, nrg)
    return unw, coh


# ────────────────────────────────────────────────────────── 메인
def main():
    a = parse()
    global SNAPHU
    SNAPHU = a.snaphu
    os.makedirs(a.out, exist_ok=True)
    T0 = time.time()
    steps = []
    if not a.precomputed and not a.cache and not (os.path.isfile(SNAPHU) and os.access(SNAPHU, os.X_OK)):
        print("snaphu 실행파일을 찾을 수 없습니다: %s\n"
              "  → --snaphu /경로/snaphu 로 지정하거나 SNAPHU_BIN 환경변수를 설정하세요.\n"
              "  → 없으면 --precomputed 로 사전결과를 사용하면 됩니다." % SNAPHU, file=sys.stderr)
        sys.exit(3)

    meta = json.load(open(os.path.join(IN, "meta.json")))
    dates = meta["dates"]; nd = len(dates)
    naz, nrg = meta["shape_ml"]

    # ── 폴백: 사전계산 결과 그대로 사용 ──
    if a.precomputed:
        log("사전계산 결과 사용(폴백 모드)")
        n = 0
        for f in sorted(glob.glob(os.path.join(PRE, "*"))):
            shutil.copy2(f, a.out); n += 1
        log("%d개 파일 복사 완료 → %s" % (n, a.out), T0)
        json.dump({"mode": "precomputed", "elapsed_sec": round(time.time() - T0, 2)},
                  open(os.path.join(a.out, "timing.json"), "w"), indent=1)
        return

    # SLC 스택(ISCE 코레지스트레이션 산출물)은 전달자료에서 제외했다.
    # 없으면 --cache 로 언래핑 결과를 읽어 ③ 역산부터 실제로 계산한다.
    stack = os.path.join(IN, "slc_stack_crop.npy")
    g = np.load(os.path.join(IN, "geom.npz"))
    lat = g["lat"].reshape(-1).astype(float); lon = g["lon"].reshape(-1).astype(float)
    F = None
    if os.path.exists(stack):
        log("① 전처리 SAR 스택 로드 — Sentinel-1 %d장 (%s~%s)" % (nd, dates[0], dates[-1]))
        F = np.load(stack, mmap_mode=None)
        steps.append(("SLC 스택 로드", time.time() - T0))
        log("   %s  %.0fMB  멀티룩 후 %dx%d = %dpx" % (F.shape, F.nbytes / 1e6, naz, nrg, naz * nrg), T0)
    elif a.cache and os.path.exists(CACHE):
        log("① SLC 스택 없음 — 언래핑 캐시로 진행 (Sentinel-1 %d장 %s~%s · 멀티룩 %dx%d = %dpx)"
            % (nd, dates[0], dates[-1], naz, nrg, naz * nrg))
    else:
        print("SLC 스택이 없습니다: %s\n"
              "  → --cache (언래핑 캐시로 역산) 또는 --precomputed (사전결과 복사) 로 실행하십시오.\n"
              "  → 라이브 언래핑까지 돌리려면 ISCE 전처리 산출물(slc_stack_crop.npy, 559MB)이 필요합니다."
              % stack, file=sys.stderr)
        sys.exit(2)

    dt = [datetime.date(int(d[:4]), int(d[4:6]), int(d[6:8])) for d in dates]
    pairs = [(i, j) for i in range(nd) for j in range(i + 1, min(i + 1 + CMAX, nd))
             if (dt[j] - dt[i]).days <= TMAX or j == i + 1]
    npair = len(pairs)

    t1 = time.time()
    if a.cache and os.path.exists(CACHE):
        log("② 간섭쌍 %d개 — 캐시 로드" % npair)
        z = np.load(CACHE); UNW, COH = z["UNW"], z["COH"]
    else:
        log("② 간섭쌍 %d개 생성 + 위상 언래핑(snaphu, %d병렬)" % (npair, a.jobs))
        from multiprocessing import Pool
        UNW = np.empty((npair, naz, nrg), np.float32); COH = np.empty_like(UNW)
        with Pool(a.jobs, initializer=_init, initargs=(F, naz, nrg)) as pool:
            for k, (u, c) in enumerate(pool.imap(_pair, pairs, chunksize=4)):
                UNW[k] = u; COH[k] = c
                if (k + 1) % 200 == 0:
                    log("   unwrap %d/%d" % (k + 1, npair), t1)
        if not os.path.exists(CACHE):
            np.savez(CACHE, UNW=UNW, COH=COH)
    steps.append(("간섭도+언래핑", time.time() - t1))
    log("   완료", t1)

    # ── SBAS 역산 (run_sbas.py 와 동일) ──
    t2 = time.time()
    log("③ SBAS 시계열 역산")
    Npix = naz * nrg
    Uall = UNW.reshape(npair, Npix); Cf = COH.reshape(npair, Npix); mcoh = Cf.mean(0)
    ref = int(np.argmax(mcoh))
    log("   기준픽셀 = 최대결맞음 px#%d (coh %.3f)" % (ref, mcoh[ref]))
    B = np.zeros((npair, nd - 1))
    for p, (i, j) in enumerate(pairs):
        if i > 0:
            B[p, i - 1] = -1.0
        B[p, j - 1] = 1.0
    w = np.clip(Cf.mean(1), 1e-3, None)
    Binv = np.linalg.pinv(w[:, None] * B)
    t = np.array([(d - dt[0]).days for d in dt]) / 365.25; tc = t - t.mean()
    yy, xx = np.divmod(np.arange(Npix), nrg); A = np.c_[np.ones(Npix), xx, yy]

    U = Uall - Uall[:, ref][:, None]
    phi = np.zeros((nd, Npix), np.float32); phi[1:] = Binv @ (w[:, None] * U)
    resid = U - (B @ phi[1:]); tcoh = np.abs(np.exp(1j * resid).mean(0))
    good = (mcoh >= COH_MIN) & (tcoh >= TCOH_MIN)
    if int(good.sum()) == 0:
        log("양호 관측점 0 — 중단"); sys.exit(2)
    Ag = A[good]
    for k in range(1, nd):                       # 잔여 평면(궤도/대기) 제거
        c, *_ = np.linalg.lstsq(Ag, phi[k, good], rcond=None)
        phi[k] -= A @ c
    phi -= phi[:, ref][:, None]
    disp = (-LAM / (4 * np.pi) * phi * 1000.0).astype(np.float32)      # mm, (−)=침하
    vel = ((tc[:, None] * disp).sum(0) / (tc ** 2).sum()).astype(np.float32)
    gp = np.where(good)[0]
    steps.append(("SBAS 역산", time.time() - t2))
    log("   채택 %d/%d px · tcoh중앙 %.3f · 속도 %.2f~%.2f mm/yr"
        % (good.sum(), Npix, np.median(tcoh), vel[good].min(), vel[good].max()), t2)

    # ── 저장 ──
    t3 = time.time()
    import pandas as pd
    isref = np.zeros(len(gp), int)
    if ref in gp:
        isref[int(np.where(gp == ref)[0][0])] = 1
    df = pd.concat([
        pd.DataFrame({"Longitude": np.round(lon[gp], 6), "Latitude": np.round(lat[gp], 6),
                      "incidence": 0.0, "velocity": np.round(vel[gp], 4),
                      "tcoh": np.round(tcoh[gp], 3)}),
        pd.DataFrame(np.round(disp[:, gp].T, 4), columns=["D" + d for d in dates]),
        pd.DataFrame({"is_ref": isref})], axis=1)
    base = os.path.join(a.out, REGION + "_sbas_ps_v")
    df.to_csv(base + ".csv", index=False)
    json.dump({"ok": True, "ref_lon": float(lon[ref]), "ref_lat": float(lat[ref]),
               "ref_radius_m": 60.0, "n_ps_in_ref": 1, "note": "SBAS max-coh ref pixel"},
              open(os.path.join(a.out, REGION + "_sbas_ref_for_clickmap.json"), "w"),
              ensure_ascii=False, indent=2)
    if a.shp:
        import geopandas as gpd
        gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df.Longitude, df.Latitude),
                         crs=4326).to_file(base + ".shp")
    steps.append(("결과 저장", time.time() - t3))
    log("④ 저장 %s.csv (%d점)" % (base, len(df)), t3)

    total = time.time() - T0
    json.dump({"mode": "cache" if a.cache else "live", "jobs": a.jobs,
               "n_dates": nd, "n_pairs": npair, "n_points": int(len(df)),
               "elapsed_sec": round(total, 2),
               "steps": [{"name": n, "sec": round(s, 2)} for n, s in steps]},
              open(os.path.join(a.out, "timing.json"), "w"), ensure_ascii=False, indent=1)
    log("SBAS 완료 — 총 %.1f초" % total)

    if a.verify:
        ref_csv = ("<DATA_ROOT>/regions/busan/sbas/sasang_hadan/sweep/"
                   "coh0.3_tcoh0.7/%s_sbas_ps_v.csv" % REGION)
        if not os.path.exists(ref_csv):
            log("검증 스킵 — 운영 결과 없음"); return
        r = pd.read_csv(ref_csv)
        log("검증: 운영 %d점 vs 데모 %d점" % (len(r), len(df)))
        key = lambda d: ((d.Longitude * 1e6).round().astype("int64").astype(str) + "_" +
                         (d.Latitude * 1e6).round().astype("int64").astype(str))
        m = pd.merge(r.assign(k=key(r)), df.assign(k=key(df)), on="k", suffixes=("_op", "_dm"))
        dv = (m.velocity_op - m.velocity_dm).abs()
        log("   공통 %d점 · 속도 최대차 %.4f mm/yr · 평균차 %.5f" % (len(m), dv.max(), dv.mean()))


if __name__ == "__main__":
    main()
