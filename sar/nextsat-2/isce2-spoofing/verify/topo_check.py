"""Is the CSK unwrapped phase dominated by uncompensated topography?
Regress unwrapped phase (radar, multilooked) against independent DEM height sampled at lat/lon.rdr.
Expected slope if topography-only: 2*pi/HoA (HoA from recompute_geometry.py)."""
import sys, json
import numpy as np, rasterio
import xml.etree.ElementTree as ET

ifg, geom, demtif, hoa = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
r = ET.parse(f'{ifg}/topophase.cor.xml').getroot()
W = int(r.find(".//property[@name='width']/value").text); L = int(r.find(".//property[@name='length']/value").text)
unw = np.fromfile(f'{ifg}/filt_topophase.unw.phase2', np.float32).reshape(L, W)
cc = np.fromfile(f'{ifg}/filt_topophase.unw.phase2.conncomp', np.uint8).reshape(L, W)
coh = np.fromfile(f'{ifg}/topophase.cor', np.float32).reshape(L, 2, W)[:, 1, :]
lat = np.fromfile(f'{geom}/lat.rdr', np.float64).reshape(L, W)
lon = np.fromfile(f'{geom}/lon.rdr', np.float64).reshape(L, W)
s = (slice(None, None, 4), slice(None, None, 4))
u, la, lo, c, k = unw[s].ravel(), lat[s].ravel(), lon[s].ravel(), coh[s].ravel(), cc[s].ravel()
with rasterio.open(demtif) as d:
    inv = ~d.transform
    cols, rows = inv * (lo, la)
    rows, cols = np.floor(rows).astype(int), np.floor(cols).astype(int)
    ok = (rows >= 0) & (rows < d.height) & (cols >= 0) & (cols < d.width)
    a = d.read(1)
h = np.full(u.shape, np.nan); h[ok] = a[rows[ok], cols[ok]]
m = ok & (k > 0) & (c > 0.3) & np.isfinite(h) & np.isfinite(u) & (np.abs(la) > 1)
x, y = h[m], u[m]
A = np.vstack([x, np.ones_like(x)]).T
coef, *_ = np.linalg.lstsq(A, y, rcond=None)
pred = A @ coef
r2 = 1 - np.sum((y - pred) ** 2) / np.sum((y - y.mean()) ** 2)
out = dict(n=int(m.sum()), dem_height_range_m=[float(np.percentile(x, 2)), float(np.percentile(x, 98))],
           pearson_r=float(np.corrcoef(x, y)[0, 1]), slope_rad_per_m=float(coef[0]), r2=float(r2),
           expected_abs_slope_topo_only=float(2 * np.pi / hoa), implied_HoA_m=float(2 * np.pi / abs(coef[0])),
           residual_std_rad=float(np.std(y - pred)), residual_std_LOS_mm=float(np.std(y - pred) * 0.0312284 / (4 * np.pi) * 1000))
print(json.dumps(out, indent=1))
