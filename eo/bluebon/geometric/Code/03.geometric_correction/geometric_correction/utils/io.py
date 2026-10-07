"""
입출력 유틸리티 모듈

파일 입출력 관련 유틸리티 함수들을 제공합니다.
"""

import os
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.control import GroundControlPoint
from typing import Tuple, List, Optional
from pathlib import Path

from ..exceptions import (
    ImageLoadError,
    FileNotFoundError as CustomFileNotFoundError,
    FileValidationError
)


def load_image_for_matching(
    path: str, 
    resolution_divisor: int = 1
) -> Tuple[np.ndarray, any, int, int]:
    """
    이미지를 로드하고 필요시 다운샘플링합니다 (첫 번째 밴드만 사용)
    
    Args:
        path: 이미지 경로
        resolution_divisor: 해상도 축소 비율 (1=원본, 2=1/2, 4=1/4, ...)
        
    Returns:
        tuple: (이미지 배열, transform, width, height)
        
    Raises:
        CustomFileNotFoundError: 파일이 존재하지 않을 경우
        ImageLoadError: 이미지 로딩 실패 시
    """
    if not os.path.exists(path):
        raise CustomFileNotFoundError(f"파일이 존재하지 않습니다: {path}")
    
    try:
        with rasterio.open(path) as src:
            if src.count < 1:
                raise ImageLoadError(f"밴드가 없습니다: {path}")
            
            if resolution_divisor > 1:
                new_width = src.width // resolution_divisor
                new_height = src.height // resolution_divisor
                
                # 첫 번째 밴드만 읽기
                img = src.read(
                    1,
                    out_shape=(new_height, new_width),
                    resampling=Resampling.bilinear
                )
            else:
                # 첫 번째 밴드만 읽기
                img = src.read(1)
            
            return img, src.transform, src.width, src.height
            
    except rasterio.errors.RasterioError as e:
        raise ImageLoadError(f"이미지 로딩 실패: {path}") from e


def load_image_gdal(
    path: str, 
    resize: Optional[Tuple[int, int]] = None,
    reverse_bands: bool = False,
    target_bands: Optional[List[int]] = None
) -> np.ndarray:
    """
    GDAL을 사용하여 이미지를 로드합니다.
    
    Args:
        path: 이미지 경로
        resize: 리사이즈 크기 (width, height), None이면 원본 크기
        reverse_bands: True이면 밴드 순서를 반대로 (3,2,1) (Reference 이미지용)
        target_bands: Target 이미지의 RGB 밴드 인덱스 (예: [6,4,2] for PlanetScope)
                     None이면 기본 순서 (1,2,3) 사용
        
    Returns:
        이미지 배열 (H, W) or (H, W, C)
        
    Raises:
        CustomFileNotFoundError: 파일이 존재하지 않을 경우
        ImageLoadError: 이미지 로딩 실패 시
    """
    if not os.path.exists(path):
        raise CustomFileNotFoundError(f"파일이 존재하지 않습니다: {path}")
    
    try:
        from osgeo import gdal
        
        # GDAL 경고 제거
        try:
            gdal.UseExceptions()
        except:
            pass
        
        ds = gdal.Open(path, gdal.GA_ReadOnly)
        if ds is None:
            raise ImageLoadError(f"GDAL로 파일을 열 수 없습니다: {path}")
        
        # 밴드 수
        num_bands = ds.RasterCount
        
        if num_bands == 1:
            # Grayscale
            band = ds.GetRasterBand(1)
            img = band.ReadAsArray()
        else:
            # Multi-band
            if target_bands is not None and len(target_bands) >= 3:
                # Target 이미지: 특정 밴드 사용 (예: PlanetScope의 경우 [6,4,2] -> R,G,B)
                # RGB로 3개 밴드만 읽기
                img = np.zeros((ds.RasterYSize, ds.RasterXSize, 3), dtype=np.float32)
                rgb_bands = target_bands[:3]  # R, G, B 순서
                for i, band_idx in enumerate(rgb_bands):
                    if band_idx > num_bands:
                        raise ImageLoadError(f"밴드 인덱스 {band_idx}가 이미지 밴드 수 ({num_bands})를 초과합니다: {path}")
                    band = ds.GetRasterBand(band_idx)  # GDAL은 1-based
                    img[:, :, i] = band.ReadAsArray()
            else:
                # 기본 동작: 모든 밴드 읽기
                img = np.zeros((ds.RasterYSize, ds.RasterXSize, num_bands), dtype=np.float32)
                if reverse_bands and num_bands >= 3:
                    # Reference 이미지: 밴드 순서 반대로 (3, 2, 1 -> B, G, R)
                    # 원래 순서: 1=R, 2=G, 3=B
                    # 반대 순서: 1=B, 2=G, 3=R
                    for i in range(num_bands):
                        if i < 3:
                            # 처음 3개 밴드만 반대로
                            original_band_idx = 3 - i - 1  # 0->2, 1->1, 2->0
                            band = ds.GetRasterBand(original_band_idx + 1)  # GDAL은 1-based
                            img[:, :, i] = band.ReadAsArray()
                        else:
                            # 4번째 이후 밴드는 그대로
                            band = ds.GetRasterBand(i + 1)
                            img[:, :, i] = band.ReadAsArray()
                else:
                    # 일반 순서 (1, 2, 3 -> R, G, B)
                    for i in range(num_bands):
                        band = ds.GetRasterBand(i + 1)
                        img[:, :, i] = band.ReadAsArray()
        
        ds = None  # 메모리 해제
        
        # 리사이즈
        if resize is not None:
            import cv2
            img = cv2.resize(img, resize)
        
        return img
        
    except Exception as e:
        raise ImageLoadError(f"이미지 로딩 실패: {path}") from e


def save_rpc_file_gdal_format(
    image_path: str, 
    gcps: List[GroundControlPoint], 
    output_path: str,
    rpc_model: Optional[any] = None
) -> None:
    """
    RPC 메타데이터를 GDAL 형식으로 저장합니다.
    
    Args:
        image_path: 원본 이미지 경로
        gcps: GCP 리스트
        output_path: 출력 경로
        rpc_model: RPC 모델 객체 (선택적)
        
    Raises:
        ImageLoadError: 이미지 로딩 실패 시
        FileValidationError: 파일 검증 실패 시
    """
    try:
        from osgeo import gdal, osr
        
        # 원본 이미지 열기
        src_ds = gdal.Open(image_path, gdal.GA_ReadOnly)
        if src_ds is None:
            raise ImageLoadError(f"GDAL로 파일을 열 수 없습니다: {image_path}")
        
        # 드라이버 생성
        driver = gdal.GetDriverByName('GTiff')
        if driver is None:
            raise FileValidationError("GTiff 드라이버를 찾을 수 없습니다")
        
        # 출력 파일 생성
        dst_ds = driver.CreateCopy(output_path, src_ds, options=['COMPRESS=LZW'])
        if dst_ds is None:
            raise ImageLoadError(f"출력 파일 생성 실패: {output_path}")
        
        # GCP 설정
        if gcps:
            dst_ds.SetGCPs(gcps, gcps[0].gcpProjection if hasattr(gcps[0], 'gcpProjection') else '')
        
        # RPC 메타데이터 추가
        if rpc_model:
            rpc_metadata = {
                'LINE_OFF': str(rpc_model.line_off),
                'SAMP_OFF': str(rpc_model.samp_off),
                'LAT_OFF': str(rpc_model.lat_off),
                'LONG_OFF': str(rpc_model.lon_off),
                'HEIGHT_OFF': str(rpc_model.height_off),
                'LINE_SCALE': str(rpc_model.line_scale),
                'SAMP_SCALE': str(rpc_model.samp_scale),
                'LAT_SCALE': str(rpc_model.lat_scale),
                'LONG_SCALE': str(rpc_model.lon_scale),
                'HEIGHT_SCALE': str(rpc_model.height_scale),
                'LINE_NUM_COEFF': ' '.join(map(str, rpc_model.line_num)),
                'LINE_DEN_COEFF': ' '.join(map(str, rpc_model.line_den)),
                'SAMP_NUM_COEFF': ' '.join(map(str, rpc_model.samp_num)),
                'SAMP_DEN_COEFF': ' '.join(map(str, rpc_model.samp_den)),
            }
            dst_ds.SetMetadata(rpc_metadata, 'RPC')
        
        # 파일 닫기
        dst_ds.FlushCache()
        dst_ds = None
        src_ds = None
        
        print(f"   💾 RPC 메타데이터 저장 완료: {output_path}")
        
    except Exception as e:
        raise ImageLoadError(f"RPC 파일 저장 실패: {output_path}") from e


def validate_file_exists(file_path: str, file_type: str = "파일") -> None:
    """
    파일 존재 여부를 확인합니다.
    
    Args:
        file_path: 파일 경로
        file_type: 파일 타입 (에러 메시지용)
        
    Raises:
        CustomFileNotFoundError: 파일이 존재하지 않을 경우
    """
    if not os.path.exists(file_path):
        raise CustomFileNotFoundError(f"{file_type}이(가) 존재하지 않습니다: {file_path}")


def ensure_directory(directory: str) -> None:
    """
    디렉토리가 존재하지 않으면 생성합니다.
    
    Args:
        directory: 디렉토리 경로
    """
    Path(directory).mkdir(parents=True, exist_ok=True)


def get_file_size(file_path: str) -> int:
    """
    파일 크기를 바이트 단위로 반환합니다.
    
    Args:
        file_path: 파일 경로
        
    Returns:
        파일 크기 (바이트)
        
    Raises:
        CustomFileNotFoundError: 파일이 존재하지 않을 경우
    """
    validate_file_exists(file_path)
    return os.path.getsize(file_path)


def get_image_info(image_path: str) -> dict:
    """
    이미지 기본 정보를 반환합니다.
    
    Args:
        image_path: 이미지 경로
        
    Returns:
        dict: 이미지 정보 (width, height, bands, dtype, crs, transform)
        
    Raises:
        CustomFileNotFoundError: 파일이 존재하지 않을 경우
        ImageLoadError: 이미지 로딩 실패 시
    """
    validate_file_exists(image_path, "이미지")
    
    try:
        with rasterio.open(image_path) as src:
            return {
                'width': src.width,
                'height': src.height,
                'bands': src.count,
                'dtype': src.dtypes[0],
                'crs': src.crs,
                'transform': src.transform,
                'bounds': src.bounds,
                'nodata': src.nodata
            }
    except Exception as e:
        raise ImageLoadError(f"이미지 정보 읽기 실패: {image_path}") from e

