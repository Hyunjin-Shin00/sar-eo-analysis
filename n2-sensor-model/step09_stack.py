"""Step 9: 백록담 시계열 스택 — 12씬 5 m AOI 지오코딩(씬별 편향) → 그룹별 상대정합 검증 → 스택 GeoTIFF.

    python step09_stack.py [--res 5] [--size 6] [--outdir ../Output/baengnokdam]

산출 (outdir)
  <date>_<tag>_{dB,locinc,mask}_utm5m_aoi6km.tif   씬별 타일 (동일 격자)
  scenes.csv                                        씬 메타 (기하·편향·유효율·상대정합 잔차)
  coreg_check.csv / coreg_check.png                 그룹 내 씬 쌍 상호상관 잔차 [m]
  stack_<group>_dB_utm5m.tif                        그룹별 다중밴드 스택 (밴드 = 날짜), 상대 dB
  stack_<group>_dBn_utm5m.tif                       공통 유효화소 중앙값 기준 정규화 dB (씬 간 밝기 비교용)
  stack_<group>_validmask_utm5m.tif                 모든 밴드 유효(마스크 0) 화소 = 1
  thumbnails.png
그룹: AR (상승·우측룩, 서쪽 조명) / ALDR (상승·좌측룩 + 하강·우측룩, 동쪽 조명)
"""
import sys, os, glob, json, csv, itertools
import numpy as np, rasterio
from scipy.ndimage import gaussian_filter
import step04_geocode as G4
from simulate import _peak2d

HALA = "/mnt/c/N2_InSAR/N2/LV1A/HALA"
CENTER = (126.5292, 33.3617)          # 백록담
GROUP = {"AR": "AR", "AL": "ALDR", "DR": "ALDR", "DL": "ALDR"}


def run_geocode(outdir, res, size):
    files = sorted(glob.glob(os.path.join(HALA, "*_SSC_*.h5")))
    rows = []
    for k, f in enumerate(files):
        print(f"\n[{k+1:2d}/{len(files)}] {os.path.basename(f)[7:15]}")
        try:
            s = G4.main(f, res=res, with_nobias=False, center=CENTER, size_km=size, bias_src="step07", outdir=outdir)
            rows.append(s)
        except Exception as e:
            print("  !! 실패:", e)
    return rows


def load(outdir, row, res, size, kind="dB"):
    fn = os.path.join(outdir, row["file"].replace("_dB_", f"_{kind}_"))
    with rasterio.open(fn) as d:
        return d.read(1), d.profile


def coreg_pair(a, b, ma, mb, res, search=8, sigma_m=120.0):
    """두 타일의 잔여 시프트. 규약: a(r,c) ≈ b(r-dr, c-dc) -> a 가 b 보다 (dr,dc) px 아래/오른콽. 반환 dE, dN [m], r"""
    m = ma & mb & np.isfinite(a) & np.isfinite(b)
    if m.sum() < 5000:
        return np.nan, np.nan, np.nan
    sig = sigma_m / res
    def hp(x):
        x = np.where(m, x, np.nanmean(x[m])); return x - gaussian_filter(x, sig)
    A, B = hp(a), hp(b)
    H, W = A.shape
    cc = np.full((2 * search + 1, 2 * search + 1), np.nan)
    for i, dr in enumerate(range(-search, search + 1)):
        for j, dc in enumerate(range(-search, search + 1)):
            r0, r1 = max(0, dr), min(H, H + dr); c0, c1 = max(0, dc), min(W, W + dc)
            X = A[r0:r1, c0:c1]; Y = B[r0 - dr:r1 - dr, c0 - dc:c1 - dc]; M = m[r0:r1, c0:c1] & m[r0 - dr:r1 - dr, c0 - dc:c1 - dc]
            if M.sum() < 5000: continue
            x = X[M] - X[M].mean(); y = Y[M] - Y[M].mean()
            cc[i, j] = (x * y).sum() / np.sqrt((x * x).sum() * (y * y).sum())
    if not np.any(np.isfinite(cc)): return np.nan, np.nan, np.nan
    i, j = np.unravel_index(np.nanargmax(cc), cc.shape)
    di, dj = _peak2d(cc, i, j, 2)
    dr = (i - search) + di; dc = (j - search) + dj
    return dc * res, -dr * res, float(cc[i, j])


def main(res=5.0, size=6.0, outdir=None):
    outdir = outdir or os.path.join(G4.OUT, "baengnokdam")
    os.makedirs(outdir, exist_ok=True)
    print("=" * 70); print(f"Step 9  백록담 {size:g} km 타일, {res:g} m, 씬별 편향(step07)  ->  {os.path.normpath(outdir)}"); print("=" * 70)
    rows = run_geocode(outdir, res, size)
    rows = [r for r in rows if r["valid_pct"] > 1.0]
    print(f"\nAOI 안에 자료가 있는 씬: {len(rows)}")

    # ---------------- 상대정합 검증 (그룹 내 모든 쌍)
    print("\n" + "=" * 70); print("상대정합 검증 — 같은 조명 그룹 내 씬 쌍 상호상관 (지오코딩 후 잔여 시프트)"); print("=" * 70)
    tiles = {}
    for r in rows:
        dB, prof = load(outdir, r, res, size, "dB"); mk, _ = load(outdir, r, res, size, "mask")
        tiles[r["date"]] = dict(dB=dB, ok=(mk == 0), row=r, prof=prof)
    pairs = []
    print(f"  {'A':10}{'B':10}{'그룹':6}{'dE m':>8}{'dN m':>8}{'|d| m':>7}{'r':>6}")
    for a, b in itertools.combinations(sorted(tiles), 2):
        ga, gb = GROUP[tiles[a]["row"]["tag"]], GROUP[tiles[b]["row"]["tag"]]
        if ga != gb: continue
        dE, dN, rr = coreg_pair(tiles[a]["dB"], tiles[b]["dB"], tiles[a]["ok"], tiles[b]["ok"], res)
        pairs.append(dict(a=a, b=b, group=ga, dE_m=dE, dN_m=dN, r=rr))
        print(f"  {a:10}{b:10}{ga:6}{dE:8.1f}{dN:8.1f}{np.hypot(dE,dN):7.1f}{rr:6.2f}")
    ok = [p for p in pairs if np.isfinite(p["dE_m"])]
    if ok:
        d = np.array([np.hypot(p["dE_m"], p["dN_m"]) for p in ok])
        print(f"\n  쌍 {len(ok)}개  |잔여 시프트| 중앙 {np.median(d):.1f} m, RMS {np.sqrt((d**2).mean()):.1f} m, 최대 {d.max():.1f} m   (격자 {res:g} m)")
    with open(os.path.join(outdir, "coreg_check.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["a", "b", "group", "dE_m", "dN_m", "r"]); w.writeheader(); w.writerows(pairs)

    # 씬별: 그룹 기준씬 대비 시프트 (기준 = 그룹 내 유효율 최대)
    for r in rows:
        r["coreg_dE_m"] = r["coreg_dN_m"] = np.nan
    for g in set(GROUP.values()):
        mem = [d for d in tiles if GROUP[tiles[d]["row"]["tag"]] == g]
        if len(mem) < 2: continue
        ref = max(mem, key=lambda d: tiles[d]["row"]["valid_pct"])
        for d in mem:
            if d == ref: tiles[d]["row"]["coreg_dE_m"] = tiles[d]["row"]["coreg_dN_m"] = 0.0; tiles[d]["row"]["coreg_ref"] = ref; continue
            p = next((p for p in pairs if {p["a"], p["b"]} == {d, ref}), None)
            if p:
                sgn = 1 if p["a"] == d else -1
                tiles[d]["row"]["coreg_dE_m"] = sgn * p["dE_m"]; tiles[d]["row"]["coreg_dN_m"] = sgn * p["dN_m"]; tiles[d]["row"]["coreg_ref"] = ref

    # ---------------- 스택
    print("\n" + "=" * 70); print("스택 생성"); print("=" * 70)
    for g in sorted(set(GROUP.values())):
        mem = sorted(d for d in tiles if GROUP[tiles[d]["row"]["tag"]] == g)
        if not mem: continue
        prof = tiles[mem[0]]["prof"].copy(); prof.update(count=len(mem), dtype="float32", nodata=np.nan, compress="deflate")
        cube = np.stack([tiles[d]["dB"] for d in mem]); okc = np.stack([tiles[d]["ok"] for d in mem])
        common = okc.all(0)
        # 정규화: 공통 유효화소 중앙값을 0 dB 로
        cube_n = cube.copy()
        for k in range(len(mem)):
            med = np.nanmedian(cube[k][common]) if common.sum() > 100 else np.nanmedian(cube[k][okc[k]])
            cube_n[k] = cube[k] - med
        for name, arr in (("dB", cube), ("dBn", cube_n)):
            fn = os.path.join(outdir, f"stack_{g}_{name}_utm{res:g}m.tif")
            with rasterio.open(fn, "w", **prof) as dst:
                for k, d in enumerate(mem):
                    dst.write(np.where(okc[k], arr[k], np.nan).astype(np.float32), k + 1)
                    dst.set_band_description(k + 1, f"{d}_{tiles[d]['row']['tag']}")
                dst.update_tags(group=g, scenes=",".join(mem), note="dB relative; dBn = median-normalized on common valid pixels")
        pm = prof.copy(); pm.update(count=1, dtype="uint8", nodata=255)
        with rasterio.open(os.path.join(outdir, f"stack_{g}_validmask_utm{res:g}m.tif"), "w", **pm) as dst:
            dst.write(common.astype(np.uint8), 1)
        print(f"  {g:5} {len(mem)}씬  {mem}   공통 유효화소 {common.mean()*100:.1f} %")

    # ---------------- 메타 CSV, 썸네일
    keys = ["date", "tag", "inc_center", "ml", "bias_src", "dt_bias_ms", "dr_bias_m", "valid_pct", "layover_pct", "coreg_ref", "coreg_dE_m", "coreg_dN_m", "file"]
    with open(os.path.join(outdir, "scenes.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore"); w.writeheader()
        for r in rows: w.writerow({k: (round(r[k], 3) if isinstance(r.get(k), float) else r.get(k, "")) for k in keys})
    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        from matplotlib import font_manager
        fp = "/mnt/c/Windows/Fonts/malgun.ttf"
        if os.path.exists(fp):
            font_manager.fontManager.addfont(fp); plt.rcParams["font.family"] = font_manager.FontProperties(fname=fp).get_name()
        n = len(tiles); cols = 4; rws = int(np.ceil(n / cols))
        fig, ax = plt.subplots(rws, cols, figsize=(4 * cols, 4.2 * rws)); ax = np.atleast_1d(ax).ravel()
        for k, d in enumerate(sorted(tiles)):
            t = tiles[d]; v = np.nanpercentile(t["dB"][t["ok"]], (2, 98)) if t["ok"].sum() > 100 else (80, 95)
            ax[k].imshow(np.where(t["ok"], t["dB"], np.nan), cmap="gray", vmin=v[0], vmax=v[1])
            r = t["row"]; ax[k].set_title(f"{d} {r['tag']}  inc {r['inc_center']:.0f}°  유효 {r['valid_pct']:.0f}%", fontsize=10); ax[k].axis("off")
        for k in range(len(tiles), len(ax)): ax[k].axis("off")
        fig.suptitle(f"백록담 {size:g} km 타일, {res:g} m, 씬별 편향 적용 (마스크 0 만 표시)"); plt.tight_layout()
        plt.savefig(os.path.join(outdir, "thumbnails.png"), dpi=90); plt.close()
        # coreg 그림
        if ok:
            fig, ax = plt.subplots(figsize=(6, 6))
            for g, c in (("AR", "C0"), ("ALDR", "C1")):
                pp = [p for p in ok if p["group"] == g]
                if pp: ax.scatter([p["dE_m"] for p in pp], [p["dN_m"] for p in pp], c=c, label=f"{g} ({len(pp)}쌍)", s=40)
            for rr_ in (res / 2, res): ax.add_patch(plt.Circle((0, 0), rr_, fill=False, ls="--", color="gray"))
            ax.axhline(0, color="k", lw=.5); ax.axvline(0, color="k", lw=.5); ax.set_aspect("equal")
            ax.set_xlabel("dE [m]"); ax.set_ylabel("dN [m]"); ax.set_title("그룹 내 씬 쌍 잔여 시프트 (점선 = 0.5 px, 1 px)"); ax.legend()
            plt.tight_layout(); plt.savefig(os.path.join(outdir, "coreg_check.png"), dpi=100); plt.close()
        print(f"  썸네일/정합 그림 저장")
    except Exception as e:
        print("  [그림 생략]", e)
    print(f"\n완료: {os.path.normpath(outdir)}")


if __name__ == "__main__":
    a = sys.argv[1:]
    res = float(a[a.index("--res") + 1]) if "--res" in a else 5.0
    size = float(a[a.index("--size") + 1]) if "--size" in a else 6.0
    od = a[a.index("--outdir") + 1] if "--outdir" in a else None
    main(res, size, od)
