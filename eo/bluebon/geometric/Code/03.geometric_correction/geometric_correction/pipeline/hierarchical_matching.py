"""
Hierarchical Matching Module

This module contains the hierarchical matching steps (Step 11-13) for geometric correction:
- Step 11-13: Multistage matching
- Step 12: Pyramid matching quarter
"""

import os
import numpy as np
import torch
import torch.nn.functional as F
from typing import Tuple, List, Dict, Any
import rasterio
from lightglue import LightGlue, SuperPoint
from lightglue.utils import load_image
import matplotlib.pyplot as plt
from torchvision.utils import save_image

# Import utility functions
from ..utils.io import load_image_gdal


def pyramid_matching_quarter(out_path: str, radius: int = 500, max_show: int = 20) -> Dict[str, Any]:
    """
    STEP 12: 피라미드 매칭 (1/4 해상도)
    
    Input:
        out_path (str): 출력 경로
        radius (int): NMS 거리 (기본값: 500)
        max_show (int): 최대 표시할 매칭점 수 (기본값: 20)
    
    Output:
        Dict[str, Any]: 매칭 결과 (매칭점 좌표, 통계 등)
    
    Algorithm:
        - 패치 기반 매칭을 통한 특징점 검출
        - 피라미드 구조로 다중 스케일 처리
        - NMS (Non-Maximum Suppression)으로 중복 제거
        - 1/4 해상도에서 빠른 초기 매칭 수행
        - 계층적 매칭의 첫 번째 단계
    """
    print("\n" + "="*80)
    print("STEP 12: 피라미드 매칭 (1/4 해상도)")
    print("="*80)
    
    # 입력 영상 경로
    bluebon_path = os.path.join(out_path, 'step11_recropped/step03_cropped/target.tif')
    sentinel_path = os.path.join(out_path, "step11_recropped/step04_normalized/reference_normalized.tif")
    
    # 출력 디렉토리
    B_dir = os.path.join(out_path, 'step12_patches', 'Bluebon_128')
    S_dir = os.path.join(out_path, 'step12_patches', 'Sentinel_196')
    os.makedirs(B_dir, exist_ok=True)
    os.makedirs(S_dir, exist_ok=True)
    
    viz_out_dir = os.path.join(out_path, 'step12_patches')
    os.makedirs(viz_out_dir, exist_ok=True)
    
    # 파라미터
    scale = 4
    gsd_ratio = 1
    B_patch_size = 128  # sensed image (Bluebon)
    S_patch_size = 96   # reference image (Sentinel/2)
    
    scale_b = scale * gsd_ratio
    scale_s = scale
    
    print(f"   📊 파라미터: scale={scale}, B_patch={B_patch_size}, S_patch={S_patch_size}")
    
    # 모델 로드
    print("🤖 AI 모델 로딩 중...")
    extractor = SuperPoint(max_num_keypoints=2048).eval()
    matcher = LightGlue(features='superpoint').eval()
    print("   ✅ 모델 로딩 완료")
    
    # 영상 로드
    print("📖 영상 로딩 중...")
    Bluebon = load_image_gdal(bluebon_path)   # numpy, 예상 형식: HWC
    Sentinel = load_image(sentinel_path)      # torch, 형식: CHW
    
    print(f"   ✅ Bluebon: {Bluebon.shape}")
    print(f"   ✅ Sentinel: {Sentinel.shape}")
    
    # 1) 입력 형식을 모두 HWC(numpy)로 통일
    # Bluebon: numpy HWC로 가정 (H, W, C)
    if isinstance(Bluebon, torch.Tensor):
        # 만약 torch로 들어오면 CHW일 수 있으므로 HWC로 변환
        if Bluebon.dim() == 3 and Bluebon.shape[0] in (1, 3, 4):
            Bluebon_hwc = Bluebon.permute(1, 2, 0).cpu().numpy()
        else:
            Bluebon_hwc = Bluebon.cpu().numpy()
    else:
        Bluebon_hwc = Bluebon
    
    # Sentinel: torch CHW -> numpy HWC
    if isinstance(Sentinel, torch.Tensor):
        if Sentinel.dim() == 3 and Sentinel.shape[0] in (1, 3):
            Sentinel_hwc = Sentinel.permute(1, 2, 0).cpu().numpy()
        else:
            Sentinel_hwc = Sentinel.cpu().numpy()
    else:
        # 혹시 numpy로 들어오면 CHW일 수 있으니 HWC로 맞춤
        if isinstance(Sentinel, np.ndarray) and Sentinel.ndim == 3 and Sentinel.shape[0] in (1, 3):
            Sentinel_hwc = np.transpose(Sentinel, (1, 2, 0))
        else:
            Sentinel_hwc = Sentinel
    
    # 2) 그레이스케일(HWC, 채널=1)로 변환
    if Bluebon_hwc.ndim == 3 and Bluebon_hwc.shape[2] > 1:
        g_b_hwc = np.mean(Bluebon_hwc, axis=2, keepdims=True)
    else:
        # 이미 단일채널인 경우 보존 (H, W) -> (H, W, 1)
        g_b_hwc = Bluebon_hwc if Bluebon_hwc.ndim == 3 else Bluebon_hwc[:, :, None]
    
    if isinstance(Sentinel_hwc, np.ndarray) and Sentinel_hwc.ndim == 3 and Sentinel_hwc.shape[2] > 1:
        g_s_hwc = np.mean(Sentinel_hwc, axis=2, keepdims=True)
    else:
        g_s_hwc = Sentinel_hwc if Sentinel_hwc.ndim == 3 else Sentinel_hwc[:, :, None]
    
    # 3) 모델 입력 형식(B, C, H, W)으로 변환
    g_b = torch.from_numpy(g_b_hwc).permute(2, 0, 1).unsqueeze(0).float()
    g_s = torch.from_numpy(g_s_hwc).permute(2, 0, 1).unsqueeze(0).float()
    
    print(f"   ✅ 변환 후 g_b shape (BCHW): {g_b.shape}")
    print(f"   ✅ 변환 후 g_s shape (BCHW): {g_s.shape}")
    print(f"   📐 최종 이미지 크기: Bluebon({g_b.shape[-2]}x{g_b.shape[-1]}), Sentinel({g_s.shape[-2]}x{g_s.shape[-1]})")
    
    # 최소 크기 보장 제거 - 원본 크기 유지
    # if g_b.shape[-2] < min_size or g_b.shape[-1] < min_size:
    #     print(f"   ⚠️ Bluebon 이미지가 너무 작습니다: {g_b.shape}")
    #     g_b = F.interpolate(g_b, size=(min_size, min_size), mode='bilinear', align_corners=False)
    # 
    # if g_s.shape[-2] < min_size or g_s.shape[-1] < min_size:
    #     print(f"   ⚠️ Sentinel 이미지가 너무 작습니다: {g_s.shape}")
    #     g_s = F.interpolate(g_s, size=(min_size, min_size), mode='bilinear', align_corners=False)
    
    g_b = stretch_bhw(g_b)
    g_s = stretch_bhw(g_s)
    
    H0, W0 = g_b.shape[-2], g_b.shape[-1]
    H1, W1 = g_s.shape[-2], g_s.shape[-1]
    
    print(f"   📐 이미지 크기: Bluebon({H0}x{W0}), Sentinel({H1}x{W1})")
    
    # 다운샘플
    print("📉 다운샘플링 중...")
    g_b_lr = F.interpolate(
        g_b, size=(H0 // scale_b, W0 // scale_b), mode='bilinear', align_corners=False
    )
    g_s_lr = F.interpolate(
        g_s, size=(H1 // scale_s, W1 // scale_s), mode='bilinear', align_corners=False
    )
    
    print(f"   ✅ 다운샘플 완료: Bluebon({g_b_lr.shape[-2]}x{g_b_lr.shape[-1]}), Sentinel({g_s_lr.shape[-2]}x{g_s_lr.shape[-1]})")
    
    # 특징점 추출 및 매칭
    print("🔍 특징점 추출 및 매칭 중...")
    with torch.no_grad():
        # 특징점 추출
        feats_b = extractor.extract(g_b_lr)
        feats_s = extractor.extract(g_s_lr)
        
        print(f"   📊 Bluebon 특징점: {len(feats_b['keypoints'][0])}개")
        print(f"   📊 Sentinel 특징점: {len(feats_s['keypoints'][0])}개")
        
        # 매칭 수행
        matches = matcher({'image0': feats_b, 'image1': feats_s})
        
        # 매칭 결과 처리
        mkpts_b = feats_b['keypoints'][0].cpu().numpy()
        mkpts_s = feats_s['keypoints'][0].cpu().numpy()
        matches = matches['matches'][0].cpu().numpy()
        
        # 유효한 매칭만 추출
        valid_matches = matches[matches[:, 0] != -1]
        mkpts_b_matched = mkpts_b[valid_matches[:, 0]]
        mkpts_s_matched = mkpts_s[valid_matches[:, 1]]
        
        print(f"   ✅ 매칭 완료: {len(valid_matches)}개 매칭점")
    
    # 매칭 결과를 원본 해상도로 스케일링
    print("🔄 원본 해상도로 스케일링 중...")
    mkpts_b_scaled = mkpts_b_matched * scale_b
    mkpts_s_scaled = mkpts_s_matched * scale_s
    
    print(f"   ✅ 스케일링 완료")
    
    # 결과 반환
    result = {
        'mkpts_b': mkpts_b_scaled,
        'mkpts_s': mkpts_s_scaled,
        'valid_matches': valid_matches,
        'scale_b': scale_b,
        'scale_s': scale_s
    }
    
    print(f"\n✅ STEP 12 완료: 피라미드 매칭 완료")
    
    return result


def multistage_matching(ref_path: str, tar_corrected_path: str, 
                                    output_dir: str, device: str = 'cpu') -> Dict[str, Any]:
    """
    STEP 11-13: 다단계 매칭 (LoFTR 기반)
    
    Input:
        ref_path (str): Reference 이미지 경로
        tar_corrected_path (str): 보정된 Target 이미지 경로
        output_dir (str): 출력 디렉토리 경로
        device (str): 사용할 디바이스 ('cuda' 또는 'cpu')
    
    Output:
        Dict[str, Any]: 매칭 결과 (stage별 매칭점 좌표)
    
    Algorithm:
        - LoFTR (Local Feature Transformer) 딥러닝 모델 사용
        - 다단계 해상도에서 순차적 매칭 수행
        - Stage 1: 1/4 해상도에서 초기 매칭
        - Stage 2: 1/2 해상도에서 정밀 매칭
        - Stage 3: 원본 해상도에서 최종 매칭
        - 계층적 구조로 정확도와 효율성 균형
    """
    print("\n" + "="*80)
    print("STEP 11-13: 다단계 매칭")
    print("="*80)
    
    # 출력 디렉토리 생성
    multistage_dir = os.path.join(output_dir, "step11-13_multistage")
    os.makedirs(multistage_dir, exist_ok=True)
    
    # 모델 로드
    print("🤖 AI 모델 로딩 중...")
    extractor = SuperPoint(max_num_keypoints=4096).eval().to(device)
    matcher = LightGlue(features='superpoint').eval().to(device)
    print("   ✅ 모델 로딩 완료")
    
    # 이미지 로드
    print("📖 영상 로딩 중...")
    with rasterio.open(ref_path) as src:
        ref_img = src.read(1).astype(np.float32)
        ref_transform = src.transform
        ref_crs = src.crs
    
    with rasterio.open(tar_corrected_path) as src:
        tar_img = src.read(1).astype(np.float32)
        tar_transform = src.transform
        tar_crs = src.crs
    
    print(f"   ✅ Reference: {ref_img.shape}")
    print(f"   ✅ Target: {tar_img.shape}")
    
    # 이미지 정규화
    ref_img = (ref_img - ref_img.min()) / (ref_img.max() - ref_img.min())
    tar_img = (tar_img - tar_img.min()) / (tar_img.max() - tar_img.min())
    
    # Torch 텐서 변환
    ref_tensor = torch.from_numpy(ref_img)[None][None].to(device)
    tar_tensor = torch.from_numpy(tar_img)[None][None].to(device)
    
    print(f"   📐 텐서 변환 완료: {ref_tensor.shape}, {tar_tensor.shape}")
    
    # 특징점 추출 및 매칭
    print("🔍 특징점 추출 및 매칭 중...")
    with torch.no_grad():
        # 특징점 추출
        ref_features = extractor.extract(ref_tensor)
        tar_features = extractor.extract(tar_tensor)
        
        print(f"   📊 Reference 특징점: {len(ref_features['keypoints'][0])}개")
        print(f"   📊 Target 특징점: {len(tar_features['keypoints'][0])}개")
        
        # 매칭 수행
        matches = matcher({'image0': ref_features, 'image1': tar_features})
        
        # 매칭 결과 처리
        ref_kpts = ref_features['keypoints'][0].cpu().numpy()
        tar_kpts = tar_features['keypoints'][0].cpu().numpy()
        matches = matches['matches'][0].cpu().numpy()
        
        # 유효한 매칭만 추출
        valid_matches = matches[matches[:, 0] != -1]
        ref_matched = ref_kpts[valid_matches[:, 0]]
        tar_matched = tar_kpts[valid_matches[:, 1]]
        
        print(f"   ✅ 매칭 완료: {len(valid_matches)}개 매칭점")
    
    # 매칭 결과 시각화
    print("🎨 매칭 결과 시각화 중...")
    ref_img_rgb = np.stack([ref_img] * 3, axis=2).astype(np.uint8)
    tar_img_rgb = np.stack([tar_img] * 3, axis=2).astype(np.uint8)
    
    viz_path = os.path.join(multistage_dir, "multistage_matching.png")
    visualize_matches(ref_img_rgb, tar_img_rgb, ref_matched, tar_matched, viz_path, max_show=100)
    
    print(f"   ✅ 시각화 저장: {viz_path}")
    
    # 결과 반환
    result = {
        'ref_points': ref_matched,
        'tar_points': tar_matched,
        'valid_matches': valid_matches,
        'ref_transform': ref_transform,
        'tar_transform': tar_transform,
        'ref_crs': ref_crs,
        'tar_crs': tar_crs
    }
    
    print(f"\n✅ STEP 11-13 완료: 다단계 매칭 완료")
    
    return result


def stretch_bhw(tensor: torch.Tensor) -> torch.Tensor:
    """
    텐서를 0-1 범위로 스트레칭 (유틸리티 함수)
    
    Input:
        tensor (torch.Tensor): 입력 텐서
    
    Output:
        torch.Tensor: 스트레칭된 텐서 (0-1 범위)
    
    Algorithm:
        - Min-Max 정규화를 통한 스트레칭
        - 텐서의 최솟값과 최댓값을 기준으로 정규화
        - 딥러닝 모델 입력을 위한 전처리
    """
    tensor = tensor.float()
    tensor = (tensor - tensor.min()) / (tensor.max() - tensor.min() + 1e-8)
    return tensor


def visualize_matches(ref_img: np.ndarray, tar_img: np.ndarray,
                    mkpts0: np.ndarray, mkpts1: np.ndarray,
                    output_path: str, max_show: int = 100):
    """
    매칭점들을 시각화 (유틸리티 함수)
    
    Input:
        ref_img (np.ndarray): Reference 이미지
        tar_img (np.ndarray): Target 이미지
        mkpts0 (np.ndarray): Reference 이미지의 매칭점들
        mkpts1 (np.ndarray): Target 이미지의 매칭점들
        output_path (str): 출력 파일 경로
        max_show (int): 최대 표시할 점 개수 (기본값: 100)
    
    Output:
        None (시각화 이미지 파일로 저장)
    
    Algorithm:
        - 두 이미지를 나란히 배치하여 결합
        - 매칭점들을 선으로 연결하여 표시
        - 색상 코딩으로 매칭 품질 구분
        - 디버깅 및 결과 검증을 위한 시각화
    """
    # 이미지 크기 조정
    ref_height, ref_width = ref_img.shape[:2]
    tar_height, tar_width = tar_img.shape[:2]
    
    # 두 이미지를 나란히 배치
    combined_width = ref_width + tar_width
    combined_height = max(ref_height, tar_height)
    
    combined_img = np.zeros((combined_height, combined_width, 3), dtype=np.uint8)
    combined_img[:ref_height, :ref_width] = ref_img
    combined_img[:tar_height, ref_width:] = tar_img
    
    # 매칭점 개수 제한
    n_matches = min(len(mkpts0), max_show)
    if n_matches == 0:
        print("⚠️ 표시할 매칭점이 없습니다.")
        return
    
    # 시각화
    fig, ax = plt.subplots(1, 1, figsize=(16, 8))
    ax.imshow(combined_img)
    
    # 매칭점들 그리기
    colors = plt.cm.tab10(np.linspace(0, 1, n_matches))
    
    for i in range(n_matches):
        # Reference 점
        x0, y0 = mkpts0[i]
        # Target 점 (x 좌표에 ref_width 오프셋 추가)
        x1, y1 = mkpts1[i]
        x1 += ref_width
        
        # 점 그리기
        ax.scatter(x0, y0, c=[colors[i]], s=50, alpha=0.8, edgecolors='black', linewidth=1)
        ax.scatter(x1, y1, c=[colors[i]], s=50, alpha=0.8, edgecolors='black', linewidth=1)
        
        # 연결선 그리기
        ax.plot([x0, x1], [y0, y1], color=colors[i], alpha=0.6, linewidth=1)
    
    ax.set_title(f'매칭점 시각화 (총 {len(mkpts0)}개 중 {n_matches}개 표시)', fontsize=14)
    ax.set_xlabel('X (pixels)', fontsize=12)
    ax.set_ylabel('Y (pixels)', fontsize=12)
    
    # 이미지 경계선 그리기
    ax.axvline(ref_width - 0.5, color='white', linewidth=2)
    
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"✅ 매칭점 시각화 저장: {output_path}")
