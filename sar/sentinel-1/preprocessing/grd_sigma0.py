#!/usr/bin/env python
"""
Sentinel-1 GRD -> calibrated sigma0, geocoded, cropped to an AOI.

Done directly against the .SAFE zip with GDAL/rasterio rather than through SNAP,
because SNAP on this machine has a -Xmx87G vmoptions that exhausts shared memory.

Steps, all standard:
  1. read the sigmaNought calibration LUT from annotation/calibration/*.xml
  2. work out which slice of the SAR-geometry raster covers the AOI, from the
     210 product GCPs, and read only that slice
  3. sigma0 = DN^2 / sigmaNought^2, with the LUT bilinearly interpolated onto
     every pixel of that slice
  4. geocode with a thin-plate spline over the GCPs to EPSG:4326

Geolocation caveat, stated because it bounds what the corridor statistics mean:
this is ellipsoid geocoding, not Range-Doppler terrain correction. The ground
range shift is about h / tan(theta); at the Chiba incidence angle that is
roughly 1.2 x the terrain height. Over the Chiba lowland where the flooding
occurred (h < 20 m) the error is under ~25 m, which is why the rail-corridor
statistics below are reported at 250 m and wider rather than at 100 m.
"""
import os
import re
import sys
import subprocess
import xml.etree.ElementTree as ET
import zipfile

import numpy as np
import rasterio
from rasterio.control import GroundControlPoint

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "work", "tc")
os.makedirs(OUT, exist_ok=True)


def read_cal_lut(zf, name):
    """sigmaNought LUT on its (line, pixel) grid."""
    root = ET.fromstring(zf.read(name))
    lines, pixels, sigmas = [], None, []
    for v in root.iter("calibrationVector"):
        lines.append(int(v.find("line").text))
        px = np.array(v.find("pixel").text.split(), dtype=np.float64)
        sg = np.array(v.find("sigmaNought").text.split(), dtype=np.float64)
        if pixels is None:
            pixels = px
        sigmas.append(sg)
    return np.array(lines, float), pixels, np.array(sigmas)


def interp_lut(lines, pixels, sigmas, row0, nrows, col0, ncols):
    """Bilinear interpolation of the LUT onto an image window."""
    rr = np.arange(row0, row0 + nrows, dtype=np.float64)
    cc = np.arange(col0, col0 + ncols, dtype=np.float64)
    # interpolate along pixel axis for each LUT line, then along line axis
    per_line = np.empty((len(lines), ncols), dtype=np.float32)
    for i in range(len(lines)):
        per_line[i] = np.interp(cc, pixels, sigmas[i]).astype(np.float32)
    idx = np.interp(rr, lines, np.arange(len(lines), dtype=np.float64))
    lo = np.clip(np.floor(idx).astype(int), 0, len(lines) - 1)
    hi = np.clip(lo + 1, 0, len(lines) - 1)
    w = (idx - lo).astype(np.float32)[:, None]
    return per_line[lo] * (1.0 - w) + per_line[hi] * w


def gcp_window(gcps, bbox, shape, margin=400):
    """Image window (row0, nrows, col0, ncols) covering a lon/lat bbox."""
    lon = np.array([g.x for g in gcps]); lat = np.array([g.y for g in gcps])
    col = np.array([g.col for g in gcps]); row = np.array([g.row for g in gcps])
    # second-order polynomial fit (lon,lat) -> (col,row); plenty for one frame
    A = np.column_stack([np.ones_like(lon), lon, lat, lon * lat, lon ** 2, lat ** 2])
    cc, *_ = np.linalg.lstsq(A, col, rcond=None)
    rr, *_ = np.linalg.lstsq(A, row, rcond=None)
    w, s, e, n = bbox
    pts = [(x, y) for x in (w, e) for y in (s, n)]
    cs, rs = [], []
    for x, y in pts:
        a = np.array([1, x, y, x * y, x * x, y * y])
        cs.append(a @ cc); rs.append(a @ rr)
    c0 = int(max(0, min(cs) - margin)); c1 = int(min(shape[1], max(cs) + margin))
    r0 = int(max(0, min(rs) - margin)); r1 = int(min(shape[0], max(rs) + margin))
    return r0, r1 - r0, c0, c1 - c0


def process(zip_path, bbox, label, pol="vv"):
    dst = os.path.join(OUT, f"{label}.tif")
    if os.path.exists(dst) and os.path.getsize(dst) > 1_000_000:
        print(f"  [have] {label}")
        return dst
    zf = zipfile.ZipFile(zip_path)
    meas = [n for n in zf.namelist() if "/measurement/" in n and f"-{pol}-" in n and n.endswith(".tiff")][0]
    cal = [n for n in zf.namelist() if "/calibration/calibration-" in n and f"-{pol}-" in n][0]
    lines, pixels, sigmas = read_cal_lut(zf, cal)

    src = f"zip://{zip_path}!/{meas}"
    with rasterio.open(src) as ds:
        gcps, gcrs = ds.get_gcps()
        r0, nr, c0, nc = gcp_window(gcps, bbox, (ds.height, ds.width))
        print(f"  {label}: window rows {r0}..{r0+nr} cols {c0}..{c0+nc} "
              f"({nr}x{nc} of {ds.height}x{ds.width})")
        dn = ds.read(1, window=rasterio.windows.Window(c0, r0, nc, nr)).astype(np.float32)

    lut = interp_lut(lines, pixels, sigmas, r0, nr, c0, nc)
    sigma0 = (dn * dn) / (lut * lut)
    sigma0[dn == 0] = np.nan
    del dn, lut

    # GCPs that fall in (or near) the window, shifted into window coordinates
    sub = [GroundControlPoint(row=g.row - r0, col=g.col - c0, x=g.x, y=g.y, z=g.z)
           for g in gcps if (r0 - 2000) <= g.row <= (r0 + nr + 2000)
           and (c0 - 2000) <= g.col <= (c0 + nc + 2000)]
    print(f"  {label}: {len(sub)} GCPs in window")

    tmp = os.path.join(OUT, f"_{label}_sar.tif")
    with rasterio.open(tmp, "w", driver="GTiff", height=nr, width=nc, count=1,
                       dtype="float32", nodata=np.nan, gcps=sub, crs=gcrs,
                       compress="deflate", tiled=True) as o:
        o.write(sigma0, 1)
    del sigma0

    w, s, e, n = bbox
    cmd = ["gdalwarp", "-tps", "-r", "bilinear", "-t_srs", "EPSG:4326",
           "-te", str(w), str(s), str(e), str(n),
           "-tr", "0.0001", "0.0001", "-dstnodata", "nan",
           "-co", "COMPRESS=DEFLATE", "-co", "TILED=YES",
           "-overwrite", tmp, dst]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print("  gdalwarp failed:", p.stderr[-400:])
        return None
    os.remove(tmp)
    with rasterio.open(dst) as ds:
        a = ds.read(1)
        ok = np.isfinite(a) & (a > 0)
        print(f"  [ok] {label} {ds.width}x{ds.height} valid={ok.mean()*100:.1f}% "
              f"sigma0_dB median={10*np.log10(np.median(a[ok])):.2f}")
    return dst


JOBS = {
    # label: (zip glob fragment, bbox)
    "chiba_desc_pre":  ("S1D_IW_GRDH_1SDV_20260801T2042", (140.06, 35.44, 140.47, 35.75)),
    "chiba_desc_post": ("S1D_IW_GRDH_1SDV_20260813T2042", (140.06, 35.44, 140.47, 35.75)),
    "chiba_asc_pre":   ("S1C_IW_GRDH_1SDV_20260802T0832", (140.06, 35.44, 140.47, 35.75)),
    "chiba_asc_post":  ("S1C_IW_GRDH_1SDV_20260814T0832", (140.06, 35.44, 140.47, 35.75)),
    "chiba_desc_null": ("S1D_IW_GRDH_1SDV_20260720T2042", (140.06, 35.44, 140.47, 35.75)),
    "chiba_asc_null":  ("S1C_IW_GRDH_1SDV_20260721T0832", (140.06, 35.44, 140.47, 35.75)),
    "tohoku_null":     ("S1A_IW_GRDH_1SDV_20240711T2043", (140.19, 38.56, 140.63, 38.92)),
    "tohoku_pre":      ("S1A_IW_GRDH_1SDV_20240723T2043", (140.19, 38.56, 140.63, 38.92)),
    "tohoku_post":     ("S1A_IW_GRDH_1SDV_20240804T2043", (140.19, 38.56, 140.63, 38.92)),
}

if __name__ == "__main__":
    s1dir = os.path.join(ROOT, "work", "s1")
    want = sys.argv[1:] or list(JOBS)
    pols = ["vv", "vh"]
    for label in want:
        frag, bbox = JOBS[label]
        zips = [f for f in sorted(os.listdir(s1dir)) if f.startswith(frag) and f.endswith(".zip")]
        if not zips:
            print(f"  [skip] {label}: no zip matching {frag}")
            continue
        zp = os.path.join(s1dir, zips[0])
        for pol in pols:
            try:
                process(zp, bbox, f"{label}_{pol}", pol=pol)
            except Exception as e:
                print(f"  [ERR] {label}_{pol}: {type(e).__name__} {str(e)[:160]}")
