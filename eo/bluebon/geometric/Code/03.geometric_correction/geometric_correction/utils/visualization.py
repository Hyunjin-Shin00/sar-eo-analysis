"""
Utility Functions Module

This module contains utility functions for geometric correction pipeline.
"""

import os
import warnings
from typing import Tuple, List, Optional
import numpy as np
import cv2
import matplotlib
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from rasterio.control import GroundControlPoint


def setup_korean_font():
    """한글 폰트 설정 (경고 메시지 제거)"""
    import warnings
    warnings.filterwarnings('ignore', category=UserWarning)
    
    # 시스템에서 사용 가능한 한글 폰트 찾기
    font_list = fm.findSystemFonts(fontpaths=None, fontext='ttf')
    korean_fonts = []
    
    # OS별 한글 폰트 우선순위
    import platform
    system_name = platform.system()
    
    if system_name == 'Windows':
        font_names = ['Malgun Gothic', 'Gulim', 'Batang', 'Dotum', 'NanumGothic', 'NanumBarunGothic']
    elif system_name == 'Darwin':  # macOS
        font_names = ['AppleGothic', 'NanumGothic', 'NanumBarunGothic', 'Arial']
    else:  # Linux/Ubuntu
        font_names = ['NanumGothic', 'NanumBarunGothic', 'Noto Sans CJK KR', 'Noto Sans KR', 'DejaVu Sans']
    
    for font_path in font_list:
        for font_name in font_names:
            if font_name.lower() in font_path.lower() or font_name.lower().replace(' ', '') in font_path.lower():
                korean_fonts.append((font_name, font_path))
                break
    
    # 한글 폰트 설정
    font_set = False
    if korean_fonts:
        try:
            # 첫 번째로 찾은 한글 폰트 사용
            font_name, font_path = korean_fonts[0]
            font_prop = fm.FontProperties(fname=font_path)
            plt.rcParams['font.family'] = font_prop.get_name()
            plt.rcParams['font.size'] = 10
            font_set = True
        except Exception as e:
            pass
    
    # 폰트를 찾지 못했거나 설정 실패 시
    if not font_set:
        try:
            # 시스템 기본 폰트로 설정 시도
            if system_name == 'Windows':
                plt.rcParams['font.family'] = 'Malgun Gothic'
            elif system_name == 'Darwin':
                plt.rcParams['font.family'] = 'AppleGothic'
            else:
                plt.rcParams['font.family'] = 'DejaVu Sans'
        except Exception:
            plt.rcParams['font.family'] = 'DejaVu Sans'
    
    # 마이너스 기호 깨짐 방지
    plt.rcParams['axes.unicode_minus'] = False
    
    # matplotlib 로깅 레벨 설정 (경고 숨김)
    import logging
    logging.getLogger('matplotlib').setLevel(logging.ERROR)


def visualize_gcp_grid_distribution(image_path: str, gcps_pixel: np.ndarray, 
                                   save_path: str, grid_size: int = 5):
    """
    GCP의 그리드 분포를 시각화합니다.
    
    Args:
        image_path: 영상 파일 경로
        gcps_pixel: GCP 픽셀 좌표 (N, 2) - [x, y]
        save_path: 저장 경로
        grid_size: 그리드 크기 (NxN)
    """
    # 한글 폰트 설정
    setup_korean_font()
    from config_example import ENABLE_VISUALIZATION
    if not ENABLE_VISUALIZATION:
        return
    
    print(f"\n📊 GCP 그리드 분포 시각화 중...")
    
    # 영상 로드
    with rasterio.open(image_path) as src:
        img = src.read(1).astype(np.float32)
        if img.max() > 1.0:
            img = img / 255.0
    
    # 영상 크기
    height, width = img.shape
    
    # 그리드 셀 크기
    cell_width = width / grid_size
    cell_height = height / grid_size
    
    # 각 그리드별 GCP 개수 계산
    grid_counts = {}
    grid_points = {}
    
    for x, y in gcps_pixel:
        grid_x = int(x / cell_width)
        grid_y = int(y / cell_height)
        grid_x = min(grid_x, grid_size - 1)
        grid_y = min(grid_y, grid_size - 1)
        
        grid_id = (grid_x, grid_y)
        grid_counts[grid_id] = grid_counts.get(grid_id, 0) + 1
        if grid_id not in grid_points:
            grid_points[grid_id] = []
        grid_points[grid_id].append((x, y))
    
    # 시각화
    fig, ax = plt.subplots(1, 1, figsize=(12, 12))
    
    # 영상 표시 (grayscale)
    ax.imshow(img, cmap='gray', aspect='auto')
    
    # 그리드 라인 그리기
    for i in range(grid_size + 1):
        # 세로선
        x = i * cell_width
        ax.axvline(x, color='cyan', linewidth=1.5, alpha=0.6)
        # 가로선
        y = i * cell_height
        ax.axhline(y, color='cyan', linewidth=1.5, alpha=0.6)
    
    # 각 그리드에 GCP 개수 표시
    max_count = max(grid_counts.values()) if grid_counts else 1
    
    for grid_y in range(grid_size):
        for grid_x in range(grid_size):
            grid_id = (grid_x, grid_y)
            count = grid_counts.get(grid_id, 0)
            
            # 그리드 중심 좌표
            center_x = (grid_x + 0.5) * cell_width
            center_y = (grid_y + 0.5) * cell_height
            
            # 배경 색상 (GCP 개수에 비례)
            if count > 0:
                alpha = 0.3 + 0.4 * (count / max_count)
                rect = plt.Rectangle(
                    (grid_x * cell_width, grid_y * cell_height),
                    cell_width, cell_height,
                    facecolor='green', alpha=alpha, edgecolor='none'
                )
                ax.add_patch(rect)
                
                # GCP 개수 텍스트
                ax.text(center_x, center_y, str(count),
                       color='white', fontsize=14, fontweight='bold',
                       ha='center', va='center',
                       bbox=dict(boxstyle='round,pad=0.3', facecolor='black', alpha=0.7))
            else:
                # 빈 그리드
                ax.text(center_x, center_y, '0',
                       color='red', fontsize=12, fontweight='bold',
                       ha='center', va='center',
                       bbox=dict(boxstyle='round,pad=0.3', facecolor='black', alpha=0.5))
    
    # GCP 위치 표시 (점)
    if len(gcps_pixel) > 0:
        ax.scatter(gcps_pixel[:, 0], gcps_pixel[:, 1],
                  c='red', s=30, marker='x', linewidths=2,
                  label=f'GCP ({len(gcps_pixel)}개)', zorder=5)
    
    # 통계 정보
    occupied_grids = len([c for c in grid_counts.values() if c > 0])
    total_grids = grid_size * grid_size
    
    ax.set_title(f'GCP 그리드 분포 ({grid_size}×{grid_size})\n'
                f'점유 그리드: {occupied_grids}/{total_grids} ({occupied_grids/total_grids*100:.1f}%) | '
                f'총 GCP: {len(gcps_pixel)}개',
                fontsize=14, fontweight='bold', pad=15)
    ax.set_xlabel('X (pixels)', fontsize=12)
    ax.set_ylabel('Y (pixels)', fontsize=12)
    ax.legend(loc='upper right', fontsize=10)
    ax.grid(False)
    
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    
    print(f"   ✅ GCP 분포 시각화 저장: {save_path}")
    print(f"   📍 점유 그리드: {occupied_grids}/{total_grids} ({occupied_grids/total_grids*100:.1f}%)")
    print(f"   📊 그리드별 GCP 개수: 최소 {min(grid_counts.values() if grid_counts else [0])}, "
          f"최대 {max(grid_counts.values() if grid_counts else [0])}, "
          f"평균 {sum(grid_counts.values())/len(grid_counts) if grid_counts else 0:.1f}")


def visualize_initial_correction_matches(ref_path: str, tar_path: str,
                                         mkpts0: np.ndarray, mkpts1: np.ndarray,
                                         output_dir: str):
    """
    초기 기하보정의 최종 매칭 결과를 고품질로 시각화합니다.
    - 큰 점 크기, 두꺼운 선으로 가시성 극대화
    - 각 매칭점에 번호 표시
    - 고해상도 저장
    
    Args:
        ref_path: Reference 영상 경로
        tar_path: Target 영상 경로
        mkpts0: Reference 매칭점 (N, 2) [x, y]
        mkpts1: Target 매칭점 (N, 2) [x, y]
        output_dir: 출력 디렉토리
    """
    setup_korean_font()
    from config_example import ENABLE_VISUALIZATION
    if not ENABLE_VISUALIZATION:
        return
    
    output_path = os.path.join(output_dir, "04_lowres_matching")
    os.makedirs(output_path, exist_ok=True)
    save_path = os.path.join(output_path, "initial_correction_final_matches.png")
    
    # 영상 로드 (첫 번째 밴드만 사용)
    with rasterio.open(ref_path) as src:
        ref_img = src.read(1)
    with rasterio.open(tar_path) as src:
        tar_img = src.read(1)
    
    # Normalize to 0-255
    ref_img = ((ref_img - ref_img.min()) / (ref_img.max() - ref_img.min()) * 255).astype(np.uint8)
    tar_img = ((tar_img - tar_img.min()) / (tar_img.max() - tar_img.min()) * 255).astype(np.uint8)
    
    # Convert to RGB
    ref_img_rgb = cv2.cvtColor(ref_img, cv2.COLOR_GRAY2RGB)
    tar_img_rgb = cv2.cvtColor(tar_img, cv2.COLOR_GRAY2RGB)
    
    # 영상 크기 맞추기 (높이 통일)
    if ref_img_rgb.shape[0] != tar_img_rgb.shape[0]:
        target_height = max(ref_img_rgb.shape[0], tar_img_rgb.shape[0])
        
        if ref_img_rgb.shape[0] < target_height:
            scale = target_height / ref_img_rgb.shape[0]
            new_width = int(ref_img_rgb.shape[1] * scale)
            ref_img_rgb = cv2.resize(ref_img_rgb, (new_width, target_height))
            mkpts0 = mkpts0 * scale
        
        if tar_img_rgb.shape[0] < target_height:
            scale = target_height / tar_img_rgb.shape[0]
            new_width = int(tar_img_rgb.shape[1] * scale)
            tar_img_rgb = cv2.resize(tar_img_rgb, (new_width, target_height))
            mkpts1 = mkpts1 * scale
    
    # 합치기
    vis_img = np.hstack([ref_img_rgb, tar_img_rgb])
    ref_width = ref_img_rgb.shape[1]
    
    # 매칭점 개수 결정 (최대 50개)
    num_points = min(len(mkpts0), 50)
    if num_points < len(mkpts0):
        # 균등하게 샘플링
        indices = np.linspace(0, len(mkpts0)-1, num_points, dtype=int)
    else:
        indices = np.arange(len(mkpts0))
    
    # 색상 팔레트 (Rainbow)
    colors = []
    for i in range(num_points):
        hue = int(180 * i / num_points)  # 0-180 for OpenCV
        hsv_color = np.uint8([[[hue, 255, 255]]])
        rgb_color = cv2.cvtColor(hsv_color, cv2.COLOR_HSV2RGB)[0, 0]
        colors.append(tuple(map(int, rgb_color)))
    
    # 먼저 모든 선 그리기
    for color_idx, idx in enumerate(indices):
        pt0 = mkpts0[idx]
        pt1 = mkpts1[idx]
        
        pt0_int = tuple(pt0.astype(int))
        pt1_int = tuple((pt1 + [ref_width, 0]).astype(int))
        
        color = colors[color_idx]
        
        # 연결선 그리기 (두껍게)
        cv2.line(vis_img, pt0_int, pt1_int, color, 3, cv2.LINE_AA)
    
    # 그 다음 점과 번호 그리기
    for color_idx, idx in enumerate(indices):
        pt0 = mkpts0[idx]
        pt1 = mkpts1[idx]
        
        pt0_int = tuple(pt0.astype(int))
        pt1_int = tuple((pt1 + [ref_width, 0]).astype(int))
        
        color = colors[color_idx]
        
        # 점 그리기 (크게)
        cv2.circle(vis_img, pt0_int, 10, color, -1, cv2.LINE_AA)
        cv2.circle(vis_img, pt0_int, 11, (255, 255, 255), 2, cv2.LINE_AA)  # 흰색 테두리
        
        cv2.circle(vis_img, pt1_int, 10, color, -1, cv2.LINE_AA)
        cv2.circle(vis_img, pt1_int, 11, (255, 255, 255), 2, cv2.LINE_AA)  # 흰색 테두리
        
        # 번호 표시
        label = str(color_idx + 1)
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.5
        thickness = 2
        
        # 텍스트 크기 계산
        (text_width, text_height), baseline = cv2.getTextSize(label, font, font_scale, thickness)
        
        # Reference 영상에 번호 표시 (점 중앙)
        text_x = pt0_int[0] - text_width // 2
        text_y = pt0_int[1] + text_height // 2
        cv2.putText(vis_img, label, (text_x, text_y), font, font_scale, (0, 0, 0), thickness+1, cv2.LINE_AA)
        cv2.putText(vis_img, label, (text_x, text_y), font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)
        
        # Target 영상에 번호 표시 (점 중앙)
        text_x = pt1_int[0] - text_width // 2
        text_y = pt1_int[1] + text_height // 2
        cv2.putText(vis_img, label, (text_x, text_y), font, font_scale, (0, 0, 0), thickness+1, cv2.LINE_AA)
        cv2.putText(vis_img, label, (text_x, text_y), font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)
    
    # 헤더 정보 추가
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 1.2
    thickness = 3
    
    # 배경 박스 그리기 (왼쪽 상단)
    cv2.rectangle(vis_img, (5, 5), (550, 80), (0, 0, 0), -1)
    cv2.rectangle(vis_img, (5, 5), (550, 80), (255, 255, 255), 2)
    
    # Reference 텍스트
    cv2.putText(vis_img, f"REFERENCE: {ref_img_rgb.shape[1]}x{ref_img_rgb.shape[0]}", (15, 35),
                font, font_scale, (0, 255, 255), thickness, cv2.LINE_AA)
    cv2.putText(vis_img, f"Matches: {len(mkpts0)} (Showing: {num_points})", (15, 65),
                font, font_scale, (255, 255, 0), thickness, cv2.LINE_AA)
    
    # 배경 박스 그리기 (오른쪽 상단)
    cv2.rectangle(vis_img, (ref_width + 5, 5), (ref_width + 500, 50), (0, 0, 0), -1)
    cv2.rectangle(vis_img, (ref_width + 5, 5), (ref_width + 500, 50), (255, 255, 255), 2)
    
    # Target 텍스트
    cv2.putText(vis_img, f"TARGET: {tar_img_rgb.shape[1]}x{tar_img_rgb.shape[0]}", (ref_width + 15, 35),
                font, font_scale, (0, 255, 255), thickness, cv2.LINE_AA)
    
    # 저장 (고품질)
    cv2.imwrite(save_path, cv2.cvtColor(vis_img, cv2.COLOR_RGB2BGR), 
                [cv2.IMWRITE_PNG_COMPRESSION, 3])  # PNG compression 3 = 고품질
    
    print(f"   ✅ 초기 기하보정 최종 매칭 결과 시각화 완료")
    print(f"      💾 저장 위치: {save_path}")
    print(f"      📊 총 매칭점: {len(mkpts0)}개 / 표시: {num_points}개")
    print(f"      🖼️  영상 크기: Reference {ref_img_rgb.shape[1]}x{ref_img_rgb.shape[0]}, Target {tar_img_rgb.shape[1]}x{tar_img_rgb.shape[0]}")


def apply_clahe_preprocessing(image: np.ndarray) -> np.ndarray:
    """
    CLAHE (Contrast Limited Adaptive Histogram Equalization) 전처리를 적용합니다.
    
    Args:
        image: 입력 이미지 (0-255 범위)
        
    Returns:
        np.ndarray: CLAHE가 적용된 이미지
    """
    # 이미지를 uint8로 변환 (CLAHE는 uint8 또는 uint16만 지원)
    if image.dtype != np.uint8:
        # float32/float64를 0-255 범위로 정규화 후 uint8로 변환
        if image.max() <= 1.0:
            # 0-1 범위인 경우
            image_uint8 = (image * 255).astype(np.uint8)
        else:
            # 다른 범위인 경우 정규화
            image_normalized = (image - image.min()) / (image.max() - image.min())
            image_uint8 = (image_normalized * 255).astype(np.uint8)
    else:
        image_uint8 = image
    
    # CLAHE 객체 생성
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    
    # 이미지가 3채널인 경우 각 채널에 CLAHE 적용
    if len(image_uint8.shape) == 3:
        processed_channels = []
        for i in range(image_uint8.shape[2]):
            channel = image_uint8[:, :, i]
            processed_channel = clahe.apply(channel)
            processed_channels.append(processed_channel)
        processed_image = np.stack(processed_channels, axis=2)
    else:
        # 단일 채널인 경우
        processed_image = clahe.apply(image_uint8)
    
    return processed_image


def grid_based_filtering(points_ref: np.ndarray, points_tar: np.ndarray, 
                        grid_size: int = 8, max_points_per_cell: int = 5) -> Tuple[np.ndarray, np.ndarray]:
    """
    그리드 기반 필터링을 수행하여 매칭점의 분포를 균등하게 만듭니다.
    
    Args:
        points_ref: Reference 이미지의 매칭점들
        points_tar: Target 이미지의 매칭점들
        grid_size: 그리드 크기 (grid_size x grid_size)
        max_points_per_cell: 셀당 최대 점 개수
        
    Returns:
        Tuple[np.ndarray, np.ndarray]: 필터링된 매칭점들
    """
    if len(points_ref) == 0:
        return points_ref, points_tar
    
    # 이미지 크기 계산
    ref_max_x, ref_max_y = points_ref.max(axis=0)
    tar_max_x, tar_max_y = points_tar.max(axis=0)
    
    # 그리드 셀 크기 계산
    ref_cell_width = ref_max_x / grid_size
    ref_cell_height = ref_max_y / grid_size
    tar_cell_width = tar_max_x / grid_size
    tar_cell_height = tar_max_y / grid_size
    
    # 필터링된 점들을 저장할 리스트
    filtered_ref = []
    filtered_tar = []
    
    # 각 그리드 셀에 대해 처리
    for i in range(grid_size):
        for j in range(grid_size):
            # Reference 셀 범위
            ref_x_min = i * ref_cell_width
            ref_x_max = (i + 1) * ref_cell_width
            ref_y_min = j * ref_cell_height
            ref_y_max = (j + 1) * ref_cell_height
            
            # Target 셀 범위
            tar_x_min = i * tar_cell_width
            tar_x_max = (i + 1) * tar_cell_width
            tar_y_min = j * tar_cell_height
            tar_y_max = (j + 1) * tar_cell_height
            
            # 해당 셀에 속하는 점들 찾기
            ref_mask = ((points_ref[:, 0] >= ref_x_min) & (points_ref[:, 0] < ref_x_max) &
                       (points_ref[:, 1] >= ref_y_min) & (points_ref[:, 1] < ref_y_max))
            tar_mask = ((points_tar[:, 0] >= tar_x_min) & (points_tar[:, 0] < tar_x_max) &
                       (points_tar[:, 1] >= tar_y_min) & (points_tar[:, 1] < tar_y_max))
            
            # 두 마스크가 모두 True인 점들만 선택
            cell_mask = ref_mask & tar_mask
            cell_ref_points = points_ref[cell_mask]
            cell_tar_points = points_tar[cell_mask]
            
            if len(cell_ref_points) > max_points_per_cell:
                # 셀당 최대 점 개수를 초과하는 경우 랜덤 샘플링
                indices = np.random.choice(len(cell_ref_points), max_points_per_cell, replace=False)
                cell_ref_points = cell_ref_points[indices]
                cell_tar_points = cell_tar_points[indices]
            
            # 필터링된 점들 추가
            if len(cell_ref_points) > 0:
                filtered_ref.append(cell_ref_points)
                filtered_tar.append(cell_tar_points)
    
    # 결과 합치기
    if filtered_ref:
        filtered_ref = np.vstack(filtered_ref)
        filtered_tar = np.vstack(filtered_tar)
    else:
        filtered_ref = np.array([]).reshape(0, 2)
        filtered_tar = np.array([]).reshape(0, 2)
    
    print(f"   📊 그리드 필터링: {len(points_ref)} → {len(filtered_ref)} 점")
    return filtered_ref, filtered_tar


def visualize_gcp_grid_distribution(image_path: str, gcps_pixel: np.ndarray, 
                                  grid_size: int = 8, output_path: Optional[str] = None):
    """
    GCP의 그리드 분포를 시각화합니다.
    
    Args:
        image_path: 이미지 파일 경로
        gcps_pixel: 픽셀 좌표의 GCP들
        grid_size: 그리드 크기
        output_path: 출력 파일 경로 (선택사항)
    """
    setup_korean_font()
    # 이미지 로드
    image = cv2.imread(image_path)
    if image is None:
        print(f"❌ 이미지를 로드할 수 없습니다: {image_path}")
        return
    
    image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    height, width = image_rgb.shape[:2]
    
    # 그리드 셀 크기 계산
    cell_width = width / grid_size
    cell_height = height / grid_size
    
    # 시각화
    fig, ax = plt.subplots(1, 1, figsize=(12, 8))
    ax.imshow(image_rgb)
    
    # 그리드 라인 그리기
    for i in range(grid_size + 1):
        x = i * cell_width
        ax.axvline(x, color='red', alpha=0.3, linewidth=1)
    
    for j in range(grid_size + 1):
        y = j * cell_height
        ax.axhline(y, color='red', alpha=0.3, linewidth=1)
    
    # GCP 점들 그리기
    if len(gcps_pixel) > 0:
        ax.scatter(gcps_pixel[:, 0], gcps_pixel[:, 1], 
                  c='yellow', s=50, alpha=0.8, edgecolors='black', linewidth=1)
    
    # 각 셀의 점 개수 표시
    for i in range(grid_size):
        for j in range(grid_size):
            x_min = i * cell_width
            y_min = j * cell_height
            x_max = (i + 1) * cell_width
            y_max = (j + 1) * cell_height
            
            # 해당 셀에 속하는 점들 개수 계산
            cell_mask = ((gcps_pixel[:, 0] >= x_min) & (gcps_pixel[:, 0] < x_max) &
                        (gcps_pixel[:, 1] >= y_min) & (gcps_pixel[:, 1] < y_max))
            count = np.sum(cell_mask)
            
            # 점 개수 텍스트 표시
            center_x = (x_min + x_max) / 2
            center_y = (y_min + y_max) / 2
            ax.text(center_x, center_y, str(count), 
                   ha='center', va='center', fontsize=10, 
                   bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8))
    
    ax.set_title(f'GCP 그리드 분포 (총 {len(gcps_pixel)}개 점)', fontsize=14)
    ax.set_xlabel('X (pixels)', fontsize=12)
    ax.set_ylabel('Y (pixels)', fontsize=12)
    
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        print(f"✅ GCP 그리드 분포 시각화 저장: {output_path}")
    
    plt.close()
def visualize_matches(ref_img: np.ndarray, tar_img: np.ndarray,
                      mkpts0: np.ndarray, mkpts1: np.ndarray,
                      save_path: str, title: str = "Feature Matching",
                      max_points: int = 100, keep_original_size: bool = False):
    """
    매칭 결과를 시각화하여 저장합니다.

    Args:
        ref_img: Reference 영상 (H, W, 3) RGB
        tar_img: Target 영상 (H, W, 3) RGB
        mkpts0: Reference 매칭점 (N, 2) [x, y]
        mkpts1: Target 매칭점 (N, 2) [x, y]
        save_path: 저장 경로
        title: 제목
        max_points: 표시할 최대 점 개수
        keep_original_size: True면 원본 크기 유지 (크기 조정 안함)
    """
    if not ENABLE_VISUALIZATION:
        return

    # 복사본 생성 (원본 수정 방지)
    ref_img = ref_img.copy()
    tar_img = tar_img.copy()
    mkpts0 = mkpts0.copy()
    mkpts1 = mkpts1.copy()

    if not keep_original_size:
        # 영상 크기가 다르면 같은 높이로 맞추기
        if ref_img.shape[0] != tar_img.shape[0]:
            target_height = max(ref_img.shape[0], tar_img.shape[0])

            if ref_img.shape[0] < target_height:
                scale = target_height / ref_img.shape[0]
                new_width = int(ref_img.shape[1] * scale)
                ref_img = cv2.resize(ref_img, (new_width, target_height))
                mkpts0 = mkpts0 * scale

            if tar_img.shape[0] < target_height:
                scale = target_height / tar_img.shape[0]
                new_width = int(tar_img.shape[1] * scale)
                tar_img = cv2.resize(tar_img, (new_width, target_height))
                mkpts1 = mkpts1 * scale

        # 시각화용 추가 크기 조정 (너무 크면 축소)
        max_height = 800
        if ref_img.shape[0] > max_height:
            scale = max_height / ref_img.shape[0]
            new_ref_width = int(ref_img.shape[1] * scale)
            new_tar_width = int(tar_img.shape[1] * scale)
            ref_img = cv2.resize(ref_img, (new_ref_width, max_height))
            tar_img = cv2.resize(tar_img, (new_tar_width, max_height))
            mkpts0 = mkpts0 * scale
            mkpts1 = mkpts1 * scale
    else:
        # 원본 크기 유지 - 높이만 맞추기
        if ref_img.shape[0] != tar_img.shape[0]:
            target_height = max(ref_img.shape[0], tar_img.shape[0])

            if ref_img.shape[0] < target_height:
                scale = target_height / ref_img.shape[0]
                new_width = int(ref_img.shape[1] * scale)
                ref_img = cv2.resize(ref_img, (new_width, target_height))
                mkpts0 = mkpts0 * scale

            if tar_img.shape[0] < target_height:
                scale = target_height / tar_img.shape[0]
                new_width = int(tar_img.shape[1] * scale)
                tar_img = cv2.resize(tar_img, (new_width, target_height))
                mkpts1 = mkpts1 * scale

    # 영상 합치기
    vis_img = np.hstack([ref_img, tar_img])
    ref_width = ref_img.shape[1]

    # 점 개수 제한
    num_points = min(len(mkpts0), max_points)
    indices = np.linspace(0, len(mkpts0) - 1, num_points, dtype=int)

    # 매칭점과 연결선 그리기
    for idx in indices:
        pt0 = mkpts0[idx]
        pt1 = mkpts1[idx]

        pt0_int = tuple(pt0.astype(int))
        pt1_int = tuple((pt1 + [ref_width, 0]).astype(int))

        # 점 그리기
        cv2.circle(vis_img, pt0_int, 4, (0, 255, 0), -1)
        cv2.circle(vis_img, pt1_int, 4, (0, 255, 0), -1)

        # 연결선 그리기
        cv2.line(vis_img, pt0_int, pt1_int, (255, 0, 0), 1)

    # 텍스트 추가
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.8 if keep_original_size else 1.0
    thickness = 2

    # 왼쪽 (Reference)
    cv2.putText(vis_img, f"Reference: {ref_img.shape[1]}x{ref_img.shape[0]}", (10, 30),
                font, font_scale, (0, 255, 0), thickness)

    # 오른쪽 (Target)
    cv2.putText(vis_img, f"Target: {tar_img.shape[1]}x{tar_img.shape[0]}", (ref_width + 10, 30),
                font, font_scale, (0, 255, 0), thickness)

    # 중앙 하단 (매칭 정보)
    cv2.putText(vis_img, f"Matches: {len(mkpts0)} / Displayed: {num_points}",
                (vis_img.shape[1] // 2 - 200, vis_img.shape[0] - 20),
                font, font_scale, (255, 255, 0), thickness)

    # 저장
    cv2.imwrite(save_path, cv2.cvtColor(vis_img, cv2.COLOR_RGB2BGR))
    print(f"   💾 시각화 저장: {save_path}")
    print(f"      영상 크기: Reference {ref_img.shape[1]}x{ref_img.shape[0]}, Target {tar_img.shape[1]}x{tar_img.shape[0]}")
    print(f"      매칭점: {len(mkpts0)}개 (표시: {num_points}개)")


def visualize_matches(ref_img: np.ndarray, tar_img: np.ndarray,
                    mkpts0: np.ndarray, mkpts1: np.ndarray,
                    output_path: Optional[str] = None, max_show: int = 300):
    """
    매칭점들을 시각화합니다.
    
    Args:
        ref_img: Reference 이미지
        tar_img: Target 이미지
        mkpts0: Reference 이미지의 매칭점들
        mkpts1: Target 이미지의 매칭점들
        output_path: 출력 파일 경로 (선택사항)
        max_show: 최대 표시할 점 개수
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
    
    ax.set_title(f'Tie-point Matching (Total {len(mkpts0)} points, Displayed {n_matches} points)', fontsize=14)
    ax.set_xlabel('X (pixels)', fontsize=12)
    ax.set_ylabel('Y (pixels)', fontsize=12)
    
    # 이미지 경계선 그리기
    ax.axvline(ref_width - 0.5, color='white', linewidth=2)
    
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        print(f"✅ 매칭점 시각화 저장: {output_path}")
    
    plt.close()


def visualize_ransac_comparison(ref_img: np.ndarray, tar_img: np.ndarray,
                               mkpts0: np.ndarray, mkpts1: np.ndarray,
                               inlier_mask: np.ndarray,
                               output_path: Optional[str] = None):
    """
    RANSAC 전후 비교를 시각화합니다.
    
    Args:
        ref_img: Reference 이미지
        tar_img: Target 이미지
        mkpts0: Reference 매칭점
        mkpts1: Target 매칭점
        inlier_mask: Inlier 마스크
        output_path: 출력 파일 경로
    """
    setup_korean_font()
    # 이미지 크기 조정
    ref_height, ref_width = ref_img.shape[:2]
    tar_height, tar_width = tar_img.shape[:2]
    
    # 두 이미지를 나란히 배치
    combined_width = ref_width + tar_width
    combined_height = max(ref_height, tar_height)
    
    combined_img = np.zeros((combined_height, combined_width, 3), dtype=np.uint8)
    combined_img[:ref_height, :ref_width] = ref_img
    combined_img[:tar_height, ref_width:] = tar_img
    
    # 시각화
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(20, 8))
    
    # RANSAC 전 (모든 점)
    ax1.imshow(combined_img)
    ax1.scatter(mkpts0[:, 0], mkpts0[:, 1], c='red', s=30, alpha=0.7)
    ax1.scatter(mkpts1[:, 0] + ref_width, mkpts1[:, 1], c='red', s=30, alpha=0.7)
    ax1.set_title(f'RANSAC 전 (총 {len(mkpts0)}개 점)', fontsize=14)
    ax1.axvline(ref_width - 0.5, color='white', linewidth=2)
    
    # RANSAC 후 (Inlier만)
    ax2.imshow(combined_img)
    inlier_mkpts0 = mkpts0[inlier_mask]
    inlier_mkpts1 = mkpts1[inlier_mask]
    
    ax2.scatter(inlier_mkpts0[:, 0], inlier_mkpts0[:, 1], c='green', s=30, alpha=0.7)
    ax2.scatter(inlier_mkpts1[:, 0] + ref_width, inlier_mkpts1[:, 1], c='green', s=30, alpha=0.7)
    ax2.set_title(f'RANSAC 후 (Inlier {np.sum(inlier_mask)}개 점)', fontsize=14)
    ax2.axvline(ref_width - 0.5, color='white', linewidth=2)
    
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        print(f"✅ RANSAC 비교 시각화 저장: {output_path}")
    
    plt.close()


def visualize_before_after_correction(ref_path: str, tar_before_path: str, 
                                   tar_after_path: str, output_path: Optional[str] = None):
    """
    보정 전후 비교를 시각화합니다.
    
    Args:
        ref_path: Reference 이미지 경로
        tar_before_path: 보정 전 Target 이미지 경로
        tar_after_path: 보정 후 Target 이미지 경로
        output_path: 출력 파일 경로 (선택사항)
    """
    setup_korean_font()
    # 이미지 로드
    ref_img = cv2.imread(ref_path)
    tar_before_img = cv2.imread(tar_before_path)
    tar_after_img = cv2.imread(tar_after_path)
    
    if ref_img is None or tar_before_img is None or tar_after_img is None:
        print("❌ 이미지를 로드할 수 없습니다.")
        return
    
    # BGR to RGB 변환
    ref_img = cv2.cvtColor(ref_img, cv2.COLOR_BGR2RGB)
    tar_before_img = cv2.cvtColor(tar_before_img, cv2.COLOR_BGR2RGB)
    tar_after_img = cv2.cvtColor(tar_after_img, cv2.COLOR_BGR2RGB)
    
    # 시각화
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    
    axes[0].imshow(ref_img)
    axes[0].set_title('Reference', fontsize=14)
    axes[0].axis('off')
    
    axes[1].imshow(tar_before_img)
    axes[1].set_title('Target (Before)', fontsize=14)
    axes[1].axis('off')
    
    axes[2].imshow(tar_after_img)
    axes[2].set_title('Target (After)', fontsize=14)
    axes[2].axis('off')
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        print(f"✅ 보정 전후 비교 시각화 저장: {output_path}")
    
    plt.close()


def visualize_initial_correction_matches(ref_path: str, tar_path: str,
                                       gcps: List[GroundControlPoint],
                                       output_path: Optional[str] = None):
    """
    초기 보정 매칭점들을 시각화합니다.
    
    Args:
        ref_path: Reference 이미지 경로
        tar_path: Target 이미지 경로
        gcps: Ground Control Points
        output_path: 출력 파일 경로 (선택사항)
    """
    setup_korean_font()
    # 이미지 로드
    ref_img = cv2.imread(ref_path)
    tar_img = cv2.imread(tar_path)
    
    if ref_img is None or tar_img is None:
        print("❌ 이미지를 로드할 수 없습니다.")
        return
    
    # BGR to RGB 변환
    ref_img = cv2.cvtColor(ref_img, cv2.COLOR_BGR2RGB)
    tar_img = cv2.cvtColor(tar_img, cv2.COLOR_BGR2RGB)
    
    # GCP를 픽셀 좌표로 변환
    ref_points = np.array([[gcp.col, gcp.row] for gcp in gcps])
    tar_points = np.array([[gcp.col, gcp.row] for gcp in gcps])
    
    # 시각화
    visualize_matches(ref_img, tar_img, ref_points, tar_points, output_path)


def visualize_patch_matching(ref_img: np.ndarray, tar_img: np.ndarray,
                            ref_patches: List[np.ndarray], tar_patches: List[np.ndarray],
                            patch_coords: List[Tuple[int, int]],
                            output_path: Optional[str] = None, max_show: int = 9):
    """
    패치 매칭 결과를 시각화합니다.
    
    Args:
        ref_img: Reference 이미지
        tar_img: Target 이미지
        ref_patches: Reference 패치들
        tar_patches: Target 패치들
        patch_coords: 패치 좌표들
        output_path: 출력 파일 경로 (선택사항)
        max_show: 최대 표시할 패치 개수
    """
    setup_korean_font()
    n_patches = min(len(ref_patches), max_show)
    
    # 시각화
    fig, axes = plt.subplots(3, n_patches, figsize=(4*n_patches, 12))
    if n_patches == 1:
        axes = axes.reshape(-1, 1)
    
    for i in range(n_patches):
        # Reference 패치
        axes[0, i].imshow(ref_patches[i])
        axes[0, i].set_title(f'Ref Patch {i+1}', fontsize=10)
        axes[0, i].axis('off')
        
        # Target 패치
        axes[1, i].imshow(tar_patches[i])
        axes[1, i].set_title(f'Tar Patch {i+1}', fontsize=10)
        axes[1, i].axis('off')
        
        # 패치 위치 표시
        axes[2, i].imshow(ref_img)
        x, y = patch_coords[i]
        rect = patches.Rectangle((x-32, y-32), 64, 64, linewidth=2, edgecolor='red', facecolor='none')
        axes[2, i].add_patch(rect)
        axes[2, i].set_title(f'Location {i+1}', fontsize=10)
        axes[2, i].axis('off')
    
    plt.tight_layout()
    
    if output_path:
        plt.savefig(output_path, dpi=300, bbox_inches='tight')
        print(f"✅ 패치 매칭 시각화 저장: {output_path}")
    
    plt.close()