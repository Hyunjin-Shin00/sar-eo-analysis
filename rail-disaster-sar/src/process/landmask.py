"""SRTM 1Sec HGT 로 육지 마스크를 만든다.

해면 오탐 방지용. SAR 침수탐지에서 바다는 풍속에 따라 후방산란이 크게 변해
「거친 바다 → 잔잔한 바다」가 침수와 똑같은 신호(큰 음수 변화 + 낮은 절대값)를 만든다.
千葉 사례에서 실제로 해면 변화 287 km² 가 침수로 오검출됐다.

SRTM 은 해수면을 0 으로 채우므로 elevation > 0 을 육지로 본다.
"""
import os, zipfile, pathlib
os.environ.pop("PYTHONPATH", None)
import numpy as np

SRTM = pathlib.Path.home()/".snap"/"auxdata"/"dem"/"SRTM 1Sec HGT"


def read_tile(lat, lon):
    """1°×1° SRTM 타일을 3601×3601 int16 배열로 읽는다. 없으면 None."""
    name = f"{'N' if lat>=0 else 'S'}{abs(lat):02d}{'E' if lon>=0 else 'W'}{abs(lon):03d}"
    z = SRTM/f"{name}.SRTMGL1.hgt.zip"
    if not z.exists():
        return None
    with zipfile.ZipFile(z) as f:
        n = [x for x in f.namelist() if x.lower().endswith(".hgt")][0]
        a = np.frombuffer(f.read(n), dtype=">i2")
    return a.reshape(3601, 3601)


def elevation_at(lats, lons):
    """임의 위경도 배열의 SRTM 표고. 타일 없으면 NaN."""
    out = np.full(lats.shape, np.nan, np.float32)
    for la in range(int(np.floor(np.nanmin(lats))), int(np.floor(np.nanmax(lats)))+1):
        for lo in range(int(np.floor(np.nanmin(lons))), int(np.floor(np.nanmax(lons)))+1):
            t = read_tile(la, lo)
            if t is None:
                continue
            m = (lats >= la) & (lats < la+1) & (lons >= lo) & (lons < lo+1)
            if not m.any():
                continue
            r = ((la + 1 - lats[m]) * 3600).astype(int).clip(0, 3600)
            c = ((lons[m] - lo) * 3600).astype(int).clip(0, 3600)
            v = t[r, c].astype(np.float32)
            v[v <= -32000] = np.nan          # void
            out[m] = v
    return out


def land_mask(profile, min_elev=0.5):
    """래스터 profile 격자에 대한 육지 마스크(bool). 표고 > min_elev 를 육지로 본다."""
    import rasterio.transform as rt
    import pyproj
    H, W = profile["height"], profile["width"]
    rows, cols = np.meshgrid(np.arange(H), np.arange(W), indexing="ij")
    xs, ys = rt.xy(profile["transform"], rows.ravel(), cols.ravel())
    tf = pyproj.Transformer.from_crs(profile["crs"], 4326, always_xy=True)
    lon, lat = tf.transform(np.asarray(xs), np.asarray(ys))
    e = elevation_at(lat.reshape(H, W), lon.reshape(H, W))
    return np.isfinite(e) & (e > min_elev), e


if __name__ == "__main__":
    import rasterio, sys
    p = sys.argv[1]
    with rasterio.open(p) as s:
        prof = s.profile
    m, e = land_mask(prof)
    px = abs(prof["transform"].a*prof["transform"].e)/1e6
    print(f"격자 {prof['width']}x{prof['height']}  육지 {m.sum()*px:.0f} km² / 전체 {m.size*px:.0f} km² "
          f"({m.mean()*100:.1f}%)")
    print(f"표고: 유효 {np.isfinite(e).mean()*100:.1f}%  중앙 {np.nanmedian(e):.1f} m  최대 {np.nanmax(e):.0f} m")


def elevation_grid(profile):
    """래스터 격자의 SRTM 표고(m). land_mask 와 같은 방식이지만 마스크 없이 표고만 돌려준다."""
    import rasterio.transform as rt
    import pyproj
    H, W = profile["height"], profile["width"]
    rows, cols = np.meshgrid(np.arange(H), np.arange(W), indexing="ij")
    xs, ys = rt.xy(profile["transform"], rows.ravel(), cols.ravel())
    tf = pyproj.Transformer.from_crs(profile["crs"], 4326, always_xy=True)
    lon, lat = tf.transform(np.asarray(xs), np.asarray(ys))
    return elevation_at(lat.reshape(H, W), lon.reshape(H, W))


def slope_deg(profile, elev=None, smooth_m=40.0):
    """지형 경사(도). SRTM 은 1 m 단위 정수라 10 m 격자에서 계단 잡음이 생긴다 →
    약 smooth_m 규모로 평활한 뒤 기울기를 낸다. 물은 평탄면에만 고이므로 경사는 강력한 오탐 필터다."""
    from scipy import ndimage
    if elev is None:
        elev = elevation_grid(profile)
    px = abs(profile["transform"].a)
    e = np.where(np.isfinite(elev), elev, np.nan)
    k = max(int(round(smooth_m/px)), 1)
    filled = np.nan_to_num(e, nan=float(np.nanmedian(e)))
    sm = ndimage.uniform_filter(filled, size=k, mode="nearest")
    gy, gx = np.gradient(sm, abs(profile["transform"].e), px)
    s = np.degrees(np.arctan(np.hypot(gx, gy)))
    s[~np.isfinite(elev)] = np.nan
    return s
