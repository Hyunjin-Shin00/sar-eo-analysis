
from sarpy.io.complex.converter import open_complex
import json
from pyproj import Transformer
import rasterio
from rasterio.transform import from_origin
import numpy as np
import matplotlib.pyplot as plt
import calc

#---------------------------------------------------------------------------
# DESCRIPTION:
#> @brief
#> 
#
#> @param[in] N/A
#> @param[out] N/A
#> @return N/A
#---------------------------------------------------------------------------
def read_umbra_slc(input_file):
    # Read SICD file
    reader = open_complex(input_file)
    slc_data = reader.read()
    meta_data = reader.sicd_meta

    return slc_data, meta_data

#---------------------------------------------------------------------------
# DESCRIPTION:
#> @brief
#> 
#
#> @param[in] N/A
#> @param[out] N/A
#> @return N/A
#---------------------------------------------------------------------------
def write_geotiff(json_file, output_file, stack_data):
    num_band, num_rows, num_cols = stack_data.shape
    
    with open(json_file) as f:
        meta = json.load(f)
    
    # Determine metadata type
    is_stac = "geometry" in meta and "coordinates" in meta["geometry"]
    if is_stac:
        ul_lon, ul_lat = meta["geometry"]["coordinates"][0][0][:2]
        az_spacing = meta["properties"].get("sar:resolution_azimuth")
        rg_spacing = meta["properties"].get("sar:resolution_range")
    else:
        footprint = meta["collects"][0]["footprintPolygonLla"]['coordinates']
        ul_lon = footprint[0][1][0]
        ul_lat = footprint[0][0][1]
        ground_res = meta["derivedProducts"]["SICD"][0]["groundResolution"]
        az_spacing = ground_res["azimuthMeters"]
        rg_spacing = ground_res["rangeMeters"]

    # Coordinate transformation and transform setup
    zone, epsg_code = calc.get_utm_epsg(ul_lon, ul_lat)
    crs_str = f"EPSG:{epsg_code}"
    transformer = Transformer.from_crs("EPSG:4326", crs_str, always_xy=True)
    x_ul, y_ul = transformer.transform(ul_lon, ul_lat)
    transform = from_origin(x_ul, y_ul, rg_spacing, az_spacing)

    # Metadata tags
    meta_tags = {
        "SATELLITE": meta.get("umbraSatelliteName", meta.get("properties", {}).get("platform", "UMBRA")),
        "START_TIME": meta.get("collects", [{}])[0].get("startAtUTC", meta.get("properties", {}).get("start_datetime", "")),
        "END_TIME": meta.get("collects", [{}])[0].get("endAtUTC", meta.get("properties", {}).get("end_datetime", "")),
        "MISSION": "UMBRA",
        "BAND_DESCRIPTIONS": "sigma0_dB",
        "UTM_ZONE": str(zone)
    }

    # GeoTIFF save
    with rasterio.open(
        output_file,
        "w",
        driver="GTiff",
        height=num_rows,
        width=num_cols,
        count=1,   # if write all stack data, use num_band
        dtype=np.float32,
        transform=transform,
        crs=crs_str
    ) as dst:
        dst.write(stack_data)
        band_names = ["sigma0_dB"]
        for idx, name in enumerate(band_names, start=1):
            dst.set_band_description(idx, name)
        dst.update_tags(**meta_tags)

    # print(f"SAVE : {output_file} (EPSG:{epsg_code}, rg_spacing={rg_spacing:.2f}m, az_spacing={az_spacing:.2f}m)")

#---------------------------------------------------------------------------
# DESCRIPTION:
#> @brief
#> 
#
#> @param[in] N/A
#> @param[out] N/A
#> @return N/A
#---------------------------------------------------------------------------
def plot_sigma0(sigma0_db, ofile_path, output_prefix):
    vmin, vmax = np.percentile(sigma0_db, [5, 95])

    # 2D image Visualization
    plt.figure(figsize=(12, 10))
    im = plt.imshow(sigma0_db, cmap='gray', vmin=vmin, vmax=vmax, aspect='equal')
    plt.colorbar(im, label='Sigma Nought (dB)', pad=0.02)
    plt.title(f'2D Visualization of Sigma Nought (dB)\nMin: {vmin:.2f} dB, Max: {vmax:.2f} dB', fontsize=16, pad=15)
    plt.xlabel('Column Index', fontsize=14)
    plt.ylabel('Row Index', fontsize=14)
    plt.tight_layout()
    output_file = ofile_path + f'{output_prefix}.png'
    plt.savefig(output_file, dpi=300)
    plt.close()

    # histogram Visualization
    plt.figure(figsize=(10, 8))
    plt.hist(sigma0_db.ravel(), bins=100, density=True, color='blue', alpha=0.7)
    plt.title('Histogram of Sigma Nought (dB)', fontsize=16, pad=15)
    plt.xlabel('Sigma Nought (dB)', fontsize=14)
    plt.ylabel('Density', fontsize=14)
    plt.grid(True)
    plt.tight_layout()
    output_file = ofile_path + f'{output_prefix}_histogram.png'
    plt.savefig(output_file, dpi=300)
    plt.close()
