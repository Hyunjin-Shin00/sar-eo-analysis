"""
Initial Matching Module

This module contains the initial matching steps (Step 6-10) for geometric correction:
- Step 6: AI feature matching
- Step 7: RANSAC filtering
- Step 8: Scale to full resolution
- Step 9: Create GCPs
- Step 10: Initial correction
"""

import os
import math
import json
import numpy as np
import torch
import cv2
from typing import Tuple, List, Dict, Any
import rasterio
from rasterio.control import GroundControlPoint
from rasterio.transform import from_gcps
import subprocess
from lightglue import LightGlue, SuperPoint
from lightglue.utils import rbd
from sklearn.linear_model import RANSACRegressor
from sklearn.preprocessing import PolynomialFeatures
from sklearn.pipeline import Pipeline
from sklearn.metrics import mean_squared_error
import matplotlib.pyplot as plt

# Import utility functions
from ..utils.visualization import apply_clahe_preprocessing, visualize_matches, visualize_ransac_comparison, visualize_gcp_grid_distribution, visualize_initial_correction_matches
from ..utils.geo import sample_bilinear


def ai_feature_matching(lowres_paths: dict, output_dir: str, device: str = 'cpu', target_bands: list = None) -> Tuple[np.ndarray, np.ndarray]:
    """
    STEP 6: AI 기반 특징점 매칭 (SuperPoint + LightGlue)
    
    Input:
        lowres_paths (dict): 저해상도 파일 경로들 (reference, target)
        output_dir (str): 출력 디렉토리 경로
        device (str): GPU 디바이스 ('cuda' 또는 'cpu')
    
    Output:
        Tuple[np.ndarray, np.ndarray]: 매칭된 특징점 좌표 (ref_points, tar_points)
    
    Algorithm:
        - SuperPoint: 딥러닝 기반 특징점 검출 및 디스크립터 생성
        - LightGlue: 그래프 신경망 기반 특징점 매칭
        - CLAHE 전처리로 대비 향상
        - GPU 가속을 통한 고속 처리
        - 저해상도 영상에서 빠른 초기 매칭 수행
    """
    print("\n" + "="*80)
    print("STEP 6: AI 기반 특징점 매칭 (SuperPoint + LightGlue)")
    print("="*80)
    
    # 모델 로드
    print("🤖 AI 모델 로딩 중...")
    DEVICE = 'cpu'  # CUDA 사용 불가로 인해 CPU 사용
    extractor = SuperPoint(max_num_keypoints=4096).eval().to(DEVICE)
    matcher = LightGlue(features='superpoint').eval().to(DEVICE)
    print("   ✅ 모델 로딩 완료")
    
    # 이미지 로드 (무조건 첫 번째 밴드만 사용)
    print("\n📖 영상 로딩 중...")
    with rasterio.open(lowres_paths['reference']) as src:
        # 첫 번째 밴드만 읽기
        ref_gray = src.read(1).astype(np.float32)  # (H, W)
        ref_transform = src.transform
        ref_width = src.width
        ref_height = src.height
    
    with rasterio.open(lowres_paths['target']) as src:
        # 지정된 밴드(MS1, 2, 3 등)가 있으면 평균내어 Grayscale 생성, 없으면 1번 밴드 사용
        if target_bands and len(target_bands) > 0:
            bands_data = []
            for b in target_bands:
                if 1 <= b <= src.count:
                    bands_data.append(src.read(b).astype(np.float32))
            if bands_data:
                tar_gray = np.mean(bands_data, axis=0)
            else:
                tar_gray = src.read(1).astype(np.float32)
        else:
            tar_gray = src.read(1).astype(np.float32)
        
        tar_transform = src.transform
        tar_width = src.width
        tar_height = src.height
    
    print(f"   ✅ Reference: {ref_gray.shape}")
    print(f"   ✅ Target: {tar_gray.shape}")
    
    # CLAHE 전처리로 대비 향상
    print("\n🎨 전처리 중 (CLAHE 대비 향상)...")
    ref_gray_original = ref_gray.copy()
    tar_gray_original = tar_gray.copy()
    
    ref_gray = apply_clahe_preprocessing(ref_gray)
    tar_gray = apply_clahe_preprocessing(tar_gray)
    
    print(f"   ✅ CLAHE 적용 완료 (특징점 추출 성능 향상)")
    
    # CLAHE 후 uint8 → float32 변환 (PyTorch 모델 호환성)
    ref_gray = ref_gray.astype(np.float32) / 255.0
    tar_gray = tar_gray.astype(np.float32) / 255.0
    
    # Torch 텐서 변환
    ref_tensor = torch.from_numpy(ref_gray)[None][None].to(DEVICE)
    tar_tensor = torch.from_numpy(tar_gray)[None][None].to(DEVICE)
    
    # 특징점 추출
    print("\n🔍 특징점 추출 중...")
    with torch.no_grad():
        feats0 = extractor.extract(ref_tensor)
        feats1 = extractor.extract(tar_tensor)
        print(f"   ✅ Reference: {feats0['keypoints'].shape[1]} keypoints")
        print(f"   ✅ Target: {feats1['keypoints'].shape[1]} keypoints")
    
    # 매칭
    print("\n🔗 매칭 수행 중...")
    with torch.no_grad():
        matches01 = matcher({'image0': feats0, 'image1': feats1})
        feats0, feats1, matches01 = [
            rbd(x) for x in [feats0, feats1, matches01]
        ]
    
    # 매칭 결과 추출 (LightGlue 출력 형식 처리)
    # LightGlue는 'matches0' 키를 사용 (image0의 각 keypoint가 image1의 어느 것과 매칭되는지)
    if 'matches0' in matches01:
        matches = matches01['matches0']  # shape: (N,)
        valid = matches > -1
        mkpts0 = feats0['keypoints'][valid].cpu().numpy()
        mkpts1 = feats1['keypoints'][matches[valid]].cpu().numpy()
    elif 'matches' in matches01:
        # 'matches' 키를 사용하는 경우
        matches = matches01['matches']
        if len(matches.shape) == 2:
            # shape가 (N, 2)인 경우: 매칭 쌍
            valid_mask = (matches[:, 0] >= 0) & (matches[:, 1] >= 0)
            matches = matches[valid_mask]
            mkpts0 = feats0['keypoints'][matches[:, 0]].cpu().numpy()
            mkpts1 = feats1['keypoints'][matches[:, 1]].cpu().numpy()
        else:
            # shape가 (N,)인 경우: 인덱스 배열
            valid = matches > -1
            mkpts0 = feats0['keypoints'][valid].cpu().numpy()
            mkpts1 = feats1['keypoints'][matches[valid]].cpu().numpy()
    else:
        raise ValueError(f"Unsupported LightGlue output format. Keys: {matches01.keys()}")
    
    print(f"   ✅ 총 {len(mkpts0)}개의 매칭점 발견")
    
    # 시각화 (원본 크기로, Grayscale을 3채널로 변환)
    print("\n📊 매칭 결과 시각화 중...")
    vis_dir = os.path.join(output_dir, "02_Initial_matching")
    os.makedirs(vis_dir, exist_ok=True)
    
    # Grayscale (0-1) -> RGB (0-255)
    ref_vis = (ref_gray * 255).astype(np.uint8)
    tar_vis = (tar_gray * 255).astype(np.uint8)
    ref_vis = np.stack([ref_vis, ref_vis, ref_vis], axis=-1)  # (H, W, 3)
    tar_vis = np.stack([tar_vis, tar_vis, tar_vis], axis=-1)  # (H, W, 3)
    
    vis_path = os.path.join(vis_dir, "initial_matches.png")
    visualize_matches(ref_vis, tar_vis, mkpts0, mkpts1, vis_path)
    
    print("\n✅ STEP 6 완료: 특징점 매칭이 완료되었습니다.")
    return mkpts0, mkpts1


def ransac_filtering(mkpts0: np.ndarray, mkpts1: np.ndarray,
                     lowres_paths: dict, output_dir: str,
                     ransac_reproj_threshold: float = 3.0,
                     max_iters: int = 5000,
                     confidence: float = 0.99,
                     min_inliers: int = 10) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    STEP 7: RANSAC 아웃라이어 제거

    Input:
        mkpts0 (np.ndarray): Reference 이미지의 매칭점들
        mkpts1 (np.ndarray): Target 이미지의 매칭점들
        lowres_paths (dict): 저해상도 파일 경로들 (시각화용)
        output_dir (str): 출력 디렉토리 경로
        ransac_reproj_threshold (float): 재투영 오차 허용 픽셀 (기본값: 3.0)
        max_iters (int): RANSAC 최대 반복 횟수 (기본값: 5000)
        confidence (float): RANSAC 신뢰도 (기본값: 0.99)
        min_inliers (int): 필터링 후 최소 inlier 개수 — 미달 시 원본 반환 (기본값: 10)

    Output:
        Tuple[np.ndarray, np.ndarray, np.ndarray]: (ref_points, tar_points, inlier_mask)
    """
    print("\n" + "="*80)
    print("STEP 7: RANSAC 기반 아웃라이어 제거")
    print("="*80)

    print(f"📊 입력 매칭점: {len(mkpts0)}개")

    # 전체 inlier mask (fallback용)
    all_true_mask = np.ones(len(mkpts0), dtype=bool)

    # Homography는 최소 4쌍의 대응점이 필요 — 미달 시 RANSAC skip
    if len(mkpts0) < 4:
        print(f"⚠️  매칭점이 {len(mkpts0)}개로 4개 미만 → Homography 추정 불가, 원본 사용")
        return mkpts0, mkpts1, all_true_mask

    # Homography 변환 추정
    print("\n🔧 Homography 변환 추정 중...")
    try:
        H, mask = cv2.findHomography(
            mkpts1, mkpts0,
            method=cv2.RANSAC,
            ransacReprojThreshold=ransac_reproj_threshold,
            maxIters=max_iters,
            confidence=confidence
        )
    except cv2.error as e:
        print(f"⚠️  cv2.findHomography 예외 발생 - 원본 사용: {e}")
        return mkpts0, mkpts1, all_true_mask

    if H is None or mask is None:
        print("⚠️  RANSAC 실패 - 모든 점 사용")
        return mkpts0, mkpts1, all_true_mask

    mask = mask.ravel().astype(bool)
    mkpts0_filtered = mkpts0[mask]
    mkpts1_filtered = mkpts1[mask]

    inlier_ratio = len(mkpts0_filtered) / len(mkpts0) * 100
    print(f"   ✅ Inliers: {len(mkpts0_filtered)}개 ({inlier_ratio:.1f}%)")

    # inlier 최소 개수 미달 시 필터링 결과 폐기
    if len(mkpts0_filtered) < min_inliers:
        print(f"   ⚠️  Inlier 수({len(mkpts0_filtered)})가 최소 기준({min_inliers})에 미달 → 원본 사용")
        return mkpts0, mkpts1, all_true_mask

    inlier_mask = mask
    print(f"   ✅ Outliers: {len(mkpts0) - len(mkpts0_filtered)}개")
    
    # Homography 변환 행렬 출력
    if H is not None:
        print(f"\n📐 추정된 Homography 변환 행렬 (3x3):")
        print(f"   {H[0]}")
        print(f"   {H[1]}")
        print(f"   {H[2]}")
        
        # 변환 분석 (대략적)
        scale_x = math.sqrt(H[0,0]**2 + H[1,0]**2)
        scale_y = math.sqrt(H[0,1]**2 + H[1,1]**2)
        rotation = math.atan2(H[1,0], H[0,0]) * 180 / math.pi
        print(f"\n   분석:")
        print(f"   • X 스케일: {scale_x:.3f}")
        print(f"   • Y 스케일: {scale_y:.3f}")
        print(f"   • 회전각: {rotation:.2f}°")
        print(f"   • 평행이동: ({H[0,2]:.2f}, {H[1,2]:.2f})")
        print(f"   • 원근 왜곡: ({H[2,0]:.6f}, {H[2,1]:.6f})")
    
    # RANSAC 전/후 비교 시각화
    ENABLE_VISUALIZATION = True  # 시각화 활성화
    if ENABLE_VISUALIZATION:
        print("\n📊 RANSAC 전/후 비교 시각화 중...")
        try:
            # 영상 로드 (첫 번째 밴드만 사용)
            with rasterio.open(lowres_paths['reference']) as src:
                ref_gray = src.read(1).astype(np.float32)
                ref_gray = ref_gray / 255.0 if ref_gray.max() > 1.0 else ref_gray
                ref_img = (ref_gray * 255).astype(np.uint8)
                ref_img = np.stack([ref_img, ref_img, ref_img], axis=-1)  # (H, W, 3)
            
            with rasterio.open(lowres_paths['target']) as src:
                tar_gray = src.read(1).astype(np.float32)
                tar_gray = tar_gray / 255.0 if tar_gray.max() > 1.0 else tar_gray
                tar_img = (tar_gray * 255).astype(np.uint8)
                tar_img = np.stack([tar_img, tar_img, tar_img], axis=-1)  # (H, W, 3)
            
            vis_dir = os.path.join(output_dir, "02_Initial_matching")
            os.makedirs(vis_dir, exist_ok=True)
            
            ransac_vis_path = os.path.join(vis_dir, "ransac_comparison.png")
            visualize_ransac_comparison(ref_img, tar_img, mkpts0, mkpts1, 
                                       mkpts0_filtered, mkpts1_filtered, ransac_vis_path)
        except Exception as e:
            print(f"   ⚠️  시각화 실패: {e}")
    
    print("\n✅ STEP 7 완료: 아웃라이어가 제거되었습니다.")
    return mkpts0_filtered, mkpts1_filtered, inlier_mask


def scale_to_fullres(mkpts0: np.ndarray, mkpts1: np.ndarray, 
                          lowres_paths: dict, normalized_paths: dict, output_dir: str) -> Tuple[np.ndarray, np.ndarray]:
    """
    STEP 8: 저해상도 매칭점을 원본 해상도로 스케일링
    
    Input:
        mkpts0 (np.ndarray): Reference 이미지의 매칭점들 (저해상도)
        mkpts1 (np.ndarray): Target 이미지의 매칭점들 (저해상도)
        lowres_paths (dict): 저해상도 파일 경로들
        normalized_paths (dict): 정규화된 파일 경로들
    
    Output:
        Tuple[np.ndarray, np.ndarray]: 원본 해상도로 스케일링된 매칭점들 (ref_points, tar_points)
    
    Algorithm:
        - 저해상도와 원본 해상도의 스케일 비율 계산
        - 좌표 변환 행렬을 사용한 정확한 스케일링
        - Reference와 Target 각각의 해상도 비율 적용
        - 저해상도에서의 빠른 매칭 결과를 원본 해상도로 변환
        - 정밀한 기하보정을 위한 고해상도 좌표 제공
    """
    print("\n" + "="*80)
    print("STEP 8: 좌표 스케일링 및 GRID 필터링")
    print("="*80)
    
    # 스케일 팩터 계산 (normalized 영상 사용)
    with rasterio.open(lowres_paths['reference']) as lowres:
        with rasterio.open(normalized_paths['reference']) as fullres:
            scale_x_ref = fullres.width / lowres.width
            scale_y_ref = fullres.height / lowres.height
            fullres_width = fullres.width
            fullres_height = fullres.height
            lowres_width_ref = lowres.width
    
    with rasterio.open(lowres_paths['target']) as lowres:
        with rasterio.open(normalized_paths['target']) as fullres:
            scale_x_tar = fullres.width / lowres.width
            scale_y_tar = fullres.height / lowres.height
            fullres_width_tar = fullres.width
            lowres_width_tar = lowres.width
    
    print(f"📐 Reference 스케일: {scale_x_ref:.2f} x {scale_y_ref:.2f}")
    print(f"   ({lowres_width_ref} → {fullres_width} pixels)")
    print(f"📐 Target 스케일: {scale_x_tar:.2f} x {scale_y_tar:.2f}")
    print(f"   ({lowres_width_tar} → {fullres_width_tar} pixels)")
    
    if abs(scale_x_ref - scale_x_tar) > 0.1 or abs(scale_y_ref - scale_y_tar) > 0.1:
        print(f"⚠️  WARNING: Reference와 Target의 스케일이 다릅니다!")
        print(f"   해상도 정규화에 문제가 있을 수 있습니다.")
    else:
        print(f"✅ Reference와 Target의 스케일이 일치합니다!")
    
    # 스케일링 적용
    mkpts0_fullres = mkpts0.copy()
    mkpts0_fullres[:, 0] *= scale_x_ref
    mkpts0_fullres[:, 1] *= scale_y_ref
    
    mkpts1_fullres = mkpts1.copy()
    mkpts1_fullres[:, 0] *= scale_x_tar
    mkpts1_fullres[:, 1] *= scale_y_tar
    
    print(f"\n✅ {len(mkpts0_fullres)}개의 매칭점이 원본 해상도로 스케일링되었습니다.")
    
    # GRID 기반 균등 분포 필터링
    from config_example import ENABLE_GRID_FILTERING
    if ENABLE_GRID_FILTERING:
        print(f"\n🔲 GRID 기반 균등 분포 필터링 중...")
        mkpts0_fullres, mkpts1_fullres = grid_based_filtering(
            mkpts0_fullres, mkpts1_fullres,
            fullres_width, fullres_height,
            grid_size=GRID_SIZE,
            max_points_per_grid=MAX_POINTS_PER_GRID
        )
    
    # 초기 기하보정 최종 매칭 결과 시각화 (고품질)
    from config_example import ENABLE_VISUALIZATION
    if ENABLE_VISUALIZATION:
        print("\n📊 초기 기하보정 최종 매칭 결과 시각화 중...")
        try:
            from geometric_correction.utils.visualization import visualize_initial_correction_matches
            visualize_initial_correction_matches(
                normalized_paths['reference'],
                normalized_paths['target'],
                mkpts0_fullres,
                mkpts1_fullres,
                output_dir
            )
        except Exception as e:
            print(f"   ⚠️  시각화 실패: {e}")
    
    print("\n✅ STEP 8 완료")
    return mkpts0_fullres, mkpts1_fullres


def create_gcps(mkpts0: np.ndarray, mkpts1: np.ndarray, 
                     normalized_paths: dict, output_dir: str) -> List[GroundControlPoint]:
    """
    STEP 9: Ground Control Points 생성
    
    Input:
        mkpts0 (np.ndarray): Reference 이미지의 매칭점들
        mkpts1 (np.ndarray): Target 이미지의 매칭점들
        normalized_paths (dict): 정규화된 파일 경로들
        output_dir (str): 출력 디렉토리 경로
    
    Output:
        List[GroundControlPoint]: 생성된 GCP 리스트
    
    Algorithm:
        - 매칭점을 픽셀 좌표에서 지리 좌표로 변환
        - Reference 이미지의 지리 변환 행렬 사용
        - DEM + Geoid에서 고도 정보 추출
        - Ground Control Points 객체 생성
        - 기하보정을 위한 지상 기준점 제공
    """
    print("\n" + "="*80)
    print("STEP 9: GCP (Ground Control Points) 생성")
    print("="*80)
    
    # Reference 이미지의 지리 정보 가져오기 (normalized_paths 사용)
    with rasterio.open(normalized_paths['reference']) as src:
        ref_transform = src.transform
        ref_crs = src.crs
    
    # DEM에서 고도 정보 가져오기
    with rasterio.open(normalized_paths['dem']) as dem:
        dem_data = dem.read(1)
        dem_transform = dem.transform
        dem_nodata = dem.nodata

    # Geoid 정보 가져오기
    with rasterio.open(normalized_paths['geoid']) as geoid:
        geoid_data = geoid.read(1)
        geoid_transform = geoid.transform


    gcps = []
    skipped_count = 0
    for ref_pt, tar_pt in zip(mkpts0, mkpts1):
        # Reference 픽셀 좌표 → 지리 좌표
        geo_x, geo_y = ref_transform * (ref_pt[0], ref_pt[1])

        # DEM에서 고도 추출 (이중선형 보간)
        height = sample_bilinear(dem_data, dem_transform, geo_x, geo_y, nodata=dem_nodata)
        if height is None:
            skipped_count += 1
            continue

        # Geoid에서 고도 추출 (이중선형 보간)
        geoid_height = sample_bilinear(geoid_data, geoid_transform, geo_x, geo_y, nodata=None)
        if geoid_height is None:
            geoid_height = 0.0

        height = height + geoid_height
        
        # GCP 생성 (TARGET 이미지 좌표 + 지리 좌표)
        gcp = GroundControlPoint(
            row=float(tar_pt[1]),
            col=float(tar_pt[0]),
            x=float(geo_x),
            y=float(geo_y),
            z=float(height)
        )
        gcps.append(gcp)
    
    print(f"✅ {len(gcps)}개의 GCP 생성 완료")
    if skipped_count > 0:
        print(f"   ❌ 필터링된 GCP: {skipped_count}개 (DEM 범위 밖)")
    
    # GCP 통계
    heights = [gcp.z for gcp in gcps]
    print(f"\n📊 GCP 통계:")
    print(f"   고도 범위: {min(heights):.1f} ~ {max(heights):.1f} m")
    print(f"   평균 고도: {np.mean(heights):.1f} m")
    
    # GCP를 JSON으로 저장
    gcp_dir = os.path.join(output_dir, "02_Initial_matching")
    os.makedirs(gcp_dir, exist_ok=True)
    
    gcp_data = {
        'num_gcps': len(gcps),
        'crs': str(ref_crs),
        'gcps': [
            {
                'id': i,
                'target_pixel': {'col': gcp.col, 'row': gcp.row},
                'geo_coords': {'x': gcp.x, 'y': gcp.y, 'z': gcp.z}
            }
            for i, gcp in enumerate(gcps)
        ]
    }
    
    gcp_json_path = os.path.join(gcp_dir, "initial_gcps.json")
    with open(gcp_json_path, 'w', encoding='utf-8') as f:
        json.dump(gcp_data, f, indent=2, ensure_ascii=False)
    
    print(f"💾 GCP 정보 저장: {gcp_json_path}")
    
    # GCP 그리드 분포 시각화 (normalized TARGET 이미지 사용)
    try:
        from geometric_correction.utils.visualization import visualize_gcp_grid_distribution
        gcps_pixel = mkpts1  # TARGET 영상 기준 픽셀 좌표
        grid_vis_path = os.path.join(gcp_dir, "gcp_grid_distribution.png")
        visualize_gcp_grid_distribution(
            normalized_paths['target'],
            gcps_pixel,
            grid_vis_path,
            grid_size=GRID_SIZE
        )
    except Exception as e:
        print(f"   ⚠️  GCP 분포 시각화 실패: {e}")
    
    print("\n✅ STEP 9 완료: GCP가 생성되었습니다.")
    return gcps


def initial_correction(gcps: List[GroundControlPoint], normalized_paths: dict, 
                            output_dir: str, method: str = "tps", output_filename: str = None) -> str:
    """
    STEP 10: 초기 기하보정 수행
    
    Input:
        gcps (List[GroundControlPoint]): Ground Control Points
        normalized_paths (dict): 정규화된 파일 경로들
        output_dir (str): 출력 디렉토리 경로
        method (str): 보정 방법 ("tps" 또는 "polynomial")
    
    Output:
        str: 보정된 이미지 경로
    
    Algorithm:
        - TPS (Thin Plate Spline) 또는 다항식 변환 사용
        - GCP를 기반으로 기하학적 변환 모델 생성
        - gdalwarp를 사용한 실제 기하보정 수행
        - 초기 매칭 결과를 바탕으로 한 1차 보정
        - 정밀 보정을 위한 기초 작업 수행
    """
    print("\n" + "="*80)
    print(f"STEP 10: 초기 기하보정 ({method.upper()})")
    print("="*80)
    
    print(f"   📊 GCP 개수: {len(gcps)}개")
    
    # 출력 디렉토리 생성
    initial_dir = os.path.join(output_dir, "03_Initial_correction")
    os.makedirs(initial_dir, exist_ok=True)
    
    # Reference 해상도 및 CRS
    with rasterio.open(normalized_paths['reference']) as ref:
        ref_res_x = abs(ref.transform.a)
        ref_res_y = abs(ref.transform.e)
        ref_crs = ref.crs
    
    print(f"   📐 기준 해상도: {ref_res_x:.2f} x {ref_res_y:.2f} m")
    print(f"   🌍 대상 좌표계: {ref_crs}")
    
    # 임시 파일 경로
    temp_vrt = os.path.join(initial_dir, "temp_with_gcps.vrt")
    if output_filename:
        # 확장자가 없으면 추가
        if not output_filename.lower().endswith(('.tif', '.tiff')):
            output_filename += '.tif'
        corrected_path = os.path.join(initial_dir, output_filename)
    else:
        corrected_path = os.path.join(initial_dir, f"target_initial_{method}_corrected.tif")
    
    # GCP 임베딩
    print("\n🔧 GCP 임베딩 중...")
    gcp_args = []
    for gcp in gcps:
        gcp_args.extend(['-gcp', str(gcp.col), str(gcp.row), str(gcp.x), str(gcp.y), str(gcp.z)])
    
    cmd1 = ['gdal_translate', '-of', 'VRT'] + gcp_args + [normalized_paths['target'], temp_vrt]
    result1 = subprocess.run(cmd1, capture_output=True, text=True)
    
    if result1.returncode != 0:
        raise RuntimeError(f"GCP 임베딩 실패: {result1.stderr}")
    
    print("   ✅ GCP 임베딩 완료")
    
    # 기하보정 수행
    print(f"\n🔧 {method.upper()} 기하보정 수행 중...")
    
    if method.lower() == "tps":
        cmd2 = [
            'gdalwarp', '-overwrite',
            '--config', 'CHECK_DISK_FREE_SPACE', 'FALSE',
            '-tps',
            '-tr', str(ref_res_x), str(ref_res_y),
            '-t_srs', str(ref_crs),
            '-r', 'cubic',
            '-co', 'COMPRESS=LZW',
            '-co', 'BIGTIFF=YES',
            temp_vrt,
            corrected_path
        ]
    else:  # polynomial or affine
        cmd2 = [
            'gdalwarp', '-overwrite',
            '--config', 'CHECK_DISK_FREE_SPACE', 'FALSE',
            '-order', '2',
            '-tr', str(ref_res_x), str(ref_res_y),
            '-t_srs', str(ref_crs),
            '-r', 'cubic',
            '-co', 'COMPRESS=LZW',
            '-co', 'BIGTIFF=YES',
            temp_vrt,
            corrected_path
        ]
    
    result2 = subprocess.run(cmd2, capture_output=True, text=True)
    
    if result2.returncode != 0:
        raise RuntimeError(f"{method.upper()} 기하보정 실패: {result2.stderr}")
    
    print(f"   ✅ {method.upper()} 기하보정 완료")
    
    # 결과 확인
    with rasterio.open(corrected_path) as src:
        print(f"\n✅ 초기 기하보정 완료:")
        print(f"   크기: {src.width} x {src.height} pixels")
        print(f"   CRS: {src.crs}")
        print(f"   해상도: {abs(src.transform.a):.2f} x {abs(src.transform.e):.2f} m")
        print(f"   저장 경로: {corrected_path}")
    
    # 임시 파일 삭제
    if os.path.exists(temp_vrt):
        os.remove(temp_vrt)
    
    # STEP10: 마스크 생성 (0/비0) + 모폴로지 필터 + TIF/PNG 저장
    try:
        print(f"\n🔧 STEP10 마스크 생성 중...")
        mask_tif = corrected_path.replace('.tif', '_mask.tif')
        mask_png = corrected_path.replace('.tif', '_mask.png')
        with rasterio.open(corrected_path) as src:
            band1 = src.read(1)
            profile = src.profile.copy()
        # 이진 마스크
        mask = (band1 != 0).astype('uint8') * 255
        # 모폴로지 (closing -> opening)
        import cv2
        kernel_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        kernel_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_open)
        # 저장
        profile.update({'dtype': 'uint8', 'count': 1, 'nodata': 0})
        with rasterio.open(mask_tif, 'w', **profile) as dst:
            dst.write(mask, 1)
        cv2.imwrite(mask_png, mask)
        print(f"   💾 마스크 저장: {mask_tif}")
        print(f"   💾 마스크 PNG 저장: {mask_png}")
    except Exception as e:
        print(f"   ⚠️ STEP10 마스크 생성 실패: {e}")

    print(f"\n✅ STEP 10 완료: 초기 기하보정 완료")
    
    return corrected_path
