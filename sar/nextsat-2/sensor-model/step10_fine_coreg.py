"""Step 10: 그룹 내 미세정합 — 씬 쌍 시프트(step09 coreg_check.csv) 를 네트워크 최소제곱으로 풀어
씬별 보정량을 구하고, 타일을 서브픽셀 이동해 개별 GeoTIFF 로 저장한다 (스택 아님).

    python step10_fine_coreg.py [--indir ../Output/baengnokdam] [--outdir ../Output/baengnokdam/output]

네트워크 LS: 쌍 (a,b) 관측 d_ab = s_a − s_b  (E, N 각각), 가중 r, 기준씬 s_ref = 0.
적용: a 를 −s_a 만큼 이동 (bilinear; mask 는 최근접). 이동 후 20쌍을 다시 재서 잔차를 보고한다.
"""
import sys, os, csv, glob, itertools
import numpy as np, rasterio
from scipy.ndimage import shift as ndshift
import step09_stack as S9

GROUP = S9.GROUP


def read_csv(fn):
    with open(fn, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def network_ls(scenes, pairs, ref):
    """scenes: 날짜 리스트, pairs: dict(a,b,dE_m,dN_m,r). 반환 {date: (sE, sN)}, 잔차 rms"""
    idx = {d: k for k, d in enumerate(scenes)}; n = len(scenes)
    A = []; yE = []; yN = []; w = []
    for p in pairs:
        if p["a"] not in idx or p["b"] not in idx or not np.isfinite(p["dE_m"]): continue
        row = np.zeros(n); row[idx[p["a"]]] = 1; row[idx[p["b"]]] = -1
        A.append(row); yE.append(p["dE_m"]); yN.append(p["dN_m"]); w.append(max(p["r"], 0.05))
    # 기준 구속
    row = np.zeros(n); row[idx[ref]] = 1; A.append(row); yE.append(0.0); yN.append(0.0); w.append(100.0)
    A = np.array(A); w = np.sqrt(np.array(w))
    sE, *_ = np.linalg.lstsq(A * w[:, None], np.array(yE) * w, rcond=None)
    sN, *_ = np.linalg.lstsq(A * w[:, None], np.array(yN) * w, rcond=None)
    eE = (A @ sE - yE)[:-1]; eN = (A @ sN - yN)[:-1]
    rms = float(np.sqrt(np.mean(eE ** 2 + eN ** 2))) if len(eE) else np.nan
    return {d: (float(sE[idx[d]]), float(sN[idx[d]])) for d in scenes}, rms


def main(indir=None, outdir=None):
    indir = indir or os.path.join(S9.G4.OUT, "baengnokdam")
    outdir = outdir or os.path.join(indir, "output")
    os.makedirs(outdir, exist_ok=True)
    scenes = read_csv(os.path.join(indir, "scenes.csv"))
    pairs = read_csv(os.path.join(indir, "coreg_check.csv"))
    for p in pairs:
        for k in ("dE_m", "dN_m", "r"): p[k] = float(p[k]) if p[k] not in ("", "nan") else np.nan
    res = 5.0
    with rasterio.open(os.path.join(indir, scenes[0]["file"])) as d: res = d.res[0]

    print("=" * 70); print(f"Step 10  미세정합 -> {os.path.normpath(outdir)}"); print("=" * 70)
    shifts = {}
    for g in sorted(set(GROUP.values())):
        mem = [s for s in scenes if GROUP[s["tag"]] == g]
        if len(mem) < 2: continue
        dates = [s["date"] for s in mem]
        ref = max(mem, key=lambda s: float(s["valid_pct"]))["date"]
        sol, rms = network_ls(dates, [p for p in pairs if p["group"] == g], ref)
        print(f"\n  그룹 {g}  기준씬 {ref}   네트워크 잔차 rms {rms:.2f} m  (쌍 측정 잡음)")
        for d in dates:
            sE, sN = sol[d]; shifts[d] = (sE, sN, ref, g)
            print(f"    {d}: 보정 이동  동 {-sE:+6.2f} m  북 {-sN:+6.2f} m   ({np.hypot(sE,sN)/res:.2f} px)")

    # ---------------- 적용
    rows_out = []
    tiles = {}
    for s in scenes:
        d = s["date"]
        if d not in shifts: continue
        sE, sN, ref, g = shifts[d]
        # a(r,c) ≈ b(r-dr, c-dc), dE = dc*res, dN = -dr*res  ->  정렬: a(r+dr, c+dc) = ndshift(a, (-dr, -dc)) = ndshift(a, (sN/res, -sE/res))
        sh = (sN / res, -sE / res)
        for kind in ("dB", "locinc", "mask"):
            fn = os.path.join(indir, s["file"].replace("_dB_", f"_{kind}_"))
            with rasterio.open(fn) as src:
                arr = src.read(1); prof = src.profile
            if kind == "mask":
                out = ndshift(arr.astype(np.float32), sh, order=0, mode="constant", cval=255).astype(np.uint8)
            else:
                valid = np.isfinite(arr)
                filled = np.where(valid, arr, 0.0).astype(np.float32)
                num = ndshift(filled, sh, order=1, mode="constant", cval=0.0)
                den = ndshift(valid.astype(np.float32), sh, order=1, mode="constant", cval=0.0)
                out = np.where(den > 0.5, num / np.maximum(den, 1e-6), np.nan).astype(np.float32)
            ofn = os.path.join(outdir, os.path.basename(fn).replace(".tif", "_coreg.tif"))
            with rasterio.open(ofn, "w", **prof) as dst:
                dst.write(out, 1)
                dst.update_tags(fine_coreg_shift_E_m=f"{-sE:.2f}", fine_coreg_shift_N_m=f"{-sN:.2f}", coreg_ref=ref, group=g)
            if kind == "dB": tiles[d] = dict(dB=out, tag=s["tag"])
            if kind == "mask": tiles[d]["ok"] = (out == 0)
        rows_out.append(dict(date=d, tag=s["tag"], group=g, ref=ref, applied_dE_m=round(-sE, 2), applied_dN_m=round(-sN, 2),
                             applied_px=round(np.hypot(sE, sN) / res, 2)))
    with open(os.path.join(outdir, "coreg_shifts.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys())); w.writeheader(); w.writerows(rows_out)

    # ---------------- 이동 후 재검증
    print("\n" + "=" * 70); print("이동 후 재검증 (같은 20쌍 상호상관)"); print("=" * 70)
    d_before = []; d_after = []
    for p in pairs:
        a, b = p["a"], p["b"]
        if a not in tiles or b not in tiles or not np.isfinite(p["dE_m"]): continue
        dE, dN, rr = S9.coreg_pair(tiles[a]["dB"], tiles[b]["dB"], tiles[a]["ok"], tiles[b]["ok"], res)
        d_before.append(np.hypot(p["dE_m"], p["dN_m"])); d_after.append(np.hypot(dE, dN))
        print(f"  {a}-{b} {p['group']:5}  전 {d_before[-1]:5.1f} m  ->  후 {d_after[-1]:5.1f} m   (r {rr:.2f})")
    db, da = np.array(d_before), np.array(d_after)
    print(f"\n  |잔여 시프트|  전: 중앙 {np.median(db):.1f} / RMS {np.sqrt((db**2).mean()):.1f} / 최대 {db.max():.1f} m")
    print(f"                후: 중앙 {np.median(da):.1f} / RMS {np.sqrt((da**2).mean()):.1f} / 최대 {da.max():.1f} m   (격자 {res:g} m)")
    print(f"\n완료: {len(rows_out)}씬 x 3 = {3*len(rows_out)} 파일 -> {os.path.normpath(outdir)}")


if __name__ == "__main__":
    a = sys.argv[1:]
    ind = a[a.index("--indir") + 1] if "--indir" in a else None
    od = a[a.index("--outdir") + 1] if "--outdir" in a else None
    main(ind, od)
