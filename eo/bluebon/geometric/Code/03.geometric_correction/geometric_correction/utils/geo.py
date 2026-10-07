"""
지리공간 유틸리티 모듈

좌표 변환, CRS 처리 등 지리공간 관련 유틸리티 함수들을 제공합니다.
"""

import numpy as np
from pyproj import Transformer, CRS
from typing import Tuple, Optional
from rasterio.transform import Affine


def sample_bilinear(data: np.ndarray, transform: Affine, geo_x: float, geo_y: float,
                    nodata=None) -> Optional[float]:
    """
    이중선형 보간(bilinear interpolation)으로 래스터에서 값을 추출합니다.

    nodata 또는 NaN 픽셀은 0.0으로 대체한 뒤 표준 보간에 포함합니다.

    Args:
        data:      2D 래스터 배열 (shape: [nrows, ncols])
        transform: rasterio Affine transform
        geo_x:     지리 X 좌표 (경도 또는 투영 X)
        geo_y:     지리 Y 좌표 (위도 또는 투영 Y)
        nodata:    래스터 nodata 값 (None이면 NaN만 검사)

    Returns:
        보간된 float 값.
        래스터 범위 완전 이탈 시 None.
    """
    nrows, ncols = data.shape

    # rasterio Affine: 픽셀 모서리(0,0) 기준 → 픽셀 중심 기준으로 -0.5 보정
    col_f = (geo_x - transform.c) / transform.a - 0.5
    row_f = (geo_y - transform.f) / transform.e - 0.5

    # 래스터 범위 완전 이탈 체크 (반 픽셀 여유)
    if col_f < -0.5 or col_f >= ncols - 0.5 or row_f < -0.5 or row_f >= nrows - 0.5:
        return None

    # 4개 이웃 픽셀 인덱스
    col0 = int(np.floor(col_f))
    row0 = int(np.floor(row_f))
    col1 = col0 + 1
    row1 = row0 + 1

    # 경계 클램핑 (배열 인덱스 안전)
    col0_c = max(0, min(ncols - 1, col0))
    col1_c = max(0, min(ncols - 1, col1))
    row0_c = max(0, min(nrows - 1, row0))
    row1_c = max(0, min(nrows - 1, row1))

    # 이중선형 가중치
    dc = col_f - col0   # 0 ~ 1
    dr = row_f - row0   # 0 ~ 1

    def _to_valid(v: float) -> float:
        """nodata 또는 NaN이면 0.0으로 대체 (바다/빈 영역 처리)"""
        if np.isnan(v):
            return 0.0
        if nodata is not None and v == nodata:
            return 0.0
        return v

    v00 = _to_valid(float(data[row0_c, col0_c]))
    v01 = _to_valid(float(data[row0_c, col1_c]))
    v10 = _to_valid(float(data[row1_c, col0_c]))
    v11 = _to_valid(float(data[row1_c, col1_c]))

    # 표준 이중선형 보간 (nodata는 0으로 포함)
    return ((1 - dc) * (1 - dr) * v00
            + dc       * (1 - dr) * v01
            + (1 - dc) * dr       * v10
            + dc       * dr       * v11)

from ..exceptions import (
    CRSError,
    CRSMismatchError,
    CRSTransformError
)


def create_transformer(
    src_crs: any, 
    dst_crs: any, 
    always_xy: bool = True
) -> Transformer:
    """
    좌표 변환기를 생성합니다.
    
    Args:
        src_crs: 소스 CRS
        dst_crs: 대상 CRS
        always_xy: True면 (x, y) 순서, False면 (lat, lon) 순서
        
    Returns:
        Transformer 객체
        
    Raises:
        CRSTransformError: 변환기 생성 실패 시
    """
    try:
        return Transformer.from_crs(src_crs, dst_crs, always_xy=always_xy)
    except Exception as e:
        raise CRSTransformError(f"좌표 변환기 생성 실패: {e}") from e


def pixel_to_geo(
    pixel_x: float, 
    pixel_y: float, 
    transform: Affine
) -> Tuple[float, float]:
    """
    픽셀 좌표를 지리 좌표로 변환합니다.
    
    Args:
        pixel_x: 픽셀 X 좌표
        pixel_y: 픽셀 Y 좌표
        transform: Affine 변환 행렬
        
    Returns:
        tuple: (geo_x, geo_y)
    """
    geo_x, geo_y = transform * (pixel_x, pixel_y)
    return geo_x, geo_y


def geo_to_pixel(
    geo_x: float, 
    geo_y: float, 
    transform: Affine
) -> Tuple[float, float]:
    """
    지리 좌표를 픽셀 좌표로 변환합니다.
    
    Args:
        geo_x: 지리 X 좌표
        geo_y: 지리 Y 좌표
        transform: Affine 변환 행렬
        
    Returns:
        tuple: (pixel_x, pixel_y)
    """
    inv_transform = ~transform
    pixel_x, pixel_y = inv_transform * (geo_x, geo_y)
    return pixel_x, pixel_y


def transform_coordinates(
    x: np.ndarray, 
    y: np.ndarray, 
    src_crs: any, 
    dst_crs: any
) -> Tuple[np.ndarray, np.ndarray]:
    """
    좌표 배열을 변환합니다.
    
    Args:
        x: X 좌표 배열
        y: Y 좌표 배열
        src_crs: 소스 CRS
        dst_crs: 대상 CRS
        
    Returns:
        tuple: (변환된 x, 변환된 y)
        
    Raises:
        CRSTransformError: 좌표 변환 실패 시
    """
    try:
        transformer = create_transformer(src_crs, dst_crs)
        return transformer.transform(x, y)
    except Exception as e:
        raise CRSTransformError(f"좌표 변환 실패: {e}") from e


def calculate_utm_zone(lon: float) -> int:
    """
    경도로부터 UTM 존 번호를 계산합니다.
    
    Args:
        lon: 경도
        
    Returns:
        UTM 존 번호 (1-60)
    """
    return int((lon + 180) / 6) + 1


def create_utm_crs(lon: float, lat: float) -> CRS:
    """
    경위도로부터 적절한 UTM CRS를 생성합니다.
    
    Args:
        lon: 경도
        lat: 위도
        
    Returns:
        CRS 객체
    """
    zone = calculate_utm_zone(lon)
    hemisphere = 'north' if lat >= 0 else 'south'
    epsg_code = 32600 + zone if hemisphere == 'north' else 32700 + zone
    return CRS.from_epsg(epsg_code)


def calculate_resolution(transform: Affine) -> Tuple[float, float]:
    """
    Affine 변환에서 해상도를 계산합니다.
    
    Args:
        transform: Affine 변환 행렬
        
    Returns:
        tuple: (x_resolution, y_resolution)
    """
    x_res = abs(transform.a)
    y_res = abs(transform.e)
    return x_res, y_res


def calculate_bounds(
    width: int, 
    height: int, 
    transform: Affine
) -> Tuple[float, float, float, float]:
    """
    영상의 경계(bounds)를 계산합니다.
    
    Args:
        width: 영상 너비
        height: 영상 높이
        transform: Affine 변환 행렬
        
    Returns:
        tuple: (left, bottom, right, top)
    """
    left, top = transform * (0, 0)
    right, bottom = transform * (width, height)
    return left, bottom, right, top


def check_crs_match(crs1: any, crs2: any, raise_error: bool = False) -> bool:
    """
    두 CRS가 동일한지 확인합니다.
    
    Args:
        crs1: 첫 번째 CRS
        crs2: 두 번째 CRS
        raise_error: True면 불일치 시 예외 발생
        
    Returns:
        bool: 동일하면 True
        
    Raises:
        CRSMismatchError: raise_error=True이고 불일치 시
    """
    match = crs1 == crs2
    
    if not match and raise_error:
        raise CRSMismatchError(f"CRS가 일치하지 않습니다: {crs1} != {crs2}")
    
    return match


def estimate_center_latlon(
    width: int, 
    height: int, 
    transform: Affine, 
    crs: any
) -> Tuple[float, float]:
    """
    영상 중심의 위경도를 추정합니다.
    
    Args:
        width: 영상 너비
        height: 영상 높이
        transform: Affine 변환 행렬
        crs: 영상의 CRS
        
    Returns:
        tuple: (latitude, longitude)
        
    Raises:
        CRSTransformError: 좌표 변환 실패 시
    """
    # 픽셀 중심 좌표
    center_x = width / 2
    center_y = height / 2
    
    # 지리 좌표로 변환
    geo_x, geo_y = pixel_to_geo(center_x, center_y, transform)
    
    # WGS84(EPSG:4326)로 변환
    wgs84 = CRS.from_epsg(4326)
    if crs != wgs84:
        transformer = create_transformer(crs, wgs84)
        lon, lat = transformer.transform(geo_x, geo_y)
    else:
        lon, lat = geo_x, geo_y
    
    return lat, lon


def create_affine_from_bounds(
    bounds: Tuple[float, float, float, float],
    width: int,
    height: int
) -> Affine:
    """
    경계와 크기로부터 Affine 변환을 생성합니다.
    
    Args:
        bounds: (left, bottom, right, top)
        width: 영상 너비
        height: 영상 높이
        
    Returns:
        Affine 변환 행렬
    """
    left, bottom, right, top = bounds
    x_res = (right - left) / width
    y_res = (top - bottom) / height
    
    return Affine.translation(left, top) * Affine.scale(x_res, -y_res)


def reproject_bounds(
    bounds: Tuple[float, float, float, float],
    src_crs: any,
    dst_crs: any
) -> Tuple[float, float, float, float]:
    """
    경계를 다른 CRS로 재투영합니다.
    
    Args:
        bounds: (left, bottom, right, top)
        src_crs: 소스 CRS
        dst_crs: 대상 CRS
        
    Returns:
        tuple: 재투영된 (left, bottom, right, top)
        
    Raises:
        CRSTransformError: 좌표 변환 실패 시
    """
    left, bottom, right, top = bounds
    
    try:
        transformer = create_transformer(src_crs, dst_crs)
        
        # 4개 코너 변환
        x_coords = [left, right, right, left]
        y_coords = [top, top, bottom, bottom]
        
        x_transformed, y_transformed = transformer.transform(x_coords, y_coords)
        
        # 새 경계 계산
        new_left = min(x_transformed)
        new_right = max(x_transformed)
        new_bottom = min(y_transformed)
        new_top = max(y_transformed)
        
        return new_left, new_bottom, new_right, new_top
        
    except Exception as e:
        raise CRSTransformError(f"경계 재투영 실패: {e}") from e

