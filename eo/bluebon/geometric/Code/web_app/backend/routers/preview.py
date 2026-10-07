import io
import os
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

router = APIRouter(prefix="/api/preview", tags=["preview"])


def _tiff_to_rgb_png(tiff_path: str, max_size: int = 800, transparent_zero: bool = False) -> bytes:
    import rasterio
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    from pipeline_config import get_rgb_band_indices
    from PIL import Image

    with rasterio.open(tiff_path) as src:
        band_count = src.count
        rgb_indices = get_rgb_band_indices(band_count)
        rgb_indices = [i for i in rgb_indices if i <= band_count]
        if not rgb_indices:
            rgb_indices = [1]
        bands = [src.read(i).astype(float) for i in rgb_indices]

    def stretch(arr):
        valid = arr[arr > 0]
        if valid.size == 0:
            return np.zeros_like(arr, dtype=np.uint8)
        p2, p98 = np.percentile(valid, [2, 98])
        if p98 > p2:
            out = (arr - p2) / (p98 - p2) * 255.0
        else:
            out = arr.copy()
        return np.clip(out, 0, 255).astype(np.uint8)

    rgb = np.stack([stretch(b) for b in bands], axis=-1)
    if rgb.shape[2] == 1:
        rgb = np.repeat(rgb, 3, axis=2)
    elif rgb.shape[2] == 2:
        rgb = np.concatenate([rgb, rgb[:, :, :1]], axis=2)

    h, w = rgb.shape[:2]
    scale = min(max_size / w, max_size / h, 1.0)
    new_w, new_h = max(1, int(w * scale)), max(1, int(h * scale))

    if transparent_zero:
        # 모든 밴드가 0인 픽셀 → alpha=0 (투명)
        zero_mask = np.all(np.stack([b == 0 for b in bands], axis=-1), axis=-1)
        alpha = np.where(zero_mask, 0, 255).astype(np.uint8)
        rgba = np.dstack([rgb, alpha])
        img = Image.fromarray(rgba, mode="RGBA").resize((new_w, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
    else:
        img = Image.fromarray(rgb, mode="RGB").resize((new_w, new_h), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)

    return buf.getvalue()


@router.get("/tiff")
def preview_tiff(
    path: str = Query(..., description="절대 경로"),
    max_size: int = Query(800, ge=100, le=4096),
    transparent: int = Query(0),
):
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"파일 없음: {path}")
    try:
        png_bytes = _tiff_to_rgb_png(path, max_size, transparent_zero=bool(transparent))
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tiff-bounds")
def tiff_bounds_by_path(path: str = Query(...)):
    """임의 TIFF 경로의 지리 경계를 WGS84로 반환."""
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"파일 없음: {path}")
    try:
        west, south, east, north = _get_wgs84_bounds(path)
        return {
            "bounds": [[south, west], [north, east]],
            "center": [(south + north) / 2, (west + east) / 2],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _get_wgs84_bounds(tiff_path: str):
    """TIFF의 WGS84 경계 반환. PROJ db 버전 충돌 방지를 위해 proj4 문자열 사용."""
    import rasterio
    from rasterio.crs import CRS
    from rasterio.warp import transform_bounds
    wgs84 = CRS.from_proj4('+proj=longlat +datum=WGS84 +no_defs')
    with rasterio.open(tiff_path) as src:
        if src.crs is None:
            raise ValueError(f"CRS 정보 없음: {tiff_path}")
        west, south, east, north = transform_bounds(src.crs, wgs84, *src.bounds)
    return west, south, east, north


@router.get("/bounds/{row_idx}")
def get_bounds(row_idx: int):
    """처리된 TIFF의 지리 경계를 WGS84로 반환 (Leaflet ImageOverlay용)."""
    import glob
    from state import state

    row = next((r for r in state.rows if r["row"] == row_idx), None)
    if not row or not row.get("result_dir"):
        raise HTTPException(status_code=404, detail="결과 없음")

    candidates = (
        glob.glob(os.path.join(row["result_dir"], "bb_l1c_*.tiff")) +
        glob.glob(os.path.join(row["result_dir"], "bb_l1c_*.tif"))
    )
    if not candidates:
        raise HTTPException(status_code=404, detail="TIFF 없음")

    try:
        west, south, east, north = _get_wgs84_bounds(candidates[0])
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {
        "bounds": [[south, west], [north, east]],
        "center": [(south + north) / 2, (west + east) / 2],
        "tiff_path": candidates[0],
    }


def _find_sentinel_tif(result_dir: str) -> str | None:
    """result_dir 하위의 Sentinel-2 모자이크 TIFF 경로를 반환."""
    import glob
    for section in ("Center", "Top", "Bottom"):
        pattern = os.path.join(result_dir, section, "01_Download_open_data", "S2_mosaic_*.tif")
        found = glob.glob(pattern)
        if found:
            return found[0]
    return None


@router.get("/sentinel-bounds/{row_idx}")
def get_sentinel_bounds(row_idx: int):
    """해당 행 처리에 사용된 Sentinel-2 모자이크의 WGS84 경계 반환."""
    from state import state
    row = next((r for r in state.rows if r["row"] == row_idx), None)
    if not row or not row.get("result_dir"):
        raise HTTPException(status_code=404, detail="결과 없음")
    s2_path = _find_sentinel_tif(row["result_dir"])
    if not s2_path:
        raise HTTPException(status_code=404, detail="Sentinel-2 파일 없음")
    try:
        west, south, east, north = _get_wgs84_bounds(s2_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {
        "bounds": [[south, west], [north, east]],
        "center": [(south + north) / 2, (west + east) / 2],
        "tiff_path": s2_path,
    }


@router.get("/sentinel-base/{row_idx}")
def sentinel_base(
    row_idx: int,
    max_size: int = Query(2000, ge=100, le=4096),
):
    """처리에 사용된 Sentinel-2 모자이크를 8bit RGB PNG로 반환."""
    from state import state
    row = next((r for r in state.rows if r["row"] == row_idx), None)
    if not row or not row.get("result_dir"):
        raise HTTPException(status_code=404, detail="결과 없음")
    s2_path = _find_sentinel_tif(row["result_dir"])
    if not s2_path:
        raise HTTPException(status_code=404, detail="Sentinel-2 파일 없음")
    try:
        png_bytes = _tiff_to_rgb_png(s2_path, max_size, transparent_zero=False)
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/result/{row_idx}")
def preview_result(
    row_idx: int,
    max_size: int = Query(800),
    transparent: int = Query(0),
):
    from state import state
    import glob

    for row in state.rows:
        if row["row"] == row_idx and row.get("result_dir"):
            result_dir = row["result_dir"]
            candidates = (
                glob.glob(os.path.join(result_dir, "bb_l1c_*.tiff")) +
                glob.glob(os.path.join(result_dir, "bb_l1c_*.tif"))
            )
            if candidates:
                try:
                    png_bytes = _tiff_to_rgb_png(candidates[0], max_size, transparent_zero=bool(transparent))
                    return Response(content=png_bytes, media_type="image/png")
                except Exception as e:
                    raise HTTPException(status_code=500, detail=str(e))
            raise HTTPException(status_code=404, detail="결과 TIFF 없음")

    raise HTTPException(status_code=404, detail="결과 없음")
