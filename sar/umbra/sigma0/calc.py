
import numpy as np


def calculate_sigma0(slc_data, meta_data, under_flow_flt=1e-20):
    real      = np.real(slc_data).astype(np.float32)
    imag      = np.imag(slc_data).astype(np.float32)
    intensity = (np.abs(slc_data) ** 2).astype(np.float32)
    phase     = np.angle(slc_data).astype(np.float32)
    
    num_rows       = meta_data.ImageData.NumRows
    num_cols       = meta_data.ImageData.NumCols
    scp_row        = meta_data.ImageData.SCPPixel.Row
    scp_col        = meta_data.ImageData.SCPPixel.Col
    noise_poly_db  = meta_data.Radiometric.NoiseLevel.NoisePoly[0, 0]
    sigma0_sf_poly = meta_data.Radiometric.SigmaZeroSFPoly.Coefs
    
    # Calculate noise power (linear scale)
    noise_power = 10 ** (noise_poly_db / 10)

    # Remove noise
    intensity_corrected = np.maximum(intensity - noise_power, 0)
    
    # Creating a normalized coordinate (r, a)
    rows, cols = np.indices((num_rows, num_cols))
    r = (rows - scp_row) / (num_rows / 2)
    a = (cols - scp_col) / (num_cols / 2)

    # Calculate SigmaZero Scale Factor (K)
    K = np.zeros((num_rows, num_cols), dtype=np.float64)
    for i in range(sigma0_sf_poly.shape[0]):
        for j in range(sigma0_sf_poly.shape[1]):
            K += sigma0_sf_poly[i, j] * (r ** i) * (a ** j)

    # Calculate Sigma Nought
    sigma0 = intensity_corrected * K

    # Convert dB scale
    sigma0_db = 10 * np.log10(np.clip(sigma0, under_flow_flt, None))
    
    stack_data = np.stack([sigma0, sigma0_db], axis=0)

    return stack_data

#---------------------------------------------------------------------------
# DESCRIPTION:
#> @brief
#> 
#
#> @param[in] N/A
#> @param[out] N/A
#> @return N/A
#---------------------------------------------------------------------------
def get_utm_epsg(lon, lat):
    zone = int((lon + 180) / 6) + 1
    epsg = 32600 + zone if lat >= 0 else 32700 + zone
    return zone, epsg