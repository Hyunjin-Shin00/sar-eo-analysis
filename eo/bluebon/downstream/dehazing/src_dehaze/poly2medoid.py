import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

# def extract_representatives(X, k):
#     X = np.asarray(X)

#     # Optional: standardize
#     scaler = StandardScaler()
#     X_std = scaler.fit_transform(X)

#     # KMeans doesn't build an n×n matrix, it's fine for large n
#     kmeans = KMeans(
#         n_clusters=k,
#         random_state=0,
#         n_init="auto",   # or an int like 10
#     )
#     labels = kmeans.fit_predict(X_std)
#     centers = kmeans.cluster_centers_

#     rep_indices = []
#     for j in range(k):
#         mask = (labels == j)
#         if not np.any(mask):
#             continue  # cluster empty, can be skipped or handled specially

#         cluster_idx = np.where(mask)[0]
#         cluster_points = X_std[mask]

#         # distance to centroid
#         dists = np.linalg.norm(cluster_points - centers[j], axis=1)
#         local_min = np.argmin(dists)
#         global_idx = cluster_idx[local_min]

#         rep_indices.append(global_idx)

#     rep_indices = np.array(rep_indices, dtype=int)
#     reps = X[rep_indices]   # representatives in original space
#     return reps, rep_indices


def extract_representatives(X, k, include_extremes=True):
    X = np.asarray(X)

    # Standardize
    scaler = StandardScaler()
    X_std = scaler.fit_transform(X)

    kmeans = KMeans(
        n_clusters=k,
        random_state=0,
        n_init="auto",
    )
    labels = kmeans.fit_predict(X_std)
    centers = kmeans.cluster_centers_

    rep_indices = []
    extreme_indices = []

    for j in range(k):
        mask = (labels == j)
        if not np.any(mask):
            continue

        cluster_idx = np.where(mask)[0]
        cluster_points = X_std[mask]

        # distances to centroid
        dists = np.linalg.norm(cluster_points - centers[j], axis=1)

        # representative (closest)
        min_idx = cluster_idx[np.argmin(dists)]
        rep_indices.append(min_idx)

        if include_extremes:
            # extreme (farthest)
            max_idx = cluster_idx[np.argmax(dists)]
            extreme_indices.append(max_idx)

    rep_indices = np.array(rep_indices, dtype=int)
    extreme_indices = np.array(extreme_indices, dtype=int)

    # combine (avoid duplicates)
    all_indices = np.unique(np.concatenate([rep_indices, extreme_indices]))

    reps = X[rep_indices]
    extremes = X[extreme_indices] if include_extremes else None
    selected = X[all_indices]

    return reps, rep_indices, extremes, extreme_indices, selected, all_indices

import json
import numpy as np
import xarray as xr
from shapely.geometry import Polygon
from rasterio.features import rasterize
from affine import Affine
from PIL import Image

def polygons_to_pixelcoords_nc(fnc, fjson, var_name=None):
    """
    Find pixels in a NetCDF file that fall inside polygons defined
    in pixel space as (col, row).

    Parameters
    ----------
    fnc : str
        Path to NetCDF file.
    fjson : str
        Path to GeoJSON-like file whose coordinates are (col, row) in pixel space.
    var_name : str, optional
        Name of variable inside the NetCDF to use for height/width.
        If None, the first 2D variable will be used.

    Returns
    -------
    pixel_map : list of dict
        Each dict: {"ring_id": i, "pixel_coords": [(row, col), ...]}
    rings : list
        Original ring coordinate lists.
    """

    # --- 1. Open NetCDF and get shape (height, width) ---
    if fnc.endswith(('.nc')):
        ds = xr.open_dataset(fnc, group="geophysical_data")
    
        if var_name is None:
            # Find first 2D variable (simple heuristic)
            for v in ds.data_vars:
                if ds[v].ndim == 3:
                    var_name = v
                    break
            if var_name is None:
                raise ValueError("No 2D variable found in NetCDF; please specify var_name.")
        data = ds[var_name]  
    elif fnc.endswith(('png','jpg')):
        _data = Image.open(fnc)
        data = np.transpose(np.array(_data),[2,0,1])[:-1,:,:]
    
    
    nb, height, width = data.shape  # (rows, cols)

    # --- 2. Load polygon data (already in pixel coords col,row) ---
    with open(fjson) as f:
        jdata = json.load(f)

    if 'lat' in jdata["features"][0]["geometry"]["format"]:
        raise ValueError('the coord format must not be lon, lat')
        
    rings = jdata["features"][0]["geometry"]["coordinates"]

    # --- 3. Identity transform: (col, row) -> (x, y) = (col, row) ---
    transform_pixel = Affine(1, 0, 0,
                             0, 1, 0)  # x = col, y = row

    pixel_map = []

    for i, ring_coords in enumerate(rings):
        # GeoJSON coords are (x, y) => here interpreted as (col, row) already
        poly = Polygon(ring_coords)

        # Rasterize polygon on pixel grid
        mask = rasterize(
            [(poly, 1)],
            out_shape=(height, width),     # (rows, cols)
            transform=transform_pixel,     # identity mapping
            fill=0,
            dtype="uint8"
        )

        # Extract pixel indices
        rows, cols = np.where(mask == 1)
        pixels = list(zip(rows, cols))

        pixel_map.append({
            "ring_id": i,
            "pixel_coords": pixels
        })

    return pixel_map, rings

import sys
sys.path.append('../src')
import inpolygon_analysis
def polygon2samples(fnc, fjson, k):
    try:
        pixel_map, rings =  polygons_to_pixelcoords_nc(fnc, fjson, var_name='data')	
    except ValueError as e:
        print("Error:",e)
    data_pixels = inpolygon_analysis.inpolygon_pixel2data_nc(fnc, pixel_map) 
    X = np.transpose(data_pixels[0], (1,0))
    #data_pixels to X
    
    # reps, rep_indices = extract_representatives(X, k)
    reps, rep_indices, extremes, extreme_indices, selected, all_indices = extract_representatives(X, k)
    return reps, selected

sys.path.append('../../tools')
import ncutils
import matplotlib.pyplot as plt
def plot_reps(fnc, reps):
    if '.nc' in fnc:
        waves = ncutils.readheader(fnc)['waves']
        if waves is None:
            _nbds=ncutils.readheader(fnc)['bands']
            waves=[z+1 for z in range(_nbds)]
    elif fnc.endswith(('jpg','png')):
        waves = ['R','G','B']
    colors = plt.cm.viridis(np.linspace(0, 1, len(reps)))
    
    plt.figure()
    for i, (ydata, color) in enumerate(zip(reps, colors)):
        plt.plot(waves, ydata, color=color, label=f'Sample {i+1}')
    plt.xticks(waves, rotation=45, ha='right')
    plt.legend()
    plt.show()

if __name__ == "__main__":
    # fnc='/media/yp/T7_win31/olidata/20240313_117037_WoffJeju/OLI_rhorc.nc'
    # fnc='<WORK_ROOT>/Downloads/bluebon/251022_TakhliAP/myout/251022_042629_stacked_rhot.nc'
    # # fnc='<WORK_ROOT>/Downloads/bluebon/251123_Thai/myout/251123_041547_stacked_rhorc.nc'
    # # fnc='<WORK_ROOT>/Downloads/bluebon/251123_Thai/myout_rhorc/251123_041547_stacked_rhorc.nc'
    # # fnc='<WORK_ROOT>/Downloads/bluebon/251127_Thai/myout_rhorc/251127_041230_stacked_rhorc.nc'
    # fnc='<WORK_ROOT>/Downloads/bluebon/251022_TakhliAP/myout/251022_042629_stacked_rhot_RGB210.png'
    # fjson='<WORK_ROOT>/myPy/zview/out_tmp/polygon_tmp(2).json'
    # fnc='<WORK_ROOT>/Downloads/bluebon/260209_Suwon/myout/260209_025928_stacked_rhot.nc'
    # fnc='<WORK_ROOT>/Downloads/bluebon/260220_Suwon/myout/260220_025632_stacked_rhot.nc' #clear
    # fnc='<WORK_ROOT>/Downloads/bluebon/260220_msi_T52SCG_dehazingtest/myout/MSI_res20m_rhot.nc'
    # fnc='<WORK_ROOT>/Downloads/bluebon/250903_Namhae_msi_T52SCD/myout/MSI_res20m_rhot.nc'
    # fjson='<WORK_ROOT>/myPy_inout/zview/out_tmp/polygon_tmp(20).json'
    # fnc='<WORK_ROOT>/Downloads/bluebon/260320_LC09_116034_Suwon/OLI_rhot.nc'
    # fnc='<WORK_ROOT>/Downloads/bluebon/260304_LC09_116034_GG/OLI_rhorc.nc'
    # fnc='<WORK_ROOT>/Downloads/bluebon/260322_msi_T52SCG_Suwon/myout/MSI_res20m_rhot.nc'
    # fnc='<WORK_ROOT>/Downloads/bluebon/250821_Busan_msi_T52SDD/myout/MSI_res20m_rhorc.nc'
    # fnc='/media/yp/T7_win31/olidata/20250728_119035_Qingdao/OLI_rhorc.nc'
    # fnc='<WORK_ROOT>/Downloads/bluebon/250903_Geoje_oli_114036/OLI_rhorc.nc'
    # fnc='<WORK_ROOT>/Downloads/bluebon/260413_Kuwait/myout/260413_081143_stacked_rhot.nc'
    # fnc='/media/yp/T7_msi/msidata/20240809_T52SCJ_Wonsan1/myout/MSI_res20m_rhorc.nc'
    fnc='/media/yp/T7_msi/msidata/20260401_T51SYD_Pyeongyang/myout/MSI_res20m_rhorc.nc'
    fnc='/media/yp/T7_msi/msidata/20260416_T52SCG_Seoul/myout/MSI_res20m_rhorc.nc'
    # fnc='<WORK_ROOT>/Downloads/skydata/SkySatCollect_20250603_004246_ssc13/u0001_myout/20250603_004246_ssc13_u0001_analytic_rhorc.nc'
    fnc='<WORK_ROOT>/Downloads/CASdata/C1_20240807014521_18758_01041614_RGBN_rhot.nc'
    fnc='<WORK_ROOT>/Downloads/CASdata/20240823/C1_20240823013448_19001_00858507_RGBN_rhot.nc'
    fnc='/media/yp/T7_win31/olidata/20260506_116033_Wonsan/OLI_rhorc.nc'
    fnc='<WORK_ROOT>/Downloads/CASdata/20250619/C1_20250619012456_23559_00573599_L2G_RGBN_rhot.nc'
    fnc='<WORK_ROOT>/Downloads/CASdata/20250619_1/C1_20250619012456_23559_00611431_L2G_RGBN_rhot.nc'
    fnc='/media/yp/T7_win31/olidata/20250425_165051_Aden/OLI_rhorc.nc'
    fnc='/media/yp/T7_msi/msidata/20260423_T39RVJ_Bahrain/myout/MSI_res20m_rhorc.nc'
    fjson='<WORK_ROOT>/myPy_inout/zview/out_tmp/polygon_tmp(16).json'
    k=15
    reps, selected = polygon2samples(fnc, fjson, k)
    print(np.array2string(selected, separator=", ", max_line_width=np.inf))
    # print(reps)
    # plot_reps(fnc, reps)
    plot_reps(fnc, selected)
