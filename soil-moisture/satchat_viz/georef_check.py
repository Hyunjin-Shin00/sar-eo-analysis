"""분석 격자 ↔ 실제 지도 위치 정합 검사.
 분석 자료의 물 셀(Sentinel-1 VV 시계열 중앙값 < −15 dB) vs ESA WorldCover 2021 수면(80) 비율>0.5,
 같은 100 m 격자에서 IoU, 그리고 ±3셀 이동 시 IoU 최대 위치(0,0이면 정합)."""
import numpy as np, rasterio, json
from rasterio.warp import reproject, Resampling
from rasterio.transform import from_origin
R = "<WORK_ROOT>"
def check(name, water_s1, T, crs, wc_url):
    H, W = water_s1.shape; frac = np.zeros((H, W), np.float32)
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"), rasterio.open(wc_url) as s:
        reproject(rasterio.band(s, 1), frac, dst_transform=T, dst_crs=crs, resampling=Resampling.average,
                  src_nodata=0) if False else None
        wcw = np.zeros((H * 10, W * 10), np.uint8)
        reproject(rasterio.band(s, 1), wcw, dst_transform=from_origin(T.c, T.f, T.a / 10, T.a / 10), dst_crs=crs, resampling=Resampling.nearest)
    wc = (wcw == 80).reshape(H, 10, W, 10).mean((1, 3)) > 0.5
    def iou(a, b): return (a & b).sum() / max((a | b).sum(), 1)
    best = max(((iou(np.roll(np.roll(water_s1, dy, 0), dx, 1), wc), dy, dx) for dy in range(-3, 4) for dx in range(-3, 4)))
    r = dict(site=name, s1_water_cells=int(water_s1.sum()), worldcover_water_cells=int(wc.sum()), IoU_at_0=round(iou(water_s1, wc), 3),
             best_IoU=round(best[0], 3), best_shift_cells_dy_dx=[best[1], best[2]])
    print(r); return r, wc
out = []
# 가평
z = np.load(f"{R}/outputs/GP/gao2017_stack_100m.npz", allow_pickle=True)
T = from_origin(float(z["x0"]), float(z["y1"]), 100., 100.); crs = f"EPSG:{int(z['epsg'])}"
w_gp = np.nanmedian(z["VV"], 0) < -15
r, wc_gp = check("GP", w_gp, T, crs, "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N36E126_Map.tif"); out.append(r)
np.savez(f"{R}/satchat/georef_check/GP_water.npz", s1=w_gp, wc=wc_gp)
# 영국 (10 m 창 → 100 m)
B = f"{R}/case_UK_Maslanka2022"; z = np.load(f"{B}/data/s1rtc_CHIMN.npz")
inc = json.load(open(f"{B}/data/incidence_angles.json"))["CHIMN"]
th = np.array([inc[str(o)] for o in z["orbit"]]); sig = 10 * np.log10(z["vv"] * np.cos(np.deg2rad(th))[:, None, None])
med = np.nanmedian(sig, 0); hh = med.shape[0] // 10
med100 = 10 * np.log10(np.nanmean((10 ** (med[:hh * 10, :hh * 10] / 10)).reshape(hh, 10, hh, 10), (1, 3)))
w_uk = med100 < -15
r, wc_uk = check("UK_CHIMN", w_uk, from_origin(float(z["x0"]), float(z["y1"]), 100., 100.), "EPSG:32630",
                 "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N51W003_Map.tif"); out.append(r)
np.savez(f"{R}/satchat/georef_check/UK_water.npz", s1=w_uk, wc=wc_uk)
json.dump(out, open(f"{R}/satchat/georef_check/georef_iou.json", "w"), indent=1)

# ---------- 영국 10 m 정밀 검사 (호수·자갈채취장 물) ----------
from rasterio.warp import reproject
wc10 = np.zeros(med.shape, np.uint8)
with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"), rasterio.open("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N51W003_Map.tif") as s:
    reproject(rasterio.band(s, 1), wc10, dst_transform=from_origin(float(z["x0"]), float(z["y1"]), 10., 10.), dst_crs="EPSG:32630", resampling=Resampling.nearest)
a = med < -15; b = wc10 == 80
iou = lambda p, q: (p & q).sum() / max((p | q).sum(), 1)
best = max(((iou(np.roll(np.roll(a, dy, 0), dx, 1), b), dy, dx) for dy in range(-6, 7) for dx in range(-6, 7)))
r = dict(site="UK_CHIMN_10m", s1_water_px=int(a.sum()), worldcover_water_px=int(b.sum()), IoU_at_0=round(iou(a, b), 3), best_IoU=round(best[0], 3), best_shift_px_dy_dx=[best[1], best[2]])
print(r); out.append(r); json.dump(out, open(f"{R}/satchat/georef_check/georef_iou.json", "w"), indent=1)
np.savez(f"{R}/satchat/georef_check/UK_water10.npz", s1=a, wc=b, x0=float(z["x0"]), y1=float(z["y1"]))
