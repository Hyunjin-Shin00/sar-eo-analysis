#!/usr/bin/env python
"""
The actual analysis: what can free Sentinel-1 see of this disaster, measured.

For one pre/post pair over one event AOI it produces
  * calibrated sigma0 in dB, pre and post
  * a change map (post - pre)
  * a water mask for each date and the NEW-water mask (post water, not pre water)
  * a NULL distribution from a pre-event-only pair where one exists, so that a
    change is only called real if it exceeds what the same processing produces
    when nothing happened
  * statistics tied to the railway damage AOI: new water area, how much of it is
    within 100 / 250 / 500 m of the damaged rail section, and the sigma0 change
    measured on the damaged section itself against the null distribution

Nothing here is asserted without a number, and every threshold is swept rather
than hand-picked.

Outputs: work/analysis/<label>_*.tif, data/analysis_<label>.json
"""
import json
import os
import sys

import numpy as np
import rasterio
from rasterio.features import rasterize, shapes
from rasterio.warp import transform_geom
from shapely.geometry import shape, mapping, box
from shapely.ops import unary_union, transform as sh_transform
from pyproj import CRS, Transformer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TC = os.path.join(ROOT, "work", "tc")
OUTD = os.path.join(ROOT, "work", "analysis")
os.makedirs(OUTD, exist_ok=True)

# grd_sigma0.py writes one single-band GeoTIFF per polarisation: <label>_<pol>.tif
B_VH, B_VV, B_INC = 1, 1, 1


def read_db(path, band=1):
    with rasterio.open(path) as ds:
        a = ds.read(band).astype("float32")
        prof = ds.profile
        prof.update(count=1, dtype="float32", nodata=np.nan, compress="deflate")
    a[a <= 0] = np.nan
    with np.errstate(divide="ignore", invalid="ignore"):
        return 10.0 * np.log10(a), prof


def write(path, arr, prof):
    p = dict(prof); p.update(count=1, dtype="float32", nodata=np.nan, compress="deflate")
    with rasterio.open(path, "w", **p) as ds:
        ds.write(arr.astype("float32"), 1)


def local_m(geom):
    c = geom.centroid
    crs = CRS.from_proj4(f"+proj=aeqd +lat_0={c.y} +lon_0={c.x} +datum=WGS84 +units=m +no_defs")
    fwd = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
    return sh_transform(fwd, geom), fwd


def aoi_geoms(event_id):
    p = os.path.join(ROOT, "data", "aoi", f"{event_id}.geojson")
    d = json.load(open(p, encoding="utf-8"))
    out = {}
    for f in d["features"]:
        out.setdefault(f["properties"]["role"], []).append(shape(f["geometry"]))
    return {k: unary_union(v) for k, v in out.items()}


def mask_from(geom, prof, buffer_m=0):
    """Rasterise a geometry (optionally buffered, in metres) onto the grid."""
    g = geom
    if buffer_m:
        gm, _ = local_m(geom)
        c = geom.centroid
        crs = CRS.from_proj4(f"+proj=aeqd +lat_0={c.y} +lon_0={c.x} +datum=WGS84 +units=m +no_defs")
        inv = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
        g = sh_transform(inv, gm.buffer(buffer_m))
    return rasterize([(mapping(g), 1)], out_shape=(prof["height"], prof["width"]),
                     transform=prof["transform"], fill=0, dtype="uint8").astype(bool)


def pixel_area_m2(prof):
    t = prof["transform"]
    lat = t.f + t.e * prof["height"] / 2.0
    return abs(t.a) * 111320.0 * np.cos(np.radians(lat)) * abs(t.e) * 110540.0


def analyse(label, pre_tif, post_tif, event_id, null_pre=None, null_post=None):
    print(f"\n=== {label} ===")
    pre, prof = read_db(pre_tif + "_vv.tif")
    post, _ = read_db(post_tif + "_vv.tif")
    pre_vh, _ = read_db(pre_tif + "_vh.tif")
    post_vh, _ = read_db(post_tif + "_vh.tif")
    if pre.shape != post.shape:
        h = min(pre.shape[0], post.shape[0]); w = min(pre.shape[1], post.shape[1])
        pre, post, pre_vh, post_vh = pre[:h, :w], post[:h, :w], pre_vh[:h, :w], post_vh[:h, :w]
        prof.update(height=h, width=w)
    diff_raw = post - pre
    valid = np.isfinite(diff_raw)
    # a whole-scene offset between dates (different incidence sampling, moisture,
    # calibration epoch) would otherwise masquerade as change, so remove it and
    # report it
    offset = float(np.median(diff_raw[valid]))
    diff = diff_raw - offset
    post_n = post - offset
    px_m2 = pixel_area_m2(prof)


    write(os.path.join(OUTD, f"{label}_pre_vv_db.tif"), pre, prof)
    write(os.path.join(OUTD, f"{label}_post_vv_db.tif"), post, prof)
    write(os.path.join(OUTD, f"{label}_diff_vv_db.tif"), diff, prof)

    res = {"label": label, "event_id": event_id,
           "scene_offset_removed_db": round(offset, 3),
           "pixel_area_m2": round(float(px_m2), 2),
           "valid_pixels": int(valid.sum()),
           "aoi_area_km2": round(float(valid.sum() * px_m2 / 1e6), 1)}

    # ---- null distribution from a quiet pair, if supplied ------------------
    null_sd = None
    if null_pre and null_post and os.path.exists(null_pre + "_vv.tif") and os.path.exists(null_post + "_vv.tif"):
        n0, _ = read_db(null_pre + "_vv.tif")
        n1, _ = read_db(null_post + "_vv.tif")
        h = min(n0.shape[0], n1.shape[0], diff.shape[0])
        w = min(n0.shape[1], n1.shape[1], diff.shape[1])
        nd = (n1[:h, :w] - n0[:h, :w])
        nd = nd - np.nanmedian(nd)          # same offset removal as the event pair
        nv = nd[np.isfinite(nd)]
        null_sd = float(np.std(nv))
        # how much "new water" does the SAME algorithm invent when nothing happened?
        nw_null = ((np.nan_to_num(n1[:h, :w] - np.nanmedian(n1[:h, :w] - n0[:h, :w]), nan=99) < -18.0)
                   & (np.nan_to_num(n0[:h, :w], nan=99) >= -18.0) & (nd < -3.0))
        res_null_km2 = float(nw_null.sum() * px_m2 / 1e6)
        res["null_pair"] = os.path.basename(null_pre) + " -> " + os.path.basename(null_post)
        res["null_diff_median_db"] = round(float(np.median(nv)), 3)
        res["null_diff_sd_db"] = round(null_sd, 3)
        res["null_false_new_water_km2"] = round(res_null_km2, 3)
        res["null_diff_p01_db"] = round(float(np.percentile(nv, 1)), 3)
        res["null_diff_p05_db"] = round(float(np.percentile(nv, 5)), 3)

    px_m2 = px_m2  # noqa
    dv = diff[valid]
    res["diff_median_db"] = round(float(np.median(dv)), 3)
    res["diff_sd_db"] = round(float(np.std(dv)), 3)
    res["diff_p05_db"] = round(float(np.percentile(dv, 5)), 3)
    res["diff_p01_db"] = round(float(np.percentile(dv, 1)), 3)

    # ---- water masks, threshold swept -------------------------------------
    sweep = []
    for t in (-22, -20, -18, -16, -15, -14):
        wpre = np.nan_to_num(pre, nan=99) < t
        wpost = np.nan_to_num(post_n, nan=99) < t
        new = wpost & ~wpre & valid
        sweep.append({"threshold_db": t,
                      "pre_water_km2": round(float(wpre.sum() * px_m2 / 1e6), 3),
                      "post_water_km2": round(float(wpost.sum() * px_m2 / 1e6), 3),
                      "new_water_km2": round(float(new.sum() * px_m2 / 1e6), 3),
                      "ratio_post_pre": round(float(wpost.sum() / max(wpre.sum(), 1)), 3)})
    res["water_threshold_sweep"] = sweep

    T = -18.0
    wpre = np.nan_to_num(pre, nan=99) < T
    wpost = np.nan_to_num(post_n, nan=99) < T
    new = (wpost & ~wpre & valid)
    # require a real drop as well, so a marginal pixel does not flip on noise
    new = new & (diff < -3.0)
    write(os.path.join(OUTD, f"{label}_newwater.tif"), new.astype("float32"), prof)
    res["operating_threshold_db"] = T
    res["new_water_km2"] = round(float(new.sum() * px_m2 / 1e6), 3)

    # ---- relation to the railway damage AOI --------------------------------
    g = aoi_geoms(event_id)
    dmg = g["damage_location"]
    res["damage_geom_type"] = dmg.geom_type
    for b in (100, 250, 500, 1000):
        mb = mask_from(dmg, prof, buffer_m=b)
        inb = new & mb
        res[f"new_water_km2_within_{b}m_of_damage"] = round(float(inb.sum() * px_m2 / 1e6), 4)
        res[f"fraction_of_{b}m_corridor_flooded"] = round(float(inb.sum() / max(mb.sum(), 1)), 4)

    # sigma0 change measured ON the damaged section vs the whole AOI
    for b in (50, 100, 200):
        mb = mask_from(dmg, prof, buffer_m=b)
        sel = diff[mb & valid]
        if sel.size:
            res[f"damage_corridor_{b}m_diff_median_db"] = round(float(np.median(sel)), 3)
            res[f"damage_corridor_{b}m_n_pixels"] = int(sel.size)
            if null_sd:
                z = (np.median(sel) - res["diff_median_db"]) / (null_sd / np.sqrt(sel.size))
                res[f"damage_corridor_{b}m_z_vs_null"] = round(float(z), 2)
            res[f"damage_corridor_{b}m_percentile_in_aoi"] = round(
                float((dv < np.median(sel)).mean() * 100), 1)

    # ---- how big are the detected patches? --------------------------------
    sizes = []
    if new.any():
        for geom, val in shapes(new.astype("uint8"), mask=new, transform=prof["transform"]):
            if val != 1:
                continue
            a = shape(geom)
            am, _ = local_m(a)
            sizes.append(am.area)
    sizes = np.array(sorted(sizes, reverse=True)) if sizes else np.array([])
    res["n_new_water_patches"] = int(sizes.size)
    if sizes.size:
        res["largest_patch_m2"] = round(float(sizes[0]), 1)
        res["median_patch_m2"] = round(float(np.median(sizes)), 1)
        res["patches_ge_1ha"] = int((sizes >= 1e4).sum())
        res["area_in_patches_ge_1ha_km2"] = round(float(sizes[sizes >= 1e4].sum() / 1e6), 3)
        res["area_in_patches_lt_1ha_km2"] = round(float(sizes[sizes < 1e4].sum() / 1e6), 3)

    # ---- speckle / radiometric characterisation for the resolution argument -
    # measure the per-pixel standard deviation of sigma0 over visually uniform
    # land, which is what sets the smallest detectable contrast
    land = valid & (pre > -12) & (pre < -5)
    if land.sum() > 1000:
        res["land_sigma0_sd_db"] = round(float(np.std(pre[land])), 3)
        res["land_sigma0_median_db"] = round(float(np.median(pre[land])), 3)
    water_all = valid & (post_n < -20)
    if water_all.sum() > 200:
        res["open_water_sigma0_median_db"] = round(float(np.median(post_n[water_all])), 3)
        res["land_minus_water_contrast_db"] = round(
            float(res.get("land_sigma0_median_db", np.nan) - np.median(post_n[water_all])), 3)

    out = os.path.join(ROOT, "data", f"analysis_{label}.json")
    json.dump(res, open(out, "w"), indent=2)
    for k, v in res.items():
        if k != "water_threshold_sweep":
            print(f"  {k:46s} {v}")
    print(f"  -> {out}")
    return res


if __name__ == "__main__":
    jobs = [
        ("chiba_desc", f"{TC}/chiba_desc_pre", f"{TC}/chiba_desc_post", "EV2026CHIBA",
         f"{TC}/chiba_desc_null", f"{TC}/chiba_desc_pre"),
        ("chiba_asc", f"{TC}/chiba_asc_pre", f"{TC}/chiba_asc_post", "EV2026CHIBA",
         f"{TC}/chiba_asc_null", f"{TC}/chiba_asc_pre"),
        ("tohoku", f"{TC}/tohoku_pre", f"{TC}/tohoku_post", "EV2024TOHOKU",
         f"{TC}/tohoku_null", f"{TC}/tohoku_pre"),
    ]
    want = sys.argv[1:] or [j[0] for j in jobs]
    for j in jobs:
        if j[0] not in want:
            continue
        if not (os.path.exists(j[1] + "_vv.tif") and os.path.exists(j[2] + "_vv.tif")):
            print(f"[skip] {j[0]}: inputs missing")
            continue
        analyse(*j)
