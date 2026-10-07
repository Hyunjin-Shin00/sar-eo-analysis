#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sentinel-1 IW SLC(.SAFE.zip) → 분석영역 지오코딩 진폭 GeoTIFF.

지진 분석에 쓴 SLC 원본을 GIS 에서 바로 볼 수 있는 형태로 내보낸다.
SNAP 산출물(*.data)에는 i/q/coh 밴드만 있고 Intensity 밴드가 없어서, 진폭 영상은
SLC 원본에서 직접 만들어야 한다.

처리
  1) SAFE 안 measurement/*.tiff (IW1·IW2·IW3, 지정 편파) 를 /vsizip 으로 직접 읽는다
  2) 강도 |z|² 를 멀티룩 평균 (기본 range 8 × azimuth 2 → 약 19 m × 28 m)
  3) 제품에 들어 있는 GCP 격자를 멀티룩 배율로 축소해 붙이고, TPS 로 EPSG:4326 워핑
  4) 3개 서브스와스를 하나의 출력 격자에 모자이크 → 대상 영역으로 크롭
  5) dB(= 10·log₁₀ 강도) float32 GeoTIFF 로 저장

⚠️ 한계 — GCP 기반 근사 지오코딩이다. DEM 을 쓰지 않으므로 지형기복이 큰 곳에서 수십 m
   어긋날 수 있고, TOPS 버스트 경계에서 이음매가 보일 수 있다. 정밀 정합이 필요한 작업에는
   SNAP 의 Terrain Correction 산출물(output/01_dinsar/*_TC.tif)을 쓸 것.
   이 파일은 "어떤 영상을 넣었는지" 확인용이다.

usage: slc_to_amp_geotiff.py <SLC.zip> --bounds W S E N --out PATH
                                [--pol vv] [--res 20] [--looks 8 2]
"""
import os
os.environ.pop("PYTHONPATH", None)
import sys, zipfile, argparse, time
# PROJ 데이터 경로를 명시하지 않으면 이 env 에서 GDAL 이 EPSG 코드를 해석하지 못한다.
_proj = os.path.join(os.environ.get("CONDA_PREFIX", ""), "share", "proj")
if os.path.isdir(_proj):
    os.environ.setdefault("PROJ_DATA", _proj)
    os.environ.setdefault("PROJ_LIB", _proj)
import xml.etree.ElementTree as ET
import numpy as np
from osgeo import gdal, osr

gdal.UseExceptions()
gdal.SetCacheMax(1 << 30)


def burst_valid_mask(zf, meas_name, ny, nx):
    """제품 annotation 의 firstValidSample/lastValidSample → 라인별 유효 여부·유효 열구간.

    TOPS 버스트는 앞뒤 40~50 라인이 무효다(값이 0 은 아니고 아주 작다). 값으로 걸러내면
    저후방산란 지역까지 지워지므로, 제품이 명시한 유효구간을 그대로 쓴다.
    """
    stem = os.path.basename(meas_name).rsplit(".", 1)[0]
    cand = [n for n in zf.namelist()
            if "/annotation/" in n and n.endswith(stem + ".xml")
            and os.path.basename(n).startswith("s1")]
    if not cand:
        return None, None, None, None
    st = ET.fromstring(zf.read(cand[0])).find(".//swathTiming")
    lpb = int(st.find("linesPerBurst").text)
    bursts = st.findall(".//burst")
    fvs = np.full(ny, -1, dtype=np.int32)
    lvs = np.full(ny, -1, dtype=np.int32)
    for i, b in enumerate(bursts):
        y0 = i * lpb
        if y0 >= ny:
            break
        f = np.array([int(v) for v in b.find("firstValidSample").text.split()], dtype=np.int32)
        l = np.array([int(v) for v in b.find("lastValidSample").text.split()], dtype=np.int32)
        n = min(lpb, ny - y0, len(f))
        fvs[y0:y0 + n] = f[:n]
        lvs[y0:y0 + n] = l[:n]
    return fvs, lvs, lpb, int((fvs < 0).sum())

ap = argparse.ArgumentParser()
ap.add_argument("zip")
ap.add_argument("--bounds", nargs=4, type=float, required=True, metavar=("W", "S", "E", "N"))
ap.add_argument("--out", required=True)
ap.add_argument("--pol", default="vv")
ap.add_argument("--res", type=float, default=20.0, help="출력 격자(m)")
ap.add_argument("--looks", nargs=2, type=int, default=[8, 2], metavar=("RANGE", "AZIMUTH"))
ap.add_argument("--fill", type=int, default=12, help="버스트 경계 빈줄 보간 반복횟수(한 번에 1px씩 확산). 0=끄기")
a = ap.parse_args()

W, S, E, N = a.bounds
RL, AL = a.looks
dlat = a.res / 111320.0
dlon = a.res / (111320.0 * np.cos(np.deg2rad((S + N) / 2)))
OW = int(round((E - W) / dlon)); OH = int(round((N - S) / dlat))
print("출력 %dx%d @%.0fm  W%.4f S%.4f E%.4f N%.4f" % (OW, OH, a.res, W, S, E, N), flush=True)

zpath = os.path.abspath(a.zip)
z = zipfile.ZipFile(zpath)
meas = sorted(n for n in z.namelist()
              if "/measurement/" in n and n.endswith(".tiff") and ("-%s-" % a.pol) in n.lower())
if not meas:
    sys.exit("measurement tiff 없음 (pol=%s)" % a.pol)

t0 = time.time()
srcs = []
for m in meas:
    ds = gdal.Open("/vsizip/%s/%s" % (zpath, m))
    nx, ny = ds.RasterXSize, ds.RasterYSize
    gcps = ds.GetGCPs()
    lons = [p.GCPX for p in gcps]; lats = [p.GCPY for p in gcps]
    if max(lons) < W or min(lons) > E or max(lats) < S or min(lats) > N:
        print("  %-14s 범위 밖 — 건너뜀" % os.path.basename(m)[4:12], flush=True)
        ds = None
        continue

    fvs, lvs, lpb, n_inv = burst_valid_mask(z, m, ny, nx)
    if fvs is None:
        sys.exit("annotation 을 찾지 못했다: %s" % m)
    mx = nx // RL
    band = ds.GetRasterBand(1)
    cols = np.arange(mx * RL, dtype=np.int32)
    my = ny // AL
    acc = np.zeros((my, mx), dtype=np.float32)
    CH = AL * 512                                       # 청크 높이(멀티룩 배수)
    for y0 in range(0, my * AL, CH):
        h = min(CH, my * AL - y0)
        blk = band.ReadAsArray(0, y0, mx * RL, h)       # complex64
        it = (blk.real.astype(np.float32) ** 2 + blk.imag.astype(np.float32) ** 2)
        f = fvs[y0:y0 + h][:, None]; l = lvs[y0:y0 + h][:, None]
        it[(f < 0) | (cols[None, :] < f) | (cols[None, :] > l)] = 0.0   # 무효 라인·열 → 0
        it = it.reshape(h // AL, AL, mx, RL)
        cnt = (it > 0).sum(axis=(1, 3))
        cell = it.sum(axis=(1, 3)) / np.maximum(cnt, 1)  # 유효 샘플 수로만 나눈다
        cell[cnt < 0.5 * AL * RL] = 0.0                  # 절반 미만이면 nodata
        acc[y0 // AL: y0 // AL + h // AL] = cell
        del blk, it, cnt, cell

    mem = gdal.GetDriverByName("MEM").Create("", mx, my, 1, gdal.GDT_Float32)
    mem.GetRasterBand(1).WriteArray(acc)
    mem.GetRasterBand(1).SetNoDataValue(0.0)
    sr = osr.SpatialReference(); sr.ImportFromEPSG(4326)
    mem.SetGCPs([gdal.GCP(p.GCPX, p.GCPY, p.GCPZ, p.GCPPixel / RL, p.GCPLine / AL) for p in gcps],
                sr.ExportToWkt())
    srcs.append(mem)
    print("  %-14s %dx%d → 멀티룩 %dx%d · 버스트 무효라인 %d  (%.0fs)"
          % (os.path.basename(m)[4:12], nx, ny, mx, my, n_inv, time.time() - t0), flush=True)
    ds = None

if not srcs:
    sys.exit("대상 영역과 겹치는 서브스와스 없음")

warped = gdal.Warp("", srcs, format="MEM", dstSRS="EPSG:4326", tps=True, resampleAlg="average",
                   outputBounds=(W, S, E, N), width=OW, height=OH,
                   outputType=gdal.GDT_Float32, srcNodata=0, dstNodata=0)
inten = warped.GetRasterBand(1).ReadAsArray()
srcs = None; warped = None

# 버스트 경계의 무효 라인이 얇은 사선으로 남는다 → 유효 이웃 평균으로 반복 확산해 메움.
# gdal.FillNodata 는 이 MEM 밴드에서 동작하지 않아 직접 처리한다.
if a.fill > 0:
    from scipy.ndimage import uniform_filter
    v = np.where(inten > 0, inten, np.nan)
    for _ in range(a.fill):
        bad = ~np.isfinite(v)
        if not bad.any():
            break
        ok = (~bad).astype(np.float32)
        num = uniform_filter(np.where(bad, 0.0, v).astype(np.float32), size=3, mode="nearest")
        den = uniform_filter(ok, size=3, mode="nearest")
        v = np.where(bad & (den > 0), num / np.maximum(den, 1e-9), v)
    inten = np.where(np.isfinite(v), v, 0.0)

with np.errstate(divide="ignore", invalid="ignore"):
    db = 10.0 * np.log10(np.where(inten > 0, inten, np.nan)).astype(np.float32)

drv = gdal.GetDriverByName("GTiff")
out = drv.Create(a.out, OW, OH, 1, gdal.GDT_Float32,
                 options=["COMPRESS=DEFLATE", "TILED=YES", "BIGTIFF=IF_SAFER"])
out.SetGeoTransform((W, dlon, 0, N, 0, -dlat))
sr = osr.SpatialReference(); sr.ImportFromEPSG(4326); out.SetProjection(sr.ExportToWkt())
b = out.GetRasterBand(1); b.WriteArray(db); b.SetNoDataValue(float("nan"))
f = db[np.isfinite(db)]
b.SetStatistics(float(f.min()), float(f.max()), float(f.mean()), float(f.std()))
out.SetMetadata({
    "source": os.path.basename(a.zip),
    "polarisation": a.pol.upper(),
    "units": "SLC intensity in dB = 10*log10(|z|^2), uncalibrated",
    "looks": "%d rg x %d az" % (RL, AL),
    "pixel_m": "%.0f" % a.res,
    "geocoding": "GCP + thin-plate spline, no DEM (approximate)",
    "burst_gap_fill": ("neighbour-mean diffusion, %d iterations" % a.fill) if a.fill else "none",
})
out = None

lo, hi = np.percentile(f, [2, 98])
print("저장 %s\n  유효 %.1f%% · 값 %.1f ~ %.1f dB · 권장 표출 %.1f ~ %.1f · %.0fs"
      % (a.out, 100 * np.isfinite(db).mean(), np.nanmin(db), np.nanmax(db), lo, hi, time.time() - t0),
      flush=True)
