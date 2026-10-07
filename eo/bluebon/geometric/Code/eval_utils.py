
import os
import numpy as np
import rasterio
from rasterio.windows import Window
from scipy import ndimage
from scipy.stats import linregress
import matplotlib
matplotlib.use('Agg')  # GUI 없이 사용 (백그라운드 스레드 호환)
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
import subprocess
import sys

# ============================================================
# Evaluation Functions 
# ============================================================

def load_geotiff_eval(path: str) -> tuple:
    """GeoTIFF 로드 및 geo-transform 정보 반환"""
    with rasterio.open(path) as src:
        try:
            bands = [src.read(b) for b in [3, 4, 5]]
            data = np.nanmean(np.stack(bands), axis=0)
        except:
            data = src.read(1)
        return data, src.profile

def estimate_strip_direction(valid_mask: np.ndarray) -> tuple:
    """유효 픽셀 분포에서 PCA를 이용해 스트립 방향 추정"""
    rows, cols = np.where(valid_mask)
    if len(rows) < 100:
        return 0.0, np.array([0, 1]), np.array([1, 0])
    
    center_col = np.mean(cols)
    center_row = np.mean(rows)
    coords = np.vstack([cols - center_col, rows - center_row])
    
    cov = np.cov(coords)
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    
    idx = np.argmax(eigenvalues)
    along_axis = eigenvectors[:, idx]
    
    if along_axis[1] < 0:
        along_axis = -along_axis
    
    across_axis = np.array([-along_axis[1], along_axis[0]])
    angle = np.arctan2(along_axis[1], along_axis[0])
    
    return angle, along_axis, across_axis

def generate_grid_points(height: int, width: int, valid_mask: np.ndarray,
                         grid_spacing: int = 100, patch_size: int = 64,
                         along_axis: np.ndarray = None, across_axis: np.ndarray = None) -> list:
    """Grid 기반 측정점 생성 (스트립 방향)"""
    half = patch_size // 2
    points = []
    
    if along_axis is None:
        return []

    center_row, center_col = height / 2, width / 2
    diagonal = np.sqrt(height**2 + width**2)
    
    n_along = int(diagonal / grid_spacing) + 1
    n_across = int(diagonal / grid_spacing) + 1
    
    # Offset to avoid 0,0 alignment (optional, but keep simple for now or strictly follow user)
    # compare_mosaics.py doesn't use explicit offset, but uses center-relative grid.
    
    for i_along in range(-n_along, n_along + 1):
        for i_across in range(-n_across, n_across + 1):
            pos_along = i_along * grid_spacing
            pos_across = i_across * grid_spacing
            
            col = center_col + pos_along * along_axis[0] + pos_across * across_axis[0]
            row = center_row + pos_along * along_axis[1] + pos_across * across_axis[1]
            
            r = int(round(row))
            c = int(round(col))
            
            if half <= r < height - half and half <= c < width - half:
                patch_mask = valid_mask[r-half:r+half, c-half:c+half]
                # Lower threshold to 0.5 to capture more valid areas (User feedback on empty spaces)
                if patch_mask.size > 0 and np.mean(patch_mask) > 0.5:
                    points.append((r, c))
                    
    return list(set(points))

def phase_correlation(patch1: np.ndarray, patch2: np.ndarray, search_range: int = 5) -> tuple:
    h, w = patch1.shape
    window = np.outer(np.hanning(h), np.hanning(w))
    p1 = patch1 * window
    p2 = patch2 * window
    
    f1 = np.fft.fft2(p1)
    f2 = np.fft.fft2(p2)
    cross_power = f1 * np.conj(f2)
    cross_power /= (np.abs(cross_power) + 1e-10)
    correlation = np.abs(np.fft.fftshift(np.fft.ifft2(cross_power)))
    
    cy, cx = h // 2, w // 2
    y_slice = slice(max(0, cy - search_range), min(h, cy + search_range + 1))
    x_slice = slice(max(0, cx - search_range), min(w, cx + search_range + 1))
    
    search_region = correlation[y_slice, x_slice]
    py, px = np.unravel_index(np.argmax(search_region), search_region.shape)
    
    peak_y = py + y_slice.start
    peak_x = px + x_slice.start
    peak_val = correlation[peak_y, peak_x]
    
    dy_sub, dx_sub = 0.0, 0.0
    # Quad fit
    try:
        if 0 < py < search_region.shape[0]-1 and 0 < px < search_region.shape[1]-1:
            y0, y1, y2 = search_region[py-1, px], search_region[py, px], search_region[py+1, px]
            if y0 + y2 - 2*y1 != 0: dy_sub = 0.5 * (y0 - y2) / (y0 + y2 - 2*y1)
            
            x0, x1, x2 = search_region[py, px-1], search_region[py, px], search_region[py, px+1]
            if x0 + x2 - 2*x1 != 0: dx_sub = 0.5 * (x0 - x2) / (x0 + x2 - 2*x1)
    except: pass

    return (peak_x - cx) + dx_sub, (peak_y - cy) + dy_sub, peak_val

def plot_residual_map(cols, rows, magnitudes, height, width, output_path, vmax=10.0):
    fig, ax = plt.subplots(figsize=(12, 10))
    scatter = ax.scatter(cols, rows, c=magnitudes, cmap='jet', 
                         s=20, alpha=0.8, norm=Normalize(vmin=0, vmax=vmax))
    plt.colorbar(scatter, ax=ax, label='Displacement Magnitude (Ref. pixels)')
    
    ax.set_xlim(0, width)
    ax.set_ylim(height, 0)
    ax.set_title('Residual Map (Magnitude in Ref. Resolution)')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()

def plot_rmse_points(cols, rows, image_data, output_path):
    plt.figure(figsize=(12, 10))
    
    # Background
    if image_data.ndim == 2: bg = image_data
    else: bg = np.mean(image_data, axis=0)
    
    vmin, vmax = np.percentile(bg[bg>0], [2, 98]) if np.any(bg>0) else (0, 255)
    plt.imshow(bg, cmap='gray', vmin=vmin, vmax=vmax, alpha=0.6)
    
    plt.scatter(cols, rows, c='lime', s=5, alpha=0.7, label='RMSE Points')
    plt.legend()
    plt.title('Points used for RMSE Calculation')
    plt.savefig(output_path)
    plt.close()

def evaluate_mosaic_vs_reference(mosaic_path: str, reference_path: str, output_dir: str, 
                              gdalwarp_cmd: str = 'gdalwarp', boundaries: list = [],
                              row_range: tuple = None, search_range: int = 20, rmse_threshold: float = 0.5,
                              exclude_tiff: str = None) -> dict:
    print(f"\n[Evaluation] Mosaic vs Reference (Strip-Aligned Grid)")
    os.makedirs(output_dir, exist_ok=True)
    
    # 1. Resample Reference to Mosaic extent (메모리에서 처리, 파일 저장 안 함)
    with rasterio.open(mosaic_path) as src:
        bounds = src.bounds
        w, h = src.width, src.height
        profile = src.profile.copy()
        mosaic_res = abs(src.transform.a)
        
    with rasterio.open(reference_path) as ref:
        ref_res = abs(ref.transform.a)
        
    resolution_ratio = mosaic_res / ref_res
    
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.tiff', delete=False) as tmp:
        tmp_path = tmp.name
    
    try:
        subprocess.run([gdalwarp_cmd, '-t_srs', 'EPSG:4326',
                        '-te', str(bounds.left), str(bounds.bottom), str(bounds.right), str(bounds.top),
                        '-ts', str(w), str(h), '-r', 'bilinear', '-overwrite',
                        reference_path, tmp_path], capture_output=True, check=True)
        
        # 2. Load
        data_mosaic, _ = load_geotiff_eval(mosaic_path)
        data_ref, _ = load_geotiff_eval(tmp_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    
    # 3. Mask & Direction
    mask = (data_mosaic > 0) & (data_ref > 0)
    angle, along, across = estimate_strip_direction(mask)
    
    # 4. Generate Grid (Strip Aligned)
    points = generate_grid_points(h, w, mask, grid_spacing=100, patch_size=64, 
                                  along_axis=along, across_axis=across)
    
    # Filter by row_range if provided (User Request: Evaluate specific region only)
    if row_range:
        min_r, max_r = row_range
        original_count = len(points)
        points = [p for p in points if min_r <= p[0] < max_r]
        print(f"      Points in ROI ({min_r}~{max_r}): {len(points)} (Total: {original_count})")
        
    # Check exclude_tiff if provided
    exc_mask = None
    if exclude_tiff and os.path.exists(exclude_tiff):
        with tempfile.NamedTemporaryFile(suffix='.tiff', delete=False) as tmp_exc:
            tmp_exc_path = tmp_exc.name
        try:
            subprocess.run([gdalwarp_cmd, '-t_srs', 'EPSG:4326',
                            '-te', str(bounds.left), str(bounds.bottom), str(bounds.right), str(bounds.top),
                            '-ts', str(w), str(h), '-r', 'near', '-overwrite',
                            exclude_tiff, tmp_exc_path], capture_output=True, check=True)
            data_exc, _ = load_geotiff_eval(tmp_exc_path)
            exc_mask = data_exc > 0
        finally:
            if os.path.exists(tmp_exc_path):
                os.remove(tmp_exc_path)
    
    print(f"      Valid Points: {len(points)}")
    
    dxs, dys, r_list, c_list, val_list = [], [], [], [], []
    patch = 64
    half = patch // 2
    
    for r, c in points:
        p1 = data_ref[r-half:r+half, c-half:c+half]
        p2 = data_mosaic[r-half:r+half, c-half:c+half]
        
        p1 = (p1 - np.mean(p1)) / (np.std(p1) + 1e-10)
        p2 = (p2 - np.mean(p2)) / (np.std(p2) + 1e-10)
        
        dx, dy, val = phase_correlation(p1, p2, search_range=search_range)
        
        # 시각화용: 임계값 없이 모두 저장 (0보다 크면)
        if val > 0: 
            dxs.append(dx)
            dys.append(dy)
            r_list.append(r)
            c_list.append(c)
            val_list.append(val)
            
    if not dxs:
        return {}
        
    # Scale displacements to Reference image resolution (Sentinel-2)
    dxs = np.array(dxs) * resolution_ratio
    dys = np.array(dys) * resolution_ratio
    vals = np.array(val_list)
    mag = np.sqrt(dxs**2 + dys**2)
    
    # 시각화: 모든 포인트 사용
    plot_residual_map(c_list, r_list, mag, h, w, os.path.join(output_dir, "residual_map.png"))
    plot_rmse_points(c_list, r_list, data_mosaic, os.path.join(output_dir, "rmse_points.png"))
    
    # Validation Metrics (All Points)
    valid_mask = vals >= rmse_threshold
    valid_dx = dxs[valid_mask]
    valid_dy = dys[valid_mask]
    
    metrics = {'count': len(dxs), 'valid_count': 0, 'rmse': 0.0}
    
    if len(valid_dx) > 0:
        rmse = np.sqrt(np.mean(valid_dx**2 + valid_dy**2))
        print(f"      Valid Points (All): {len(dxs)}")
        print(f"      High Conf Points (RMSE): {len(valid_dx)} (Threshold: {rmse_threshold})")
        print(f"      RMSE (All): {rmse:.4f} pixels")
        metrics['valid_count'] = len(valid_dx)
        metrics['rmse'] = rmse
    else:
        print(f"      No high confidence points found.")
        
    # Extrapolated Area Metric
    if exc_mask is not None:
        r_np = np.array(r_list)
        c_np = np.array(c_list)
        extrap_mask = ~exc_mask[r_np, c_np]
        
        # Of those extrapolated, which are valid?
        extrap_valid = extrap_mask & valid_mask
        extrap_dx = dxs[extrap_valid]
        extrap_dy = dys[extrap_valid]
        
        if len(extrap_dx) > 0:
            extrap_rmse = np.sqrt(np.mean(extrap_dx**2 + extrap_dy**2))
            print(f"      High Conf Points (Extrapolated): {len(extrap_dx)}")
            print(f"      RMSE (Extrapolated Only): {extrap_rmse:.4f} pixels")
            metrics['valid_count_extrapolated'] = len(extrap_dx)
            metrics['rmse_extrapolated'] = extrap_rmse
        else:
            print(f"      No extrapolated points found.")
            metrics['valid_count_extrapolated'] = 0
            metrics['rmse_extrapolated'] = 0.0
            
    return metrics

def visualize_gcp_distribution(overlap_gcps: list, pseudo_gcps: list, 
                               width: int, height: int, output_path: str,
                               bg_image_path: str = None, bg_offset: int = 0):
    plt.figure(figsize=(10, 12))
    
    if bg_image_path and os.path.exists(bg_image_path):
        try:
            with rasterio.open(bg_image_path) as src:
                try: band = 2 if src.count >= 2 else 1
                except: band = 1
                data = src.read(band, window=Window(0, bg_offset, width, height))
                valid = data[data > 0]
                vmin, vmax = np.percentile(valid, [2, 98]) if valid.size else (0, 255)
                plt.imshow(data, cmap='gray', vmin=vmin, vmax=vmax, alpha=0.5, extent=[0, width, height, 0])
        except: plt.xlim(0, width); plt.ylim(height, 0)
    else:
        plt.xlim(0, width); plt.ylim(height, 0); plt.gca().invert_yaxis()
    
    px = [g[1] for g in pseudo_gcps]
    py = [g[0] for g in pseudo_gcps]
    plt.scatter(px, py, c='red', s=10, alpha=0.5, label='Pseudo GCPs')
    
    ox = [g['samp'] for g in overlap_gcps]
    oy = [g['line'] for g in overlap_gcps]
    plt.scatter(ox, oy, c='blue', s=30, marker='^', label='Overlap GCPs')
    
    plt.title(f'GCP Distribution (Total: {len(overlap_gcps) + len(pseudo_gcps)})')
    plt.legend()
    plt.savefig(output_path)
    plt.close()
