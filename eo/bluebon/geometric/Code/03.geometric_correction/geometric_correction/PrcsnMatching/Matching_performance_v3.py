import torch
from torchvision.utils import save_image
from lightglue import LightGlue, SuperPoint, DISK, SIFT, ALIKED, DoGHardNet
from lightglue.utils import rbd
import matplotlib.patches as patches
import cv2
import os, re, cv2, numpy as np, torch, pandas as pd
from openpyxl.styles import PatternFill
import torch.nn.functional as F
import numpy as np
import math
import rasterio
import rasterio.warp
from rasterio.enums import Resampling
from rasterio.control import GroundControlPoint
from rasterio.transform import from_gcps
import os
import json
import subprocess
import shutil
from datetime import datetime
from pathlib import Path
from typing import Tuple, List, Optional
from affine import Affine
from pyproj import Transformer
import matplotlib.pyplot as plt
import matplotlib
import matplotlib.font_manager as fm
from osgeo import gdal, osr

# GDAL 경고 제거
try:
    gdal.UseExceptions()
except:
    pass

from kornia.feature import LoFTR
from lightglue.utils import load_image, rbd
from openpyxl.styles import PatternFill
from matplotlib import font_manager, rc
import platform

def Step_13_LoFTR(dir, weight, inlier_min_count: int = 100, visualize: bool = True, 
                   target_resolution: float = None, match_rate_thresh: float = 0.8):
    """
    실패(FAIL) 기준: 조건에 따라 다름
    
    GCP chip 모드이고 target 해상도 >= 3.0m인 경우:
      - 아핀행렬 M 추정 실패
      - inliers >= inlier_min_count (기본 100)이면 무조건 성공 (match_rate_thresh 무시)
      - inliers < inlier_min_count일 때만 matching_rate <= match_rate_thresh면 실패
    
    그 외 (GCP chip 없거나 target 해상도 < 3.0m):
      - 아핀행렬 M 추정 실패
      - matching_rate(=inliers/total_matches) <= match_rate_thresh (기본 0.8)
    
    Args:
        dir (str): 작업 루트 디렉토리
        weight (str): 매칭 알고리즘 ('LOFTR', 'SATLOFTR', 'SIFT')
        inlier_min_count (int): 최소 inlier 개수 (GCP chip 모드용, 기본 100)
        visualize (bool): True이면 PNG 시각화 저장, False이면 시각화 생략 (기본 True)
        target_resolution (float): Target 영상 해상도 (m) - 조건부 판단용
        match_rate_thresh (float): 매칭률 임계값 (기본 0.8)
    """
    weight = weight.upper()
    sift_detector = None
    bf_matcher = None
    ratio_thresh = 0.75
    try:
        import openpyxl
    except ModuleNotFoundError:
        raise RuntimeError("openpyxl이 필요합니다.  pip install openpyxl  후 다시 실행하세요.")

    def draw_full_viz_loftr(full_b, full_s, byx, syx, title, save_path):
        os.makedirs(os.path.dirname(save_path), exist_ok=True)

        # 텐서/넘파이 안전 변환
        def _to_np1hw(x):
            if isinstance(x, torch.Tensor):
                x = x.detach().cpu().numpy()
            x = np.asarray(x)
            # 허용 형태: (1,H,W) 또는 (H,W)
            if x.ndim == 3 and x.shape[0] == 1:
                return x[0]
            elif x.ndim == 2:
                return x
            else:
                raise ValueError(f"Expected (1,H,W) or (H,W), got shape {x.shape}")

        b_np = _to_np1hw(full_b)  # Bluebon
        s_np = _to_np1hw(full_s)  # Sentinel

        Hb, Wb = b_np.shape
        Hs, Ws = s_np.shape

        # Sentinel → Bluebon 순서 + 실제 크기 비율 반영
        fig = plt.figure(figsize=(10, 4.5))
        gs = fig.add_gridspec(1, 2, width_ratios=[Ws, Wb], wspace=0.05)

        # Sentinel (좌)
        ax0 = fig.add_subplot(gs[0])
        ax0.imshow(s_np, cmap="gray", vmin=0, vmax=1)
        ax0.set_xlim(0, Ws);
        ax0.set_ylim(Hs, 0)
        ax0.set_box_aspect(Hs / Ws)  # 영상 비율 고정
        ax0.set_title(title + " - Sentinel")
        ax0.axis("off")
        if syx is not None:
            sy, sx = syx
            ax0.scatter([sx], [sy], s=12, marker='o', color='r')

        # Bluebon (우)
        ax1 = fig.add_subplot(gs[1])
        ax1.imshow(b_np, cmap="gray", vmin=0, vmax=1)
        ax1.set_xlim(0, Wb);
        ax1.set_ylim(Hb, 0)
        ax1.set_box_aspect(Hb / Wb)
        ax1.set_title(title + " - Bluebon")
        ax1.axis("off")
        if byx is not None:
            by, bx = byx
            ax1.scatter([bx], [by], s=12, marker='o', color='r')

        plt.tight_layout()
        plt.savefig(save_path, dpi=220, bbox_inches="tight")
        plt.close(fig)

    # ----- (기존) 시각화 헬퍼들 -----
    if visualize:
        import matplotlib.pyplot as plt

        def _draw_vis(name_to_show, sent_np, blue_np, mapped_xy, out_dir):
            Hs, Ws = sent_np.shape[:2]
            Hb, Wb = blue_np.shape[:2]
            cx, cy = float(mapped_xy[0]), float(mapped_xy[1])
            half = 128 / 2.0
            fig = plt.figure(figsize=(10, 5))
            gs = fig.add_gridspec(1, 2, width_ratios=[Ws, Wb], wspace=0.05)
            ax0 = fig.add_subplot(gs[0])  # Sentinel
            ax1 = fig.add_subplot(gs[1])  # Bluebon
            ax0.imshow(sent_np, cmap='gray')
            ax0.set_xlim(0, Ws); ax0.set_ylim(Hs, 0); ax0.set_box_aspect(Hs / Ws)
            ax0.scatter([cx], [cy], s=100, c='red', marker='x', linewidths=2)
            rect = plt.Rectangle((cx - half, cy - half), 2 * half, 2 * half,
                                 fill=False, edgecolor='red', linewidth=2)
            ax0.add_patch(rect)
            ax0.set_title(f"Sentinel\n{name_to_show}")
            ax0.axis('off')
            ax1.imshow(blue_np, cmap='gray')
            ax1.set_xlim(0, Wb); ax1.set_ylim(Hb, 0); ax1.set_box_aspect(Hb / Wb)
            ax1.scatter([Wb / 2.0], [Hb / 2.0], s=100, c='red', marker='x', linewidths=2)
            ax1.set_title("Bluebon patch")
            ax1.axis('off')
            os.makedirs(out_dir, exist_ok=True)
            outp = os.path.join(out_dir, f"loftr_result_{name_to_show}.png")
            plt.savefig(outp, dpi=150, bbox_inches="tight")
            plt.close()

        def _draw_matches(name_to_show, img_b, img_s, k0, k1, inlier_mask, out_dir):
            Hb, Wb = img_b.shape; Hs, Ws = img_s.shape
            H = max(Hb, Hs)
            canvas = np.zeros((H, Wb + Ws), dtype=np.float32)
            canvas[:Hb, :Wb] = img_b / 255.0
            canvas[:Hs, Wb:Wb + Ws] = img_s / 255.0
            fig, ax = plt.subplots(1, 1, figsize=(12, 6))
            ax.imshow(canvas, cmap='gray'); ax.axis('off')
            N = int(k0.shape[0]); nin = 0
            if N > 0:
                k1_shift = k1.copy(); k1_shift[:, 0] += Wb
                if inlier_mask is None:
                    inlier_mask = np.ones((N,), dtype=bool)
                else:
                    inlier_mask = inlier_mask.astype(bool).ravel()
                    if inlier_mask.shape[0] != N:
                        inlier_mask = np.resize(inlier_mask, (N,))
                out_mask = ~inlier_mask
                nin = int(inlier_mask.sum())
                for p0, p1 in zip(k0[out_mask], k1_shift[out_mask]):
                    ax.plot([p0[0], p1[0]], [p0[1], p1[1]], linewidth=0.6, alpha=0.25)
                for p0, p1 in zip(k0[inlier_mask], k1_shift[inlier_mask]):
                    ax.plot([p0[0], p1[0]], [p0[1], p1[1]], linewidth=1.8, alpha=0.9)
                ax.scatter(k0[out_mask, 0], k0[out_mask, 1], s=8, alpha=0.35)
                ax.scatter(k1_shift[out_mask, 0], k1_shift[out_mask, 1], s=8, alpha=0.35)
                ax.scatter(k0[inlier_mask, 0], k0[inlier_mask, 1], s=22, alpha=0.95)
                ax.scatter(k1_shift[inlier_mask, 0], k1_shift[inlier_mask, 1], s=22, alpha=0.95)
            pct = (nin / N) * 100.0 if N > 0 else 0.0
            ax.set_title(f"LoFTR matches — inliers {nin} / {N} ({pct:.1f}%)\n{name_to_show}")
            os.makedirs(out_dir, exist_ok=True)
            outp = os.path.join(out_dir, f"loftr_matches_{name_to_show}.png")
            plt.savefig(outp, dpi=150, bbox_inches="tight")
            plt.close()
    else:
        def _draw_vis(*args, **kwargs): return
        def _draw_matches(*args, **kwargs): return

    # --- 경로 설정 ---
    # --- 경로 설정 ---
    # 사용자 요청에 따라 폴더명 변경: step12_patches -> 04_patches
    B_dir = os.path.join(dir, '04_patches', "Bluebon_128")
    
    # GCP chip 모드인지 확인 (GCPChip_224 디렉토리 존재 여부로 판단)
    gcp_chip_dir = os.path.join(dir, '04_patches', "GCPChip_224")
    sentinel_dir = os.path.join(dir, '04_patches', "Sentinel_196")
    
    if os.path.exists(gcp_chip_dir):
        S_dir = gcp_chip_dir
        use_gcp_chip_mode = True
    else:
        S_dir = sentinel_dir
        use_gcp_chip_mode = False
    
    # 사용자 요청: 05_{Algorithm}_result
    if weight == 'LOFTR' or weight == 'SATLOFTR':
        # LoFTR/SatLoFTR 사용 시에도 05번 폴더 사용
        save_root = os.path.join(dir, f'05_{weight}_result')
    else:
        # 그 외(기존 SuperPoint 등)
        save_root = os.path.join(dir, f'05_{weight}_result')
        
    save_success = os.path.join(save_root, 'success')
    save_fallback = os.path.join(save_root, 'fail')
    os.makedirs(save_success, exist_ok=True)
    os.makedirs(save_fallback, exist_ok=True)

    # --- 고정 파라미터 ---
    # center_xy는 패치 크기에 따라 동적으로 계산 (각 패치별로 img_b.shape로부터 계산)
    INLIER_FAIL_MAX = 5  # 인라이어 5개 이하이면 FAIL

    def to_t(gray, device):
        return torch.from_numpy(gray)[None, None].float().to(device) / 255.0

    # GCP chip 모드인지에 따라 정규식 패턴 및 컬럼명 변경
    # 패턴: patchXX_ 접두사가 있을 수 있음
    if use_gcp_chip_mode:
        pat_gcp = re.compile(
            r"(?:patch\d+_)?GCPChip_(?P<Sy>-?\d+(?:\.\d+)?)_(?P<Sx>-?\d+(?:\.\d+)?)_Bluebon_(?P<By>-?\d+(?:\.\d+)?)_(?P<Bx>-?\d+(?:\.\d+)?)",
            re.IGNORECASE
        )
        pat_sentinel = re.compile(
            r"(?:patch\d+_)?Sentinel_(?P<Sy>-?\d+(?:\.\d+)?)_(?P<Sx>-?\d+(?:\.\d+)?)_Bluebon_(?P<By>-?\d+(?:\.\d+)?)_(?P<Bx>-?\d+(?:\.\d+)?)",
            re.IGNORECASE
        )
        ref_label = "GcpChip"  # 컬럼명에 사용할 라벨
    else:
        pat_sentinel = re.compile(
            r"(?:patch\d+_)?Sentinel_(?P<Sy>-?\d+(?:\.\d+)?)_(?P<Sx>-?\d+(?:\.\d+)?)_Bluebon_(?P<By>-?\d+(?:\.\d+)?)_(?P<Bx>-?\d+(?:\.\d+)?)",
            re.IGNORECASE
        )
        pat_gcp = None
        ref_label = "Sentinel"  # 컬럼명에 사용할 라벨

    def parse_coords_from_name(long_name):
        # GCP chip 모드인 경우 두 패턴 모두 시도 (SuperPoint로 전환된 경우 대비)
        if use_gcp_chip_mode and pat_gcp is not None:
            m = pat_gcp.search(long_name)
            if m:
                return float(m.group("By")), float(m.group("Bx")), float(m.group("Sy")), float(m.group("Sx"))
            # GCP chip 패턴이 실패하면 Sentinel 패턴 시도
            m = pat_sentinel.search(long_name)
            if m:
                return float(m.group("By")), float(m.group("Bx")), float(m.group("Sy")), float(m.group("Sx"))
        else:
            m = pat_sentinel.search(long_name)
            if m:
                return float(m.group("By")), float(m.group("Bx")), float(m.group("Sy")), float(m.group("Sx"))
        
        # 파싱 실패
        return None, None, None, None

    short_pat = re.compile(r"^(patch\d+)", re.IGNORECASE)
    def short_name_of(filename):
        base = os.path.splitext(filename)[0]
        m = short_pat.match(base)
        return m.group(1) if m else base

    # --- 공통 파일명 ---
    # macOS 메타데이터 파일 (._로 시작) 제외
    b_names = {fn for fn in os.listdir(B_dir) 
               if fn.lower().endswith('.tif') and not fn.startswith('._')}
    s_names = {fn for fn in os.listdir(S_dir) 
               if fn.lower().endswith('.tif') and not fn.startswith('._')}
    common_names = sorted(b_names & s_names)
    
    # 실제 파일명을 보고 패턴 자동 감지 (디렉토리 존재만으로는 부족)
    if common_names:
        first_file = common_names[0]
        has_gcp_pattern = 'GCPChip' in first_file or 'GcpChip' in first_file
        has_sentinel_pattern = 'Sentinel' in first_file
        
        if use_gcp_chip_mode and has_sentinel_pattern and not has_gcp_pattern:
            # GCP chip 모드로 설정되었지만 실제 파일은 Sentinel 패턴
            print(f"   ⚠️  경고: GCP chip 모드로 설정되었지만 실제 파일명은 Sentinel 패턴입니다.")
            print(f"   ℹ️  파일명 패턴을 자동 감지하여 Sentinel 모드로 전환합니다.")
            use_gcp_chip_mode = False
            ref_label = "Sentinel"
            # 패턴 재설정
            pat_gcp = None
            pat_sentinel = re.compile(
                r"(?:patch\d+_)?Sentinel_(?P<Sy>-?\d+(?:\.\d+)?)_(?P<Sx>-?\d+(?:\.\d+)?)_Bluebon_(?P<By>-?\d+(?:\.\d+)?)_(?P<Bx>-?\d+(?:\.\d+)?)",
                re.IGNORECASE
            )
        elif not use_gcp_chip_mode and has_gcp_pattern:
            # Sentinel 모드로 설정되었지만 실제 파일은 GCP chip 패턴
            print(f"   ⚠️  경고: Sentinel 모드로 설정되었지만 실제 파일명은 GCP chip 패턴입니다.")
            print(f"   ℹ️  파일명 패턴을 자동 감지하여 GCP chip 모드로 전환합니다.")
            use_gcp_chip_mode = True
            ref_label = "GcpChip"
            # 패턴 재설정
            pat_gcp = re.compile(
                r"(?:patch\d+_)?GCPChip_(?P<Sy>-?\d+(?:\.\d+)?)_(?P<Sx>-?\d+(?:\.\d+)?)_Bluebon_(?P<By>-?\d+(?:\.\d+)?)_(?P<Bx>-?\d+(?:\.\d+)?)",
                re.IGNORECASE
            )
            pat_sentinel = re.compile(
                r"(?:patch\d+_)?Sentinel_(?P<Sy>-?\d+(?:\.\d+)?)_(?P<Sx>-?\d+(?:\.\d+)?)_Bluebon_(?P<By>-?\d+(?:\.\d+)?)_(?P<Bx>-?\d+(?:\.\d+)?)",
                re.IGNORECASE
            )
    
    if not common_names:
        print(f"   ⚠️ 매칭할 패치 파일을 찾을 수 없습니다.")
        print(f"   Bluebon 패치: {len(b_names)}개, {ref_label} 패치: {len(s_names)}개")
        print(f"   공통 파일: {len(common_names)}개")
        if len(b_names) > 0:
            print(f"   Bluebon 예시: {sorted(b_names)[:3]}")
        if len(s_names) > 0:
            print(f"   {ref_label} 예시: {sorted(s_names)[:3]}")
        return {
            "stage4": {
                "ref_points": np.empty((0, 2), dtype=np.float32),
                "tar_points": np.empty((0, 2), dtype=np.float32),
                "num_matches": 0,
            }
        }

    if weight == 'LOFTR':
        device = "cuda" if torch.cuda.is_available() else "cpu"
        matcher = LoFTR(pretrained='outdoor').to(device).eval()
        print("✅ Loaded original LoFTR (outdoor pretrained)")

    elif weight == 'SATLOFTR':
        device = "cuda" if torch.cuda.is_available() else "cpu"

        # 1) 기존대로 outdoor로 모델 뼈대 만들기
        matcher = LoFTR(pretrained='outdoor').to(device).eval()

        # 2) Lightning ckpt 로드 (repo 내 models/CheckPoints 경로)
        ckpt_path = str((Path(__file__).resolve().parent.parent / 'models' / 'CheckPoints' / 'sat_loftr_448_with_rot_aug.ckpt'))
        # Lightning ckpt를 안전하게 로드 (클래스 언피클 없이 state_dict만)
        try:
            ckpt = torch.load(ckpt_path, map_location=device, weights_only=True)
        except Exception:
            # 안전 로드 실패 시: 신뢰된 체크포인트이므로 일반 로드 허용
            ckpt = torch.load(ckpt_path, map_location=device, weights_only=False)

        # 3) state_dict 뽑기
        state_dict = ckpt.get("state_dict", ckpt)
        # 4) prefix 정리 (필요 시)
        state_dict = {k.replace("matcher.", ""): v for k, v in state_dict.items()}

        # 5) 가중치 주입
        missing, unexpected = matcher.load_state_dict(state_dict, strict=False)
        print("✅ SatLoFTR weights loaded",
              f"\nmissing: {sorted(missing)}\nunexpected: {sorted(unexpected)}")
    elif weight == 'SIFT':
        device = "cpu"
        sift_detector = cv2.SIFT_create(nfeatures=2048)
        bf_matcher = cv2.BFMatcher(cv2.NORM_L2, crossCheck=False)
        print("✅ Loaded OpenCV SIFT detector with BFMatcher (L2, ratio thresh=0.75)")
    else:
        raise ValueError("weight must be one of ['LOFTR', 'SATLOFTR', 'SIFT']")

    # 누적 결과
    new_rows = []
    summary_rows = []   # << 요약 시트용

    # 조건부 성공/실패 기준 결정
    # GCP chip 모드이고 target 해상도 >= 3.0m: inlier_min_count 사용
    # 그 외: match_rate_thresh 사용
    use_inlier_count_criterion = (use_gcp_chip_mode and target_resolution is not None and target_resolution >= 3.0)
    
    print('====실패(FAIL) 기준====')
    print('  1. 변환계수 추정 실패')
    if use_inlier_count_criterion:
        print(f'  2-1. inliers >= {inlier_min_count}이면 무조건 성공 (match_rate_thresh 무시)')
        print(f'  2-2. inliers < {inlier_min_count}이면 matching_rate <= {match_rate_thresh}일 때 실패')
    else:
        print(f'  2. matching_rate <= {match_rate_thresh} (GCP chip 없거나 해상도 < 3.0m)')
    print(f'\n   📊 처리할 패치: {len(common_names)}개')
    
    # 실패 원인 통계
    fail_stats = {
        'NO_MATCHES': 0,
        'LOW_MATCH_COUNT': 0,
        'AFFINE_EST_FAIL': 0,
        'NO_INLIER_MASK': 0,
        'INSUFFICIENT_INLIERS': 0,
        'LOW_MATCH_RATE': 0
    }

    success_count = 0
    fail_count = 0
    fail_details = []  # 실패 상세 정보 저장
    parse_fail_count = 0
    parse_fail_examples = []
    
    for idx, long_name in enumerate(common_names):
        if (idx + 1) % 10 == 0:
            print(f"   진행: {idx + 1}/{len(common_names)} (성공: {success_count}, 실패: {fail_count})")
        name_short = short_name_of(long_name)
        By, Bx, Sy, Sx = parse_coords_from_name(long_name)
        
        # 좌표 파싱 실패 체크
        if By is None or Bx is None or Sy is None or Sx is None:
            parse_fail_count += 1
            if parse_fail_count <= 5:  # 처음 5개만 로그
                parse_fail_examples.append(long_name)
            continue  # 파싱 실패한 파일은 건너뛰기

        img_b_path = os.path.join(B_dir, long_name)
        img_s_path = os.path.join(S_dir, long_name)
        
        # 파일 존재 확인
        if not os.path.exists(img_b_path):
            print(f"[warn] 이미지 로드 실패: 파일 없음 - {img_b_path}")
            continue
        if not os.path.exists(img_s_path):
            print(f"[warn] 이미지 로드 실패: 파일 없음 - {img_s_path}")
            continue
        
        img_b = cv2.imread(img_b_path, cv2.IMREAD_GRAYSCALE)
        img_s = cv2.imread(img_s_path, cv2.IMREAD_GRAYSCALE)
        
        if img_b is None:
            print(f"[warn] 이미지 로드 실패: OpenCV 읽기 실패 - {img_b_path}")
            continue
        if img_s is None:
            print(f"[warn] 이미지 로드 실패: OpenCV 읽기 실패 - {img_s_path}")
            continue

        # 패치 크기에 따른 중심점 및 기준점 동적 계산
        bluebon_center = np.array([img_b.shape[1] / 2.0, img_b.shape[0] / 2.0], dtype=np.float32)  # Bluebon 패치 중심
        ref_center = np.array([img_s.shape[1] / 2.0, img_s.shape[0] / 2.0], dtype=np.float32)  # Reference 패치 중심

        if weight in ('LOFTR', 'SATLOFTR'):
            with torch.no_grad():
                pred = matcher({'image0': to_t(img_b, device), 'image1': to_t(img_s, device)})

            k0 = pred.get('keypoints0', torch.empty(0, 2, device=device)).detach().cpu().numpy()
            k1 = pred.get('keypoints1', torch.empty(0, 2, device=device)).detach().cpu().numpy()
            conf = pred.get('confidence', None)  # (N,)일 가능성
            conf_np = None
            if conf is not None:
                conf_np = conf.detach().cpu().numpy()
        else:
            k0, k1, conf_np = run_sift_matching(
                img_b,
                img_s,
                sift_detector=sift_detector,
                matcher=bf_matcher,
                ratio_thresh=ratio_thresh
            )

        N = int(k0.shape[0])
        mapped_xy = (96.0, 96.0)
        nin = 0
        matching_rate = 0.0
        M = None
        inlier_mask_for_draw = None
        results_label = "fail"

        # 추정
        if N >= 3:
            M_est, inliers = cv2.estimateAffinePartial2D(
                k0.astype(np.float32), k1.astype(np.float32),
                method=cv2.RANSAC, ransacReprojThreshold=3.0,
                maxIters=2000, confidence=0.999
            )
            nin = int(inliers.sum()) if inliers is not None else 0
            matching_rate = (float(nin) / float(N)) if N > 0 else 0.0
        else:
            M_est, inliers = None, None
            nin = 0
            matching_rate = 0.0
        fail_reasons = []
        if N == 0:
            fail_reasons.append("NO_MATCHES")
        elif N < 3:
            fail_reasons.append(f"LOW_MATCH_COUNT(n={N}<3)")
        if M_est is None:
            fail_reasons.append("AFFINE_EST_FAIL")
        if inliers is None:
            fail_reasons.append("NO_INLIER_MASK")
        
        # 조건부 실패 기준 적용
        if use_inlier_count_criterion:
            # GCP chip 모드 + 해상도 >= 3.0m: inlier >= 100이면 무조건 성공, 그 외는 match_rate_thresh 체크
            if nin >= inlier_min_count:
                # inlier가 충분하면 match_rate_thresh 무시하고 성공
                pass
            else:
                # inlier가 부족하면 match_rate_thresh 체크
                if matching_rate <= match_rate_thresh:
                    fail_reasons.append(f"LOW_MATCH_RATE(rate={matching_rate:.3f}<= {match_rate_thresh}, inliers={nin}<{inlier_min_count})")
        else:
            # GCP chip 없거나 해상도 < 3.0m: match_rate_thresh 체크
            if matching_rate <= match_rate_thresh:
                fail_reasons.append(f"LOW_MATCH_RATE(rate={matching_rate:.3f}<= {match_rate_thresh})")

        # confidence(요약 시트용): 우선순위 = 인라이어 평균(conf) > matching_rate
        if conf_np is not None and N > 0 and inliers is not None:
            conf_summary = float(np.mean(conf_np[inliers.ravel().astype(bool)])) if nin > 0 else 0.0
        else:
            conf_summary = float(matching_rate)

        # 조건부 실패 판정
        if use_inlier_count_criterion:
            # GCP chip 모드 + 해상도 >= 3.0m: inlier >= 100이면 무조건 성공, 그 외는 match_rate_thresh 체크
            if nin >= inlier_min_count:
                # inlier가 충분하면 match_rate_thresh 무시하고 성공
                is_fail = (M_est is None)
            else:
                # inlier가 부족하면 match_rate_thresh 체크
                is_fail = (M_est is None) or (matching_rate <= match_rate_thresh)
        else:
            # GCP chip 없거나 해상도 < 3.0m: match_rate_thresh 체크
            is_fail = (M_est is None) or (matching_rate <= match_rate_thresh)

        if not is_fail and M_est is not None:  # 방어적 체크 추가
            success_count += 1
            M = M_est
            inlier_mask_for_draw = inliers.ravel().astype(bool) if inliers is not None else None
            pt = np.array([[bluebon_center]], dtype=np.float32)  # 동적 계산된 중심점 사용
            mapped = cv2.transform(pt, M)[0, 0]  # (x,y)
            mapped_xy = (float(mapped[0]), float(mapped[1]))
            results_label = "success"
            fail_reason_str = ""  # 성공이면 빈 문자열
        else:
            fail_count += 1
            # 실패 원인 통계 업데이트
            for reason in fail_reasons:
                if reason.startswith("NO_MATCHES"):
                    fail_stats['NO_MATCHES'] += 1
                elif reason.startswith("LOW_MATCH_COUNT"):
                    fail_stats['LOW_MATCH_COUNT'] += 1
                elif reason.startswith("AFFINE_EST_FAIL"):
                    fail_stats['AFFINE_EST_FAIL'] += 1
                elif reason.startswith("NO_INLIER_MASK"):
                    fail_stats['NO_INLIER_MASK'] += 1
                elif reason.startswith("INSUFFICIENT_INLIERS"):
                    fail_stats['INSUFFICIENT_INLIERS'] += 1
                elif reason.startswith("LOW_MATCH_RATE"):
                    fail_stats['LOW_MATCH_RATE'] += 1
            
            # 실패 상세 정보 저장 (처음 20개만 상세 로그)
            fail_reason_str = "; ".join(fail_reasons) if fail_reasons else "UNKNOWN_FAIL"
            if fail_count <= 20:
                fail_details.append({
                    'name': name_short,
                    'total_matches': N,
                    'inliers': nin,
                    'matching_rate': f"{matching_rate:.3f}",
                    'reasons': fail_reason_str
                })
            
            if N >= 1:
                j = int(np.linalg.norm(k0 - bluebon_center, axis=1).argmin())  # 동적 계산된 중심점 사용
                mapped = k1[j]
                mapped_xy = (float(mapped[0]), float(mapped[1]))
                inlier_mask_for_draw = inliers.ravel().astype(bool) if inliers is not None else None
            results_label = "fail"

        # ---- (기존) 시각화 ----
        if visualize:
            _draw_vis(name_short, img_s / 255.0, img_b / 255.0, mapped_xy,
                      save_success if results_label == "success" else save_fallback)
            _draw_matches(name_short, img_b, img_s, k0, k1, inlier_mask_for_draw,
                          out_dir=(save_success if results_label == "success" else save_fallback))

            # ---- (신규) full viz 추가 ----
            # Bluebon/ Sentinel 패치를 [0..1], (1,H,W) 텐서로 변환
            B_full = torch.from_numpy((img_b.astype(np.float32) / 255.0))[None, ...]
            S_full = torch.from_numpy((img_s.astype(np.float32) / 255.0))[None, ...]
            # byx=(y,x) = 동적 계산된 중심점, syx=(mapped_y, mapped_x)
            byx = (float(bluebon_center[1]), float(bluebon_center[0]))
            syx = (mapped_xy[1], mapped_xy[0])
            save_png = os.path.join(
                save_success if results_label == "success" else save_fallback,
                f"full_viz_{name_short}.png"
            )
            draw_full_viz_loftr(B_full, S_full, byx, syx, f"{name_short} LoFTR (full scene)", save_png)

        # dx, dy: 패치 내 상대 좌표 차이 (Reference 패치 중심 기준)
        dx = float(mapped_xy[0] - ref_center[0])
        dy = float(mapped_xy[1] - ref_center[1])

        # 아핀행렬 요소(없으면 NaN)
        if M is not None:
            M00, M01, M02 = float(M[0, 0]), float(M[0, 1]), float(M[0, 2])
            M10, M11, M12 = float(M[1, 0]), float(M[1, 1]), float(M[1, 2])
        else:
            M00 = M01 = M02 = M10 = M11 = M12 = np.nan

        # 원래 결과 시트용(row)
        new_rows.append({
            "name": name_short,
            "Bluebon_y": By, "Bluebon_x": Bx,
            f"{ref_label}_y_orig": Sy, f"{ref_label}_x_orig": Sx,
            "dy": dy, "dx": dx,
            f"{ref_label}_y_updated": (None if Sy is None else Sy + dy),
            f"{ref_label}_x_updated": (None if Sx is None else Sx + dx),
            "inliers": nin, "total_matches": N,
            "matching_rate": matching_rate,
            "results": results_label,
            "fail_reason": fail_reason_str,  # << 추가
            "a00": M00, "a01": M01, "a02": M02, "b00": M10, "b01": M11, "b02": M12,
        })

        # ===== 새로 추가: 요약 시트 row =====
        summary_rows.append({
            "name": name_short,
            "Bluebon_y": By, "Bluebon_x": Bx,
            f"{ref_label}_y": (None if Sy is None else Sy + dy),
            f"{ref_label}_x": (None if Sx is None else Sx + dx),
            "dy": dy, "dx": dx,
            "confidence": conf_summary,
            "num_matches": N,
        })

    # 파싱 실패 통계 출력
    if parse_fail_count > 0:
        print(f"\n   ⚠️  파일명 파싱 실패: {parse_fail_count}개")
        if parse_fail_examples:
            print(f"   🔍 파싱 실패 예시 (처음 {len(parse_fail_examples)}개):")
            for example in parse_fail_examples:
                print(f"      • {example}")
            if parse_fail_count > len(parse_fail_examples):
                print(f"      ... 외 {parse_fail_count - len(parse_fail_examples)}개")
    
    print(f"\n   ✅ STEP 13 완료: 성공 {success_count}개, 실패 {fail_count}개, 파싱 실패 {parse_fail_count}개 (전체 {len(common_names)}개)")
    if fail_count > 0:
        print(f"\n   📊 실패 원인 통계:")
        for reason, count in fail_stats.items():
            if count > 0:
                print(f"      {reason}: {count}개")
        
        # 패치별 실패 상세 정보 출력 (처음 20개)
        if fail_details:
            print(f"\n   🔍 패치별 실패 상세 (처음 {len(fail_details)}개):")
            for detail in fail_details:
                print(f"      • {detail['name']}: 매칭점={detail['total_matches']}개, "
                      f"인라이어={detail['inliers']}개, "
                      f"비율={detail['matching_rate']}, "
                      f"사유={detail['reasons']}")
            if fail_count > len(fail_details):
                print(f"      ... 외 {fail_count - len(fail_details)}개 패치 실패")
    
    # --- 결과 저장: XLSX ---
    xlsx_out = os.path.join(save_root, "mapped_xy.xlsx")
    new_df = pd.DataFrame(new_rows)
    final_cols = [
        "name",
        "Bluebon_y", "Bluebon_x",
        f"{ref_label}_y_orig", f"{ref_label}_x_orig",
        "dy", "dx",
        f"{ref_label}_y_updated", f"{ref_label}_x_updated",
        "inliers", "total_matches", "matching_rate", "results",
        "fail_reason",  # << 추가
        "a00", "a01", "a02", "b00", "b01", "b02",
    ]
    for c in final_cols:
        if c not in new_df.columns:
            new_df[c] = np.nan
    new_df = new_df[final_cols]

    # 새 데이터프레임에서 중복 제거 (최신 것만 유지)
    new_df = new_df.drop_duplicates(subset=['name'], keep='last')

    if os.path.exists(xlsx_out):
        old_df = pd.read_excel(xlsx_out, sheet_name='results')
        old_df = old_df.drop_duplicates(subset=['name'], keep='last').set_index("name")
        new_df_idx = new_df.set_index("name")
        old_df.update(new_df_idx)
        merged = pd.concat([old_df, new_df_idx[~new_df_idx.index.isin(old_df.index)]], axis=0).reset_index()
        for c in final_cols:
            if c not in merged.columns:
                merged[c] = np.nan
        merged = merged[final_cols]
    else:
        merged = new_df.copy()

    # ===== 요약 시트 DataFrame 구성 =====
    summary_df = pd.DataFrame(summary_rows)
    summary_cols = ["name", "Bluebon_y", "Bluebon_x", f"{ref_label}_y", f"{ref_label}_x", "dy", "dx", "confidence", "num_matches"]
    for c in summary_cols:
        if c not in summary_df.columns:
            summary_df[c] = np.nan
    summary_df = summary_df.drop_duplicates(subset=['name'], keep='last')
    summary_df = summary_df[summary_cols]

    # FAIL 행의 아핀행렬(M00~M12) 빨간색 칠하기 + 요약 시트 함께 저장
    with pd.ExcelWriter(xlsx_out, engine="openpyxl") as writer:
        merged.to_excel(writer, index=False, sheet_name="results")
        summary_df.to_excel(writer, index=False, sheet_name="summary")

        # 스타일 지정은 results 시트에만
        ws = writer.sheets["results"]
        header = {cell.value: i + 1 for i, cell in enumerate(next(ws.iter_rows(min_row=1, max_row=1)))}
        m_start = header.get("a00"); m_end = header.get("b02")
        results_col = header.get("results")
        if (results_col is not None) and (m_start is not None) and (m_end is not None):
            red_fill = PatternFill(start_color="FFFFCCCC", end_color="FFFFCCCC", fill_type="solid")
            for row_idx in range(2, ws.max_row + 1):
                val = ws.cell(row=row_idx, column=results_col).value
                if str(val).lower() == "fail":
                    for col_idx in range(m_start, m_end + 1):
                        ws.cell(row=row_idx, column=col_idx).fill = red_fill

    # === NPZ 저장 (SUCCESS만) ===
    npz_out = os.path.join(save_root, "stage4_matches.npz")
    cols_needed = ["Bluebon_y", "Bluebon_x", f"{ref_label}_y_updated", f"{ref_label}_x_updated", "results"]
    
    print(f"\n   📊 NPZ 저장 전 필터링 통계:")
    print(f"      - 전체 merged 행: {len(merged)}개")
    print(f"      - results='success'인 행: {len(merged[merged['results'].str.lower() == 'success'])}개")
    
    # NaN 체크
    merged_with_cols = merged[cols_needed]
    nan_counts = merged_with_cols.isna().sum()
    print(f"      - NaN 개수 (dropna 전):")
    for col, count in nan_counts.items():
        if count > 0:
            print(f"         • {col}: {count}개")
    
    valid = merged[cols_needed].dropna()
    print(f"      - dropna() 후 valid 행: {len(valid)}개")
    
    valid_success = valid[valid["results"].str.lower() == "success"]
    print(f"      - valid 중 results='success'인 행: {len(valid_success)}개")
    
    if len(valid) > 0:
        results_counts = valid["results"].value_counts()
        print(f"      - valid의 results 값 분포:")
        for result_val, count in results_counts.items():
            print(f"         • {result_val}: {count}개")
    
    # success이지만 dropna로 제거된 경우 확인
    all_success = merged[merged["results"].str.lower() == "success"]
    removed_success = all_success[all_success[cols_needed].isna().any(axis=1)]
    if len(removed_success) > 0:
        print(f"      ⚠️  경고: {len(removed_success)}개의 success 행이 NaN으로 인해 제거되었습니다!")
        print(f"         제거된 success 행의 NaN 위치:")
        for idx, row in removed_success.head(5).iterrows():
            nan_cols = [col for col in cols_needed if pd.isna(row[col])]
            print(f"         • {row['name']}: {nan_cols}")
        if len(removed_success) > 5:
            print(f"         ... 외 {len(removed_success) - 5}개")
    
    tar_points = valid_success[["Bluebon_y", "Bluebon_x"]].to_numpy(dtype=np.float32) if len(valid_success) > 0 else np.array([], dtype=np.float32).reshape(0, 2)   # (N,2) (y,x)
    ref_points = valid_success[[f"{ref_label}_y_updated", f"{ref_label}_x_updated"]].to_numpy(dtype=np.float32) if len(valid_success) > 0 else np.array([], dtype=np.float32).reshape(0, 2)  # (N,2) (y,x)
    
    print(f"      - 최종 ref_points: {len(ref_points)}개")
    print(f"      - 최종 tar_points: {len(tar_points)}개")
    
    np.savez(npz_out, ref_points=ref_points, tar_points=tar_points)

    # === 전체 매칭 결과 종합 시각화 (기존) ===
    if visualize and len(ref_points) > 0:
        print(f"\n📊 전체 매칭 결과 종합 시각화 중...")
        try:
            tar_path = os.path.join(dir, '.step11_recropped', 'step03_cropped', 'target.tif')
            ref_path = os.path.join(dir, '.step11_recropped', 'step04_normalized', 'reference_normalized.tif')
            if os.path.exists(tar_path) and os.path.exists(ref_path):
                import rasterio, matplotlib.pyplot as plt
                with rasterio.open(ref_path) as src:
                    ref_img = src.read(1).astype(np.float32)
                    ref_img = (ref_img - ref_img.min()) / (ref_img.max() - ref_img.min() + 1e-8)
                with rasterio.open(tar_path) as src:
                    tar_img = src.read(1).astype(np.float32)
                    tar_img = (tar_img - tar_img.min()) / (tar_img.max() - tar_img.min() + 1e-8)
                Hr, Wr = ref_img.shape; Ht, Wt = tar_img.shape
                H = max(Hr, Ht)
                canvas = np.zeros((H, Wr + Wt), dtype=np.float32)
                canvas[:Hr, :Wr] = ref_img
                canvas[:Ht, Wr:Wr + Wt] = tar_img
                fig, ax = plt.subplots(1, 1, figsize=(20, 10))
                ax.imshow(canvas, cmap='gray'); ax.axis('off')
                tar_points_shifted = tar_points.copy(); tar_points_shifted[:, 1] += Wr
                num_to_show = min(500, len(ref_points))
                indices = np.random.choice(len(ref_points), num_to_show, replace=False)
                for i in indices:
                    ref_xy = ref_points[i][::-1]; tar_xy = tar_points_shifted[i][::-1]
                    ax.plot([ref_xy[0], tar_xy[0]], [ref_xy[1], tar_xy[1]], 'g-', linewidth=0.5, alpha=0.6)
                ax.scatter(ref_points[:, 1], ref_points[:, 0], c='red', s=10, alpha=0.8, label='Reference')
                ax.scatter(tar_points_shifted[:, 1], tar_points_shifted[:, 0], c='cyan', s=10, alpha=0.8, label='Target')
                ax.set_title(f'STEP 13: LoFTR 전체 매칭 결과\n총 {len(ref_points)}개 매칭점 (시각화: {num_to_show}개)', fontsize=16, pad=20)
                ax.legend(loc='upper right', fontsize=12)
                summary_path = os.path.join(save_root, "loftr_matching_summary.png")
                plt.savefig(summary_path, dpi=150, bbox_inches='tight', facecolor='white')
                plt.close()
                print(f"   ✅ 전체 매칭 결과 저장: {summary_path}")
                print(f"   📊 총 {len(ref_points)}개 매칭점")
            else:
                print(f"   ⚠️  이미지를 찾을 수 없어 종합 시각화를 건너뜁니다.")
        except Exception as e:
            print(f"   ⚠️  종합 시각화 실패: {e}")

    return {
        "stage4": {
            "ref_points": ref_points,  # (N, 2)
            "tar_points": tar_points,  # (N, 2)
            "num_matches": int(ref_points.shape[0]),
        }
    }

def Step_13_super_light(dir: str, visualize: bool = True, save_npz: bool = True) -> str:
    """
    feature point algorithm + LightGlue 매칭 (1/2 중앙 49 → 원본 49 재매칭)

    - 시각화: visualize=True 시 success/, fail/로 분리 저장 (시작점 + 최종점 표시)
    - npz: save_npz=True 시 모든 패치 결과를 stage4_matches.npz (단일 파일)로 저장
           ref_points = [[Sentinel_y_updated, Sentinel_x_updated], ...]
           tar_points = [[Bluebon_y_updated,  Bluebon_x_updated],  ...]
    - CSV 컬럼(요청 사양):
        name, Bluebon_y, Bluebon_x, Sentinel_y, Sentinel_x,
        Blue_dy, Blue_dx, Sen_dy, Sen_dx,
        dy, dx,
        Bluebon_y_updated, Bluebon_x_updated, Sentinel_y_updated, Sentinel_x_updated,
        confidence, results
    """
    # ---------- 경로 ----------
    bluebon_patches_dir  = os.path.join(dir, 'step12_patches', 'Bluebon_128')
    sentinel_patches_dir = os.path.join(dir, 'step12_patches', 'Sentinel_196')
    assert os.path.isdir(bluebon_patches_dir) and os.path.isdir(sentinel_patches_dir), \
        f"패치 폴더 없음: {bluebon_patches_dir}, {sentinel_patches_dir}"

    out_dir   = os.path.join(dir, "step13_super_light_result"); os.makedirs(out_dir, exist_ok=True)
    succ_dir  = os.path.join(out_dir, "success"); os.makedirs(succ_dir, exist_ok=True)
    fail_dir  = os.path.join(out_dir, "fail");    os.makedirs(fail_dir, exist_ok=True)
    csv_path  = os.path.join(out_dir, "superpoint_lightglue_matching.csv")

    # ---------- 페어링 ----------
    def stem(p): return os.path.splitext(os.path.basename(p))[0]
    # macOS 메타데이터 파일 (._로 시작) 제외
    b_all = [os.path.join(bluebon_patches_dir, f) for f in os.listdir(bluebon_patches_dir)
             if f.lower().endswith(('.tif', '.tiff')) and not f.startswith('._')]
    s_all = [os.path.join(sentinel_patches_dir, f) for f in os.listdir(sentinel_patches_dir)
             if f.lower().endswith(('.tif', '.tiff')) and not f.startswith('._')]
    b_map = {stem(p): p for p in b_all}
    s_map = {stem(p): p for p in s_all}
    common = sorted(set(b_map.keys()) & set(s_map.keys()))
    if not common:
        raise RuntimeError("공통 파일명이 없습니다. 두 폴더의 파일명이 서로 대응되는지 확인하세요.")

    pat = re.compile(
        r'^(?P<name>[^_]+)_Sentinel_(?P<sen_y>-?\d+(?:\.\d+)?)_(?P<sen_x>-?\d+(?:\.\d+)?)_Bluebon_(?P<blue_y>-?\d+(?:\.\d+)?)_(?P<blue_x>-?\d+(?:\.\d+)?)$'
    )
    def parse_meta(st: str):
        m = pat.match(st)
        if not m:
            raise ValueError(f"파일명에서 메타 파싱 실패: {st}")
        d = m.groupdict()
        return (
            d["name"],
            float(d["blue_y"]), float(d["blue_x"]),
            float(d["sen_y"]),  float(d["sen_x"])
        )

    device = "cuda" if torch.cuda.is_available() else "cpu"
    psize  = 49

    header = [
        "name","Bluebon_y","Bluebon_x","Sentinel_y","Sentinel_x",
        "Blue_dy","Blue_dx","Sen_dy","Sen_dx",
        "dy","dx",
        "Bluebon_y_updated","Bluebon_x_updated","Sentinel_y_updated","Sentinel_x_updated",
        "confidence","results"
    ]
    rows = [",".join(header)]

    # npz 단일 저장용 누적 컨테이너
    ref_points_all = []   # [[Sen_y_upd, Sen_x_upd], ...]
    tar_points_all = []   # [[Blu_y_upd, Blu_x_upd], ...]

    # ---------- 메인 루프 ----------
    for i, stem_name in enumerate(common):
        b_path = b_map[stem_name]
        s_path = s_map[stem_name]

        # (0) 메타 파싱 (전체영상 중심점)
        try:
            name, Bluebon_y0, Bluebon_x0, Sentinel_y0, Sentinel_x0 = parse_meta(stem_name)
        except Exception:
            name = stem_name
            Bluebon_y0 = Bluebon_x0 = Sentinel_y0 = Sentinel_x0 = np.nan

        # (1) 전체 패치 로드
        B_full = load_image(b_path)   # [C,H,W] float32 0..1
        S_full = load_image(s_path)
        Bg_full = to_gray01(B_full)   # [1,H,W]
        Sg_full = to_gray01(S_full)

        # (2) 1/2 다운샘플
        Bd = F.interpolate(Bg_full.unsqueeze(0), scale_factor=0.5, mode="bicubic", align_corners=False).squeeze(0)
        Sd = F.interpolate(Sg_full.unsqueeze(0), scale_factor=0.5, mode="bicubic", align_corners=False).squeeze(0)

        # (3) 1/2 중앙 49x49 매칭
        Hd, Wd = Bd.shape[-2], Bd.shape[-1]
        cy_bd, cx_bd = get_center_hw(Hd, Wd)
        cy_sd, cx_sd = get_center_hw(Sd.shape[-2], Sd.shape[-1])
        Bd49, (bd_y0, bd_x0) = crop_center(Bd, cy_bd, cx_bd, psize)
        Sd49, (sd_y0, sd_x0) = crop_center(Sd, cy_sd, cx_sd, psize)

        off1, sc1, dbg1 = run_sp_lg(Bd49, Sd49, device=device)
        score1 = sc1 or 0.0
        dy1_o, dx1_o = (2.0 * off1[0], 2.0 * off1[1]) if off1 is not None else (0.0, 0.0)

        # (4) 원본 재매칭 시작점 (시작점 시각화 포함)
        if off1 is not None and (dbg1 or {}).get("best"):
            k0 = dbg1["best"].get("k0")  # (x,y) in Bd49
            k1 = dbg1["best"].get("k1")  # (x,y) in Sd49
        else:
            k0 = k1 = None

        if (k0 is not None) and (k1 is not None):
            by_d = bd_y0 + float(k0[1]); bx_d = bd_x0 + float(k0[0])
            sy_d = sd_y0 + float(k1[1]); sx_d = sd_x0 + float(k1[0])
            blue_pred_full_init = (2.0 * by_d, 2.0 * bx_d)   # 시작점(Bluebon)
            sent_pred_full_init = (2.0 * sy_d, 2.0 * sx_d)   # 시작점(Sentinel)
        else:
            cy_bf, cx_bf = get_center_hw(Bg_full.shape[-2], Bg_full.shape[-1])
            cy_sf, cx_sf = get_center_hw(Sg_full.shape[-2], Sg_full.shape[-1])
            blue_pred_full_init = (float(cy_bf), float(cx_bf))
            sent_pred_full_init = (float(cy_sf), float(cx_sf))

        # (5) 원본 49x49 재매칭
        Bc_hr, (b_y0, b_x0) = crop_center(Bg_full, blue_pred_full_init[0], blue_pred_full_init[1], psize)
        Sc_hr, (s_y0, s_x0) = crop_center(Sg_full, sent_pred_full_init[0], sent_pred_full_init[1], psize)
        off2, sc2, dbg2 = run_sp_lg(Bc_hr, Sc_hr, device=device)
        score2 = sc2 or 0.0

        # (6) 최종 오프셋 합
        dy2, dx2 = off2 if off2 is not None else (0.0, 0.0)
        dy_sum = dy1_o + dy2
        dx_sum = dx1_o + dx2

        # (7) 시각화용 최종 점
        Hb, Wb = Bg_full.shape[-2], Bg_full.shape[-1]
        Hs, Ws = Sg_full.shape[-2], Sg_full.shape[-1]
        cy_bf, cx_bf = get_center_hw(Hb, Wb)
        cy_sf, cx_sf = get_center_hw(Hs, Ws)
        blue_pt_final = (float(cy_bf), float(cx_bf))  # Bluebon 최종은 항상 중심

        # 성공/실패 판정 및 HR best kp 환산
        if off2 is None or (dbg2 or {}).get("best") is None:
            status = "fail"
            save_dir = fail_dir
            sent_pt_final = None
            blue_best_full_y = blue_best_full_x = np.nan
            sen_best_full_y  = sen_best_full_x  = np.nan
            confidence = 0.0
        else:
            status = "success"
            save_dir = succ_dir
            sent_pt_final = (float(cy_sf + dy_sum), float(cx_sf + dx_sum))
            sent_pt_final = (max(0.0, min(Hs-1.0, sent_pt_final[0])),
                             max(0.0, min(Ws-1.0, sent_pt_final[1])))
            k0_hr = dbg2["best"]["k0"]  # (x,y) in Bc_hr (49x49)
            k1_hr = dbg2["best"]["k1"]  # (x,y) in Sc_hr (49x49)
            confidence = float(dbg2["best"]["score"])
            blue_best_full_y = float(b_y0 + k0_hr[1]); blue_best_full_x = float(b_x0 + k0_hr[0])
            sen_best_full_y  = float(s_y0 + k1_hr[1]); sen_best_full_x  = float(s_x0 + k1_hr[0])

        # (8) 요청 사양의 dy/dx 및 업데이트 좌표 계산
        # Bluebon patch center = (64,64), Sentinel patch center = (96,96)
        Blue_dy = blue_best_full_y - 64.0 if not np.isnan(blue_best_full_y) else np.nan
        Blue_dx = blue_best_full_x - 64.0 if not np.isnan(blue_best_full_x) else np.nan
        Sen_dy  = sen_best_full_y  - 96.0 if not np.isnan(sen_best_full_y)  else np.nan
        Sen_dx  = sen_best_full_x  - 96.0 if not np.isnan(sen_best_full_x)  else np.nan
        dy = (Sen_dy - Blue_dy) if (not np.isnan(Sen_dy) and not np.isnan(Blue_dy)) else np.nan
        dx = (Sen_dx - Blue_dx) if (not np.isnan(Sen_dx) and not np.isnan(Blue_dx)) else np.nan

        Bluebon_y_updated = (Bluebon_y0 + Blue_dy) if (not np.isnan(Bluebon_y0) and not np.isnan(Blue_dy)) else np.nan
        Bluebon_x_updated = (Bluebon_x0 + Blue_dx) if (not np.isnan(Bluebon_x0) and not np.isnan(Blue_dx)) else np.nan
        Sentinel_y_updated = (Sentinel_y0 + Sen_dy) if (not np.isnan(Sentinel_y0) and not np.isnan(Sen_dy)) else np.nan
        Sentinel_x_updated = (Sentinel_x0 + Sen_dx) if (not np.isnan(Sentinel_x0) and not np.isnan(Sen_dx)) else np.nan

        # (9) 시각화
        if visualize:
            if status == "success":
                byx_init_for_draw = blue_pred_full_init
                syx_init_for_draw = sent_pred_full_init
                byx_final_for_draw = blue_pt_final
                syx_final_for_draw = sent_pt_final
            else:
                # fail이면 어떤 점도 표시하지 않음
                byx_init_for_draw = None
                syx_init_for_draw = None
                byx_final_for_draw = None
                syx_final_for_draw = None

            draw_full_viz(
                Bg_full, Sg_full,
                byx_final=byx_final_for_draw,
                syx_final=syx_final_for_draw,
                title=f"Superpoint+LightGlue [{status}]",
                save_path=os.path.join(save_dir, f"{name if name else stem_name}_Full_{i:04d}.png"),
                byx_init=byx_init_for_draw,
                syx_init=syx_init_for_draw
            )

        # (10) npz 단일 저장용 누적
        if save_npz and not (np.isnan(Sentinel_y_updated) or np.isnan(Bluebon_y_updated)):
            ref_points_all.append([Sentinel_y_updated, Sentinel_x_updated])
            tar_points_all.append([Bluebon_y_updated,  Bluebon_x_updated])

        # (11) CSV
        values = [
            name,
            f"{Bluebon_y0:.8f}" if not np.isnan(Bluebon_y0) else "",
            f"{Bluebon_x0:.8f}" if not np.isnan(Bluebon_x0) else "",
            f"{Sentinel_y0:.8f}" if not np.isnan(Sentinel_y0) else "",
            f"{Sentinel_x0:.8f}" if not np.isnan(Sentinel_x0) else "",
            f"{Blue_dy:.8f}" if not np.isnan(Blue_dy) else "",
            f"{Blue_dx:.8f}" if not np.isnan(Blue_dx) else "",
            f"{Sen_dy:.8f}" if not np.isnan(Sen_dy) else "",
            f"{Sen_dx:.8f}" if not np.isnan(Sen_dx) else "",
            f"{dy:.8f}" if not np.isnan(dy) else "",
            f"{dx:.8f}" if not np.isnan(dx) else "",
            f"{Bluebon_y_updated:.8f}" if not np.isnan(Bluebon_y_updated) else "",
            f"{Bluebon_x_updated:.8f}" if not np.isnan(Bluebon_x_updated) else "",
            f"{Sentinel_y_updated:.8f}" if not np.isnan(Sentinel_y_updated) else "",
            f"{Sentinel_x_updated:.8f}" if not np.isnan(Sentinel_x_updated) else "",
            f"{confidence:.6f}",
            status
        ]
        rows.append(",".join(values))

    # ---------- npz 단일 저장 ----------
    npz_path = None
    if save_npz and len(ref_points_all) > 0:
        ref_points_all = np.array(ref_points_all, dtype=np.float32)
        tar_points_all = np.array(tar_points_all, dtype=np.float32)
        npz_path = os.path.join(out_dir, "stage4_matches.npz")
        np.savez(
            npz_path,
            ref_points=ref_points_all,
            tar_points=tar_points_all
        )
        print(f"[NPZ 저장 완료] {len(ref_points_all)}개 매칭점 → {npz_path}")

    # ---------- CSV 저장 ----------
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write("\n".join(rows))

    print(f"[Step_13_super_light] 완료: {csv_path}\n시각화 폴더: {succ_dir}, {fail_dir}")

    # ---------- return 값 변경 ----------
    if npz_path is not None:
        data = np.load(npz_path)
        result = {
            "stage4": {
                "ref_points": data["ref_points"],
                "tar_points": data["tar_points"],
                "num_matches": len(data["ref_points"]),
            }
        }
        data.close()
        return result
    else:
        return {"stage4": {"ref_points": None, "tar_points": None, "num_matches": 0}}

def to_gray01(img: torch.Tensor) -> torch.Tensor:
    """
    (C,H,W) -> (1,H,W) 로 변환하고 패치별 min-max 정규화 [0,1]
    """
    assert img.ndim == 3, "to_gray01 expects (C,H,W)"
    x = img.mean(dim=0, keepdim=True) if img.shape[0] > 1 else img
    x_min = x.amin(dim=(-2, -1), keepdim=True)
    x_max = x.amax(dim=(-2, -1), keepdim=True)
    return ((x - x_min) / (x_max - x_min + 1e-6)).clamp(0, 1)

def get_center_hw(H: int, W: int):
    cy0 = H // 2
    cx0 = W // 2
    return cy0, cx0

def crop_center(img: torch.Tensor, cy: float, cx: float, size: int):
    # img: (1,H,W), size: odd(예 49)
    C, H, W = img.shape
    assert C == 1, "crop_center expects (1,H,W)"
    half = size // 2
    x0 = int(round(cx)) - half
    y0 = int(round(cy)) - half
    x0 = max(0, min(W - size, x0))
    y0 = max(0, min(H - size, y0))
    return img[:, y0:y0+size, x0:x0+size], (y0, x0)

def _squeeze_feat_dict(feats: dict) -> dict:
    out = {}
    for k, v in feats.items():
        if isinstance(v, torch.Tensor) and v.dim() >= 2 and v.size(0) == 1:
            out[k] = v.squeeze(0)
        else:
            out[k] = v
    return out

def _to_tensor_2d(x):
    # matches -> (N,2) tensor
    if x is None:
        return None
    if isinstance(x, torch.Tensor):
        t = x
        if t.dim() == 3 and t.size(0) == 1:
            t = t.squeeze(0)
        if t.dim() == 1 and t.numel() == 0:
            return torch.empty(0, 2, dtype=t.dtype, device=t.device)
        return t
    if isinstance(x, np.ndarray):
        t = torch.from_numpy(x)
        if t.dim() == 3 and t.size(0) == 1:
            t = t.squeeze(0)
        return t
    if isinstance(x, list):
        if len(x) == 0:
            return torch.empty(0, 2)
        if isinstance(x[0], torch.Tensor):
            t = x[0]
            if t.dim() == 3 and t.size(0) == 1:
                t = t.squeeze(0)
            return t
        t = torch.as_tensor(x)
        if t.dim() == 3 and t.size(0) == 1:
            t = t.squeeze(0)
        return t
    return None

def _to_tensor_1d(x, length_hint=None):
    # scores -> (N,) tensor
    if x is None:
        return None
    if isinstance(x, torch.Tensor):
        t = x
        if t.dim() == 2 and t.size(0) == 1:
            t = t.squeeze(0)
        return t
    if isinstance(x, np.ndarray):
        t = torch.from_numpy(x)
        if t.ndim == 2 and t.shape[0] == 1:
            t = t.squeeze(0)
        return t
    if isinstance(x, list):
        if len(x) == 0:
            return torch.empty(0)
        if isinstance(x[0], torch.Tensor):
            t = x[0]
            if t.dim() == 2 and t.size(0) == 1:
                t = t.squeeze(0)
            return t
        return torch.as_tensor(x, dtype=torch.float32)
    if length_hint is not None:
        return torch.ones(length_hint, dtype=torch.float32)
    return None

def run_sift_matching(img_b: np.ndarray,
                      img_s: np.ndarray,
                      sift_detector,
                      matcher,
                      ratio_thresh: float = 0.75):
    """
    OpenCV SIFT 기반 매칭 수행.
    Args:
        img_b, img_s: uint8 Grayscale 이미지 (Bluebon, Sentinel)
        sift_detector: cv2.SIFT_create() 객체
        matcher: cv2.BFMatcher (L2)
        ratio_thresh: Lowe ratio test threshold
    Returns:
        k0 (np.ndarray, Nx2), k1 (np.ndarray, Nx2), conf (np.ndarray or None)
    """
    if sift_detector is None or matcher is None:
        return np.empty((0, 2), dtype=np.float32), np.empty((0, 2), dtype=np.float32), None

    kp0, desc0 = sift_detector.detectAndCompute(img_b, None)
    kp1, desc1 = sift_detector.detectAndCompute(img_s, None)

    if desc0 is None or desc1 is None or len(kp0) == 0 or len(kp1) == 0:
        return np.empty((0, 2), dtype=np.float32), np.empty((0, 2), dtype=np.float32), None

    raw_matches = matcher.knnMatch(desc0, desc1, k=2)
    good_matches = []
    for pair in raw_matches:
        if len(pair) < 2:
            continue
        m, n = pair
        if m.distance < ratio_thresh * n.distance:
            good_matches.append(m)

    if len(good_matches) == 0:
        return np.empty((0, 2), dtype=np.float32), np.empty((0, 2), dtype=np.float32), None

    pts0 = np.array([kp0[m.queryIdx].pt for m in good_matches], dtype=np.float32)
    pts1 = np.array([kp1[m.trainIdx].pt for m in good_matches], dtype=np.float32)

    distances = np.array([m.distance for m in good_matches], dtype=np.float32)
    max_dist = float(distances.max()) if distances.size > 0 else 1.0
    conf = 1.0 - distances / (max_dist + 1e-6)

    return pts0, pts1, conf

def run_sp_lg(img0: torch.Tensor, img1: torch.Tensor, device="cuda"):
    """
    img0, img1: (1,h,w) [0,1]
    return: (dy,dx), best_score, dbg ; 실패 시 (None, 0.0, dbg)
    dbg["best"] = {"k0": (x,y), "k1": (x,y), "score": float}
    """
    extractor = SuperPoint(max_num_keypoints=2048).eval().to(device)
    matcher   = LightGlue(features='superpoint').eval().to(device)

    with torch.no_grad():
        f0 = extractor.extract(img0.to(device))
        f1 = extractor.extract(img1.to(device))
        out = matcher({"image0": f0, "image1": f1})

    f0_ = {k: (v.detach().cpu() if isinstance(v, torch.Tensor) else v) for k, v in f0.items()}
    f1_ = {k: (v.detach().cpu() if isinstance(v, torch.Tensor) else v) for k, v in f1.items()}
    out_= {k: (v.detach().cpu() if isinstance(v, torch.Tensor) else v) for k, v in out.items()}
    f0_ = _squeeze_feat_dict(f0_); f1_ = _squeeze_feat_dict(f1_)

    m = _to_tensor_2d(out_.get("matches", None))
    if m is None or m.numel() == 0 or m.dim() != 2 or m.size(-1) != 2:
        return None, 0.0, {"f0": f0_, "f1": f1_, "out": out_}

    valid = (m[:, 0] >= 0) & (m[:, 1] >= 0)
    m = m[valid]
    if m.numel() == 0:
        return None, 0.0, {"f0": f0_, "f1": f1_, "out": out_}

    scores = _to_tensor_1d(out_.get("scores", None))
    if (scores is None) or (scores.numel() != valid.sum().item()):
        k0s = _to_tensor_1d(f0_.get("keypoint_scores", None), length_hint=f0_["keypoints"].shape[0])
        k1s = _to_tensor_1d(f1_.get("keypoint_scores", None), length_hint=f1_["keypoints"].shape[0])
        scores = k0s[m[:, 0].long()] * k1s[m[:, 1].long()]
    else:
        scores = scores[valid]

    best_i = torch.argmax(scores)
    idx0   = m[best_i, 0].long()
    idx1   = m[best_i, 1].long()

    kp0 = f0_["keypoints"]  # (N,2) (x,y)
    kp1 = f1_["keypoints"]
    if kp0.dim() != 2 or kp1.dim() != 2:
        return None, 0.0, {"f0": f0_, "f1": f1_, "out": out_}

    if not (0 <= idx0.item() < kp0.shape[0]) or not (0 <= idx1.item() < kp1.shape[0]):
        return None, 0.0, {"f0": f0_, "f1": f1_, "out": out_}

    k0 = kp0[idx0]  # (x,y)
    k1 = kp1[idx1]
    dx = float(k1[0] - k0[0])
    dy = float(k1[1] - k0[1])
    best_score = float(scores[best_i])

    dbg = {"f0": f0_, "f1": f1_, "out": out_, "best": {"k0": k0.numpy(), "k1": k1.numpy(), "score": best_score}}
    return (dy, dx), best_score, dbg

def draw_full_viz(full_b, full_s, byx_final, syx_final, title, save_path, byx_init=None, syx_init=None):
    """
    최종점(byx_final, syx_final)과 '처음 재매칭 시작점'(byx_init, syx_init)을 함께 그린다.
      - Bluebon: 최종점 = 항상 중심, 보조로 시작점 표시
      - Sentinel: 최종점 = 중심 + (dy_sum,dx_sum), 보조로 시작점 표시
    """
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    def _to_np1hw(x):
        if isinstance(x, torch.Tensor):
            x = x.detach().cpu().numpy()
        x = np.asarray(x)
        if x.ndim == 3 and x.shape[0] == 1:
            return x[0]
        elif x.ndim == 2:
            return x
        else:
            raise ValueError(f"Expected (1,H,W) or (H,W), got shape {x.shape}")

    b_np = _to_np1hw(full_b)
    s_np = _to_np1hw(full_s)

    Hb, Wb = b_np.shape
    Hs, Ws = s_np.shape

    fig = plt.figure(figsize=(10, 4.5))
    gs = fig.add_gridspec(1, 2, width_ratios=[Ws, Wb], wspace=0.05)

    # Sentinel (좌)
    ax0 = fig.add_subplot(gs[0])
    ax0.imshow(s_np, cmap="gray", vmin=0, vmax=1)
    ax0.set_xlim(0, Ws); ax0.set_ylim(Hs, 0)
    ax0.set_box_aspect(Hs / Ws)
    ax0.set_title(title + " - Sentinel")
    ax0.axis("off")
    if syx_final is not None:
        syf, sxf = syx_final
        ax0.scatter([sxf], [syf], s=12, marker='o', color='r')
    if syx_init is not None:
        sy0, sx0 = syx_init
        ax0.scatter([sx0], [sy0], s=12, marker='+', color='b')   # 시작점 (파란색)

    # Bluebon (우)
    ax1 = fig.add_subplot(gs[1])
    ax1.imshow(b_np, cmap="gray", vmin=0, vmax=1)
    ax1.set_xlim(0, Wb); ax1.set_ylim(Hb, 0)
    ax1.set_box_aspect(Hb / Wb)
    ax1.set_title(title + " - Bluebon")
    ax1.axis("off")
    if byx_final is not None:
        byf, bxf = byx_final
        ax1.scatter([bxf], [byf], s=12, marker='o', color='r')
    if byx_init is not None:
        by0, bx0 = byx_init
        ax1.scatter([bx0], [by0], s=12, marker='+', color='b')   # 시작점 (파란색)


    plt.tight_layout()
    plt.savefig(save_path, dpi=220, bbox_inches="tight")
    plt.close(fig)

def Step_13_RoMaV2(dir: str,
                    inlier_min_count: int = 100,
                    visualize: bool = True,
                    target_resolution: float = None,
                    match_rate_thresh: float = 0.8,
                    num_corresp: int = 2000,
                    batch_size: int = 4,
                    setting: str = "fast"):
    """
    RoMaV2 기반 정밀 패치 매칭 (STEP 13)

    LoFTR와 동일한 입출력 포맷(xlsx, npz)을 사용하며,
    MPS(Apple Silicon) / CUDA / CPU 를 자동 감지합니다.

    Args:
        dir              : 작업 루트 디렉토리 (OUTPUT_DIR)
        inlier_min_count : GCP chip 모드에서 성공 판단 최소 inlier 수 (기본 100)
        visualize        : True이면 PNG 시각화 저장
        target_resolution: Target 해상도 (m) - 조건부 판단용
        match_rate_thresh: 매칭률 임계값 (기본 0.8)
        num_corresp      : RoMaV2 sample()에서 샘플링할 대응점 수 (기본 500)
        batch_size       : 한 번에 처리할 패치 쌍의 수 (기본 4)
        setting          : RoMaV2 추론 설정 ('turbo'|'fast'|'base'|'precise', 기본 'precise')
    """
    try:
        import sys as _sys
        import importlib.util as _ilu
        # RoMaV2 패키지 임포트 (geo_romav2 환경 또는 설치된 경우)
        romav2_src = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            '..', '..', '..', '..', '..', 'RoMaV2', 'src'
        )
        romav2_src = os.path.normpath(romav2_src)
        if romav2_src not in _sys.path:
            _sys.path.insert(0, romav2_src)
        from romav2 import RoMaV2
        from romav2.device import device as romav2_device
    except ImportError as _ie:
        raise ImportError(
            "RoMaV2를 임포트할 수 없습니다. "
            "geo_romav2 conda 환경을 활성화하거나 "
            "'pip install -e <RoMaV2경로>'를 실행하세요.\n"
            f"원인: {_ie}"
        )

    import torch
    import torch.nn.functional as _F

    # RoMaV2 필수 설정
    torch.set_float32_matmul_precision("highest")

    # --- 경로 설정 (Step_13_LoFTR와 동일) ---
    B_dir = os.path.join(dir, '04_patches', "Bluebon_128")
    gcp_chip_dir = os.path.join(dir, '04_patches', "GCPChip_224")
    sentinel_dir = os.path.join(dir, '04_patches', "Sentinel_196")

    if os.path.exists(gcp_chip_dir):
        S_dir = gcp_chip_dir
        use_gcp_chip_mode = True
    else:
        S_dir = sentinel_dir
        use_gcp_chip_mode = False

    save_root = os.path.join(dir, '05_ROMAV2_result')
    save_success = os.path.join(save_root, 'success')
    save_fallback = os.path.join(save_root, 'fail')
    os.makedirs(save_success, exist_ok=True)
    os.makedirs(save_fallback, exist_ok=True)

    # --- 파일명 패턴 (Step_13_LoFTR와 동일) ---
    if use_gcp_chip_mode:
        pat_gcp = re.compile(
            r"(?:patch\d+_)?GCPChip_(?P<Sy>-?\d+(?:\.\d+)?)_(?P<Sx>-?\d+(?:\.\d+)?)_Bluebon_(?P<By>-?\d+(?:\.\d+)?)_(?P<Bx>-?\d+(?:\.\d+)?)",
            re.IGNORECASE
        )
        pat_sentinel = re.compile(
            r"(?:patch\d+_)?Sentinel_(?P<Sy>-?\d+(?:\.\d+)?)_(?P<Sx>-?\d+(?:\.\d+)?)_Bluebon_(?P<By>-?\d+(?:\.\d+)?)_(?P<Bx>-?\d+(?:\.\d+)?)",
            re.IGNORECASE
        )
        ref_label = "GcpChip"
    else:
        pat_sentinel = re.compile(
            r"(?:patch\d+_)?Sentinel_(?P<Sy>-?\d+(?:\.\d+)?)_(?P<Sx>-?\d+(?:\.\d+)?)_Bluebon_(?P<By>-?\d+(?:\.\d+)?)_(?P<Bx>-?\d+(?:\.\d+)?)",
            re.IGNORECASE
        )
        pat_gcp = None
        ref_label = "Sentinel"

    def parse_coords_from_name(long_name):
        if use_gcp_chip_mode and pat_gcp is not None:
            m = pat_gcp.search(long_name)
            if m:
                return float(m.group("By")), float(m.group("Bx")), float(m.group("Sy")), float(m.group("Sx"))
            m = pat_sentinel.search(long_name)
            if m:
                return float(m.group("By")), float(m.group("Bx")), float(m.group("Sy")), float(m.group("Sx"))
        else:
            m = pat_sentinel.search(long_name)
            if m:
                return float(m.group("By")), float(m.group("Bx")), float(m.group("Sy")), float(m.group("Sx"))
        return None, None, None, None

    short_pat = re.compile(r"^(patch\d+)", re.IGNORECASE)
    def short_name_of(filename):
        base = os.path.splitext(filename)[0]
        m = short_pat.match(base)
        return m.group(1) if m else base

    # --- 공통 파일 목록 ---
    b_names = {fn for fn in os.listdir(B_dir)
               if fn.lower().endswith('.tif') and not fn.startswith('._')}
    s_names = {fn for fn in os.listdir(S_dir)
               if fn.lower().endswith('.tif') and not fn.startswith('._')}
    common_names = sorted(b_names & s_names)
    
    # ROI (Center Extract) 정보를 가져오기 위해 CSV 로드
    csv_final_path = os.path.join(dir, '04_patches', "keypoints_final.csv")
    roi_info = {}
    if os.path.exists(csv_final_path):
        import pandas as pd
        try:
            df = pd.read_csv(csv_final_path)
            for _, row in df.iterrows():
                b_path = row.get('bluebon_patch_path', '')
                if pd.notna(b_path):
                    b_name = os.path.basename(b_path)
                    roi_info[b_name] = {
                        'B_patch_size_roi': row.get('B_patch_size_roi', 128),
                        'S_patch_size_roi': row.get('S_patch_size_roi', 196) # 기본값
                    }
        except Exception as e:
            print(f"   ⚠️ ROI 정보 로드 실패: {e}")

    if not common_names:
        print(f"   ⚠️ 매칭할 패치 파일을 찾을 수 없습니다.")
        return {
            "stage4": {
                "ref_points": np.empty((0, 2), dtype=np.float32),
                "tar_points": np.empty((0, 2), dtype=np.float32),
                "num_matches": 0,
            }
        }

    # --- RoMaV2 모델 로드 (CUDA/MPS/CPU 자동 감지) ---
    _use_compile = False  # torch.compile() 비활성화: triton cuda.h 의존성 제거
    # Flash/MemEfficient SDPA도 비활성화 → triton launcher 컴파일 방지
    if str(romav2_device) == "cuda":
        torch.backends.cuda.enable_flash_sdp(False)        # triton JIT 컴파일 방지
        torch.backends.cuda.enable_mem_efficient_sdp(True) # cuDNN 기반, triton 불필요
        torch.backends.cuda.enable_math_sdp(True)
    print(f"   🔄 RoMaV2 모델 로드 중 (device={romav2_device}, setting={setting}, compile={_use_compile})...")
    romav2_cfg = RoMaV2.Cfg(
        setting=setting,
        compile=_use_compile,
    )
    matcher = RoMaV2(cfg=romav2_cfg)
    matcher.eval()
    print(f"   ✅ RoMaV2 준비 완료 (device={romav2_device})")

    # --- 성공/실패 조건 ---
    print(f'====실패(FAIL) 기준====')
    print(f'  1. 변환계수 추정 실패')
    print(f'  2. 인라이어 개수 < 10')
    print(f'  3. 인라이어 비율 < match_rate_thresh (현재 {match_rate_thresh})')
    print(f'\n   📊 처리할 패치: {len(common_names)}개 (배치 크기: {batch_size})')

    # --- 누적 결과 ---
    new_rows = []
    summary_rows = []
    success_count = 0
    fail_count = 0
    parse_fail_count = 0
    parse_fail_examples = []

    # ============================================================== #
    #  GPU 최적화된 배치 처리 루프                                     #
    #  전략: ThreadPoolExecutor 이미지 프리패치 → 연속 GPU 추론        #
    #        → ThreadPoolExecutor RANSAC/후처리 비동기 처리            #
    # ============================================================== #
    import concurrent.futures as _cf

    # ── 이미지 1쌍 로드 함수 (CPU I/O, 스레드에서 실행) ──────────────
    def _stretch_contrast(img: np.ndarray) -> np.ndarray:
        lo, hi = np.percentile(img, 2), np.percentile(img, 98)
        if hi > lo:
            return np.clip((img.astype(np.float32) - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
        return img

    def _load_pair(long_name):
        img_b_path = os.path.join(B_dir, long_name)
        img_s_path = os.path.join(S_dir, long_name)
        if not os.path.exists(img_b_path) or not os.path.exists(img_s_path):
            return None, None, long_name
        img_b_gray = cv2.imread(img_b_path, cv2.IMREAD_GRAYSCALE)
        img_s_gray = cv2.imread(img_s_path, cv2.IMREAD_GRAYSCALE)
        if img_b_gray is None or img_s_gray is None:
            return None, None, long_name
        img_b_gray = _stretch_contrast(img_b_gray)
        img_s_gray = _stretch_contrast(img_s_gray)
        return (np.stack([img_b_gray] * 3, axis=-1),
                np.stack([img_s_gray] * 3, axis=-1),
                long_name)

    # ── RANSAC + 결과 정리 함수 (CPU, 스레드에서 실행) ───────────────
    def _process_matches(item):
        long_name, img_b_gray, img_s_gray, k0, k1, conf_np = item
        name_short = short_name_of(long_name)
        By, Bx, Sy, Sx = parse_coords_from_name(long_name)
        if By is None:
            return None

        H_b, W_b = img_b_gray.shape
        H_s, W_s = img_s_gray.shape
        bluebon_center = np.array([W_b / 2.0, H_b / 2.0], dtype=np.float32)
        ref_center     = np.array([W_s / 2.0, H_s / 2.0], dtype=np.float32)

        N = int(k0.shape[0])
        mapped_xy = (ref_center[0], ref_center[1])
        nin = 0
        matching_rate = 0.0
        M = None
        inlier_mask_for_draw = None

        if N >= 3:
            M_est, inliers = cv2.estimateAffinePartial2D(
                k0.astype(np.float32), k1.astype(np.float32),
                method=cv2.RANSAC, ransacReprojThreshold=3.0,
                maxIters=2000, confidence=0.999
            )
            nin = int(inliers.sum()) if inliers is not None else 0
            matching_rate = float(nin) / float(N) if N > 0 else 0.0
        else:
            M_est, inliers = None, None

        fail_reasons = []
        if nin < 10:
            fail_reasons.append(f"LOW_INLIER_COUNT(nin={nin}<10)")
        if matching_rate < match_rate_thresh:
            fail_reasons.append(
                f"LOW_INLIER_RATIO(rate={matching_rate:.3f}<{match_rate_thresh})"
            )
        if M_est is None:
            fail_reasons.append("AFFINE_EST_FAIL")
        is_fail = (len(fail_reasons) > 0)

        conf_summary = (
            float(np.mean(conf_np[inliers.ravel().astype(bool)])) if (
                conf_np is not None and N > 0 and inliers is not None and nin > 0
            ) else float(matching_rate)
        )

        fail_reason_str = ""
        if not is_fail and M_est is not None:
            M = M_est
            inlier_mask_for_draw = inliers.ravel().astype(bool) if inliers is not None else None
            pt = np.array([[bluebon_center]], dtype=np.float32)
            mapped_xy = tuple(cv2.transform(pt, M)[0, 0].tolist())
            results_label = "success"
        else:
            fail_reason_str = "; ".join(fail_reasons) if fail_reasons else "UNKNOWN_FAIL"
            if N >= 1:
                j = int(np.linalg.norm(k0 - bluebon_center, axis=1).argmin())
                mapped_xy = (float(k1[j, 0]), float(k1[j, 1]))
                inlier_mask_for_draw = inliers.ravel().astype(bool) if inliers is not None else None
            results_label = "fail"

        dx = float(mapped_xy[0] - ref_center[0])
        dy = float(mapped_xy[1] - ref_center[1])

        if M is not None:
            M00, M01, M02 = float(M[0, 0]), float(M[0, 1]), float(M[0, 2])
            M10, M11, M12 = float(M[1, 0]), float(M[1, 1]), float(M[1, 2])
        else:
            M00 = M01 = M02 = M10 = M11 = M12 = np.nan

        return {
            "new_row": {
                "name": name_short,
                "Bluebon_y": By, "Bluebon_x": Bx,
                f"{ref_label}_y_orig": Sy, f"{ref_label}_x_orig": Sx,
                "dy": dy, "dx": dx,
                f"{ref_label}_y_updated": (None if Sy is None else Sy + dy),
                f"{ref_label}_x_updated": (None if Sx is None else Sx + dx),
                "inliers": nin, "total_matches": N,
                "matching_rate": matching_rate,
                "results": results_label,
                "fail_reason": fail_reason_str,
                "a00": M00, "a01": M01, "a02": M02,
                "b00": M10, "b01": M11, "b02": M12,
            },
            "summary_row": {
                "name": name_short,
                "Bluebon_y": By, "Bluebon_x": Bx,
                f"{ref_label}_y": (None if Sy is None else Sy + dy),
                f"{ref_label}_x": (None if Sx is None else Sx + dx),
                "dy": dy, "dx": dx,
                "confidence": conf_summary,
                "num_matches": N,
            },
            "success": results_label == "success",
            "img_b_gray": img_b_gray, "img_s_gray": img_s_gray,
            "k0": k0, "k1": k1, "inlier_mask_for_draw": inlier_mask_for_draw,
            "nin": nin, "N": N, "matching_rate": matching_rate,
            "mapped_xy": mapped_xy, "name_short": name_short,
        }

    def _render_viz(result, save_success, save_fallback):
        """비동기 시각화 저장 (호출 측에서 예외 무시 OK)"""
        out_dir_png = save_success if result["success"] else save_fallback
        img_b_gray = result["img_b_gray"]
        img_s_gray = result["img_s_gray"]
        k0_r = result["k0"]; k1_r = result["k1"]
        nin_r = result["nin"]; N_r = result["N"]
        mr_r = result["matching_rate"]
        inlier_mask_r = result["inlier_mask_for_draw"]
        name_short_r = result["name_short"]
        mapped_xy_r = result["mapped_xy"]
        try:
            Hb2, Wb2 = img_b_gray.shape; Hs2, Ws2 = img_s_gray.shape
            canvas = np.zeros((max(Hb2, Hs2), Wb2 + Ws2), dtype=np.float32)
            canvas[:Hb2, :Wb2] = img_b_gray / 255.0
            canvas[:Hs2, Wb2:Wb2 + Ws2] = img_s_gray / 255.0
            fig_v, ax_v = plt.subplots(1, 1, figsize=(10, 5))
            ax_v.imshow(canvas, cmap='gray'); ax_v.axis('off')
            if N_r > 0 and inlier_mask_r is not None:
                k1_shift = k1_r.copy(); k1_shift[:, 0] += Wb2
                for p0, p1 in zip(k0_r[inlier_mask_r], k1_shift[inlier_mask_r]):
                    ax_v.plot([p0[0], p1[0]], [p0[1], p1[1]], 'g-', lw=0.8, alpha=0.7)
                ax_v.scatter(k0_r[inlier_mask_r, 0], k0_r[inlier_mask_r, 1], s=10, c='lime', alpha=0.8)
                ax_v.scatter(k1_shift[inlier_mask_r, 0], k1_shift[inlier_mask_r, 1], s=10, c='lime', alpha=0.8)
            ax_v.set_title(f"RoMaV2 — inliers {nin_r}/{N_r} ({mr_r*100:.1f}%)\n{name_short_r}")
            os.makedirs(out_dir_png, exist_ok=True)
            plt.savefig(os.path.join(out_dir_png, f"romav2_matches_{name_short_r}.png"),
                        dpi=150, bbox_inches="tight")
            plt.close(fig_v)
        except Exception:
            pass
        try:
            bc = np.array([img_b_gray.shape[1] / 2.0, img_b_gray.shape[0] / 2.0], dtype=np.float32)
            B_full = torch.from_numpy((img_b_gray.astype(np.float32)/255.0))[None, ...]
            S_full = torch.from_numpy((img_s_gray.astype(np.float32)/255.0))[None, ...]
            save_png = os.path.join(out_dir_png, f"full_viz_{name_short_r}.png")
            draw_full_viz(B_full, S_full, (float(bc[1]), float(bc[0])),
                          (mapped_xy_r[1], mapped_xy_r[0]),
                          f"{name_short_r} RoMaV2 (full scene)", save_png)
        except Exception:
            pass

    # ── 파이프라인 실행 ──────────────────────────────────────────────
    _n_io_workers   = min(4, batch_size)  # I/O 프리패치 스레드 수
    _n_post_workers = min(4, batch_size)  # RANSAC 후처리 스레드 수
    global_idx = 0
    all_batches = [common_names[i:i + batch_size]
                   for i in range(0, len(common_names), batch_size)]

    with _cf.ThreadPoolExecutor(max_workers=_n_io_workers) as io_pool, \
         _cf.ThreadPoolExecutor(max_workers=_n_post_workers) as post_pool:

        # 첫 배치 프리패치 시작
        prefetch_futs = {io_pool.submit(_load_pair, n): n
                         for n in (all_batches[0] if all_batches else [])}
        postproc_futs = []  # RANSAC 처리 중인 future 목록

        for batch_idx, batch in enumerate(all_batches):
            # ── 현재 배치 로드 완료 대기 ─────────────────────────────
            loaded = {}
            for fut in _cf.as_completed(prefetch_futs):
                ib, is_, ln = fut.result()
                loaded[ln] = (ib, is_)

            # ── 다음 배치 프리패치 (GPU 추론과 병렬) ─────────────────
            if batch_idx + 1 < len(all_batches):
                prefetch_futs = {io_pool.submit(_load_pair, n): n
                                 for n in all_batches[batch_idx + 1]}
            else:
                prefetch_futs = {}

            # ── GPU 연속 추론 ─────────────────────────────────────────
            for long_name in batch:
                global_idx += 1
                if global_idx % 10 == 0:
                    print(f"   진행: {global_idx}/{len(common_names)} "
                          f"(성공: {success_count}, 실패: {fail_count})")

                By, Bx, Sy, Sx = parse_coords_from_name(long_name)
                if By is None:
                    parse_fail_count += 1
                    if parse_fail_count <= 5:
                        parse_fail_examples.append(long_name)
                    continue

                img_b_rgb, img_s_rgb = loaded.get(long_name, (None, None))
                if img_b_rgb is None:
                    print(f"[warn] 이미지 로드 실패: {long_name}")
                    fail_count += 1
                    continue

                H_b, W_b = img_b_rgb.shape[:2]
                H_s, W_s = img_s_rgb.shape[:2]
                bluebon_center = np.array([W_b / 2.0, H_b / 2.0], dtype=np.float32)
                ref_center     = np.array([W_s / 2.0, H_s / 2.0], dtype=np.float32)

                # ── RoMaV2 GPU 추론 ─────────────────────────────────
                k0 = np.empty((0, 2), dtype=np.float32)
                k1 = np.empty((0, 2), dtype=np.float32)
                conf_np = None
                try:
                    with torch.inference_mode():
                        preds = matcher.match(img_b_rgb, img_s_rgb)

                    actual_corresp = min(num_corresp,
                                         max(1, int(preds["overlap_AB"].sum().item())))
                    try:
                        matches, confidence, _, _ = matcher.sample(preds, num_corresp=actual_corresp)
                    except Exception:
                        matches, confidence, _, _ = matcher.sample(
                            preds, num_corresp=min(10, actual_corresp))

                    # preds는 더 이상 필요 없으므로 즉시 해제 (MPS 메모리 반환)
                    del preds

                    pts_b_px, pts_s_px = RoMaV2.to_pixel_coordinates(
                        matches, H_b, W_b, H_s, W_s)

                    # ── GPU 텐서 상태로 ROI 필터링/정렬 (cpu() 동기화 최소화) ──
                    _dev = pts_b_px.device
                    _bc = torch.tensor([W_b / 2.0, H_b / 2.0], device=_dev)
                    _rc = torch.tensor([W_s / 2.0, H_s / 2.0], device=_dev)
                    _max_half = 100.0

                    _mask_b = ((pts_b_px - _bc).abs().max(dim=1).values <= _max_half)
                    _mask_s = ((pts_s_px - _rc).abs().max(dim=1).values <= _max_half)
                    _valid  = _mask_b & _mask_s

                    pts_b_px  = pts_b_px[_valid]
                    pts_s_px  = pts_s_px[_valid]
                    confidence = confidence[_valid]

                    if pts_b_px.shape[0] > 0:
                        _dist     = (pts_b_px - _bc).norm(dim=1)
                        _top50    = _dist.argsort()[:50]
                        pts_b_px  = pts_b_px[_top50]
                        pts_s_px  = pts_s_px[_top50]
                        confidence = confidence[_top50]

                    # CPU로 한 번만 동기화
                    k0      = pts_b_px.cpu().numpy()
                    k1      = pts_s_px.cpu().numpy()
                    conf_np = confidence.cpu().numpy()

                    # MPS 메모리 캐시 정리 (unified memory 효율화)
                    if hasattr(torch, 'mps') and hasattr(torch.mps, 'empty_cache'):
                        torch.mps.empty_cache()
                    else:
                        torch.cuda.empty_cache()

                except Exception as match_err:
                    #print(f"   [warn] RoMaV2 매칭 실패 ({short_name_of(long_name)}): {match_err}")
                    pass
                # ── RANSAC 후처리를 비동기 스레드에 제출 ─────────────
                # .copy()로 뷰 참조 끊기 → img_b_rgb 원본 3채널 배열 즉시 해제 가능
                item = (long_name,
                        img_b_rgb[:, :, 0].copy(),   # view → 독립 배열로 복사
                        img_s_rgb[:, :, 0].copy(),
                        k0.copy(), k1.copy(),
                        conf_np.copy() if conf_np is not None else None)
                postproc_futs.append(post_pool.submit(_process_matches, item))

            # ── 완료된 후처리 결과 수집 (블로킹 최소화) ──────────────
            still_pending = []
            for fut in postproc_futs:
                if fut.done():
                    result = fut.result()
                    if result is None:
                        continue
                    new_rows.append(result["new_row"])
                    summary_rows.append(result["summary_row"])
                    if result["success"]:
                        success_count += 1
                    else:
                        fail_count += 1
                    if visualize:
                        try:
                            _render_viz(result, save_success, save_fallback)
                        except Exception:
                            pass
                else:
                    still_pending.append(fut)
            postproc_futs = still_pending

        # ── 남은 후처리 결과 최종 수집 ───────────────────────────────
        for fut in _cf.as_completed(postproc_futs):
            result = fut.result()
            if result is None:
                continue
            new_rows.append(result["new_row"])
            summary_rows.append(result["summary_row"])
            if result["success"]:
                success_count += 1
            else:
                fail_count += 1
            if visualize:
                try:
                    _render_viz(result, save_success, save_fallback)
                except Exception:
                    pass


    # ==========================
    # (종합) 시각화 (전체 패치)
    # ==========================
    if visualize and len(new_rows) > 0:
        try:
            from PIL import Image
            import matplotlib.gridspec as gridspec
            mapped_df = pd.DataFrame(new_rows)
            valid_b = mapped_df.dropna(subset=['Bluebon_y', 'Bluebon_x'])
            if len(valid_b) > 0:
                B_full_path = os.path.join(dir, "..", "merged_top.tif")
                if not os.path.exists(B_full_path):
                    B_full_path = ""
                    for tif_f in os.listdir(os.path.join(dir, "..")):
                        if tif_f.endswith(".tif") and "merged" in tif_f:
                            B_full_path = os.path.join(dir, "..", tif_f)
                            break

                s_full_path = ""
                step11_dir = os.path.join(dir, "step11_Mosaic")
                if os.path.exists(step11_dir):
                    s_cands = [f for f in os.listdir(step11_dir) if "sentinel_mosaic" in f.lower() and f.endswith(".tif")]
                    if s_cands:
                        s_full_path = os.path.join(step11_dir, s_cands[0])

                if os.path.exists(B_full_path) and os.path.exists(s_full_path):
                    from scipy.ndimage import percentile_filter

                    def _load_and_stretch_bluebon(path):
                        """Bluebon 로드: 8밴드→4번, 4밴드→3번, 나머지→1번"""
                        with rasterio.open(path) as src:
                            n_bands = src.count
                            if n_bands >= 8:
                                red_idx = 4  # 8밴드: 4번째 밴드 (Red)
                            elif n_bands >= 4:
                                red_idx = 3  # 4밴드: 3번째 밴드 (Red)
                            else:
                                red_idx = 1  # 그 외: 1번째 밴드
                            band = src.read(red_idx).astype(np.float32)
                        p2, p98 = np.percentile(band, (2, 98))
                        band = np.clip((band - p2) / (p98 - p2 + 1e-5), 0, 1)
                        return np.stack([band, band, band], axis=-1)  # (H,W,3) grayscale RGB

                    def _load_and_stretch_sentinel(path):
                        """Sentinel 로드: 첫 번째 밴드(Red)만 사용"""
                        with rasterio.open(path) as src:
                            band = src.read(1).astype(np.float32)  # 1번째 밴드 = Red
                        p2, p98 = np.percentile(band, (2, 98))
                        band = np.clip((band - p2) / (p98 - p2 + 1e-5), 0, 1)
                        return np.stack([band, band, band], axis=-1)  # (H,W,3) grayscale RGB

                    B_rgb = _load_and_stretch_bluebon(B_full_path)
                    S_rgb = _load_and_stretch_sentinel(s_full_path)

                    Hb, Wb, _ = B_rgb.shape
                    Hs, Ws, _ = S_rgb.shape
                    
                    df_succ = mapped_df[mapped_df['results'] == 'success']
                    
                    fig = plt.figure(figsize=(24, 12))
                    gs = gridspec.GridSpec(1, 2, width_ratios=[1, 1], wspace=0.05)
                    
                    ax1 = fig.add_subplot(gs[0])
                    ax1.imshow(S_rgb)
                    ax1.set_xlim(0, Ws); ax1.set_ylim(Hs, 0)
                    ax1.set_title("Target Image (Reference)", fontsize=16)
                    ax1.axis('off')
                    if len(df_succ) > 0:
                        sy = df_succ[f'{ref_label}_y_orig'].values
                        sx = df_succ[f'{ref_label}_x_orig'].values
                        ax1.scatter(sx, sy, s=20, c='cyan', marker='^', label='Initial')
                        sy_upd = df_succ[f'{ref_label}_y_updated'].values
                        sx_upd = df_succ[f'{ref_label}_x_updated'].values
                        ax1.scatter(sx_upd, sy_upd, s=30, c='red', marker='x', label='Matched (Updated)')
                        for px, py, ux, uy in zip(sx, sy, sx_upd, sy_upd):
                            ax1.plot([px, ux], [py, uy], color='yellow', linewidth=1, alpha=0.9)
                        ax1.legend()

                    ax2 = fig.add_subplot(gs[1])
                    ax2.imshow(B_rgb)
                    ax2.set_xlim(0, Wb); ax2.set_ylim(Hb, 0)
                    ax2.set_title("Source Image (BlueBon)", fontsize=16)
                    ax2.axis('off')
                    if len(df_succ) > 0:
                        bx = df_succ['Bluebon_x'].values
                        by = df_succ['Bluebon_y'].values
                        ax2.scatter(bx, by, s=30, c='red', marker='x')

                    plt.tight_layout()
                    full_viz_png = os.path.join(save_root, "romav2_full_viz_patch.png")
                    plt.savefig(full_viz_png, dpi=200, bbox_inches='tight')
                    plt.close(fig)
                    print(f"   📊 종합 시각화 저장 완료: {full_viz_png}")
        except Exception as e:
            print(f"   ⚠️  종합 시각화 실패: {e}")



    # 파싱 실패 통계
    if parse_fail_count > 0:
        print(f"\n   ⚠️  파일명 파싱 실패: {parse_fail_count}개")
        for ex in parse_fail_examples:
            print(f"      • {ex}")

    print(f"\n   ✅ RoMaV2 STEP 13 완료: 성공 {success_count}개, 실패 {fail_count}개 (전체 {len(common_names)}개)")

    # --- XLSX 저장 ---
    xlsx_out = os.path.join(save_root, "mapped_xy.xlsx")
    final_cols = [
        "name",
        "Bluebon_y", "Bluebon_x",
        f"{ref_label}_y_orig", f"{ref_label}_x_orig",
        "dy", "dx",
        f"{ref_label}_y_updated", f"{ref_label}_x_updated",
        "inliers", "total_matches", "matching_rate", "results",
        "fail_reason",
        "a00", "a01", "a02", "b00", "b01", "b02",
    ]
    new_df = pd.DataFrame(new_rows)
    for c in final_cols:
        if c not in new_df.columns:
            new_df[c] = np.nan
    new_df = new_df[final_cols].drop_duplicates(subset=['name'], keep='last')

    if os.path.exists(xlsx_out):
        try:
            old_df = pd.read_excel(xlsx_out, sheet_name='results')
            if 'name' not in old_df.columns or old_df.empty:
                merged = new_df.copy()
            else:
                old_df = old_df.dropna(subset=['name']).drop_duplicates(subset=['name'], keep='last').set_index("name")
                new_df_idx = new_df.set_index("name")
                old_df.update(new_df_idx)
                merged = pd.concat(
                    [old_df, new_df_idx[~new_df_idx.index.isin(old_df.index)]], axis=0
                ).reset_index()
                for c in final_cols:
                    if c not in merged.columns:
                        merged[c] = np.nan
                merged = merged[final_cols]
        except Exception as e:
            print(f"   ⚠️ 기존 mapped_xy.xlsx 읽기 실패: {e}")
            merged = new_df.copy()
    else:
        merged = new_df.copy()

    summary_df = pd.DataFrame(summary_rows)
    summary_cols = [
        "name", "Bluebon_y", "Bluebon_x",
        f"{ref_label}_y", f"{ref_label}_x",
        "dy", "dx", "confidence", "num_matches"
    ]
    for c in summary_cols:
        if c not in summary_df.columns:
            summary_df[c] = np.nan
    summary_df = summary_df.drop_duplicates(subset=['name'], keep='last')[summary_cols]

    with pd.ExcelWriter(xlsx_out, engine="openpyxl") as writer:
        merged.to_excel(writer, index=False, sheet_name="results")
        summary_df.to_excel(writer, index=False, sheet_name="summary")
        ws = writer.sheets["results"]
        header = {cell.value: i + 1 for i, cell in enumerate(next(ws.iter_rows(min_row=1, max_row=1)))}
        m_start = header.get("a00"); m_end = header.get("b02")
        results_col = header.get("results")
        if results_col and m_start and m_end:
            red_fill = PatternFill(start_color="FFFFCCCC", end_color="FFFFCCCC", fill_type="solid")
            for row_idx in range(2, ws.max_row + 1):
                val = ws.cell(row=row_idx, column=results_col).value
                if str(val).lower() == "fail":
                    for col_idx in range(m_start, m_end + 1):
                        ws.cell(row=row_idx, column=col_idx).fill = red_fill

    # --- NPZ 저장 (SUCCESS만) ---
    npz_out = os.path.join(save_root, "stage4_matches.npz")
    cols_needed = ["Bluebon_y", "Bluebon_x", f"{ref_label}_y_updated", f"{ref_label}_x_updated", "results"]
    valid = merged[cols_needed].dropna()
    valid_success = valid[valid["results"].astype(str).str.lower() == "success"]
    tar_points = (
        valid_success[["Bluebon_y", "Bluebon_x"]].to_numpy(dtype=np.float32)
        if len(valid_success) > 0 else np.empty((0, 2), dtype=np.float32)
    )
    ref_points = (
        valid_success[[f"{ref_label}_y_updated", f"{ref_label}_x_updated"]].to_numpy(dtype=np.float32)
        if len(valid_success) > 0 else np.empty((0, 2), dtype=np.float32)
    )
    np.savez(npz_out, ref_points=ref_points, tar_points=tar_points)
    print(f"   💾 NPZ 저장: {npz_out} (ref/tar: {len(ref_points)}쌍)")
    print(f"   💾 XLSX 저장: {xlsx_out}")

    return {
        "stage4": {
            "ref_points": ref_points,
            "tar_points": tar_points,
            "num_matches": int(ref_points.shape[0]),
        }
    }


def PrcsnMatching(OUTPUT_DIR, MATCH_METHOD, target_resolution: float = None):
    try:
        # GCP chip 모드 감지
        step12_patches_dir = os.path.join(OUTPUT_DIR, 'step12_patches')
        gcp_chip_dir = os.path.join(step12_patches_dir, 'GCPChip_224')
        use_gcp_chip_mode = os.path.exists(gcp_chip_dir) and os.listdir(gcp_chip_dir)
        
        # GCP chip 모드일 때는 match_rate_thresh=0.3, 그 외는 0.8
        match_rate_thresh = 0.5 if use_gcp_chip_mode else 0.9
        if use_gcp_chip_mode:
            print(f"   ℹ️  GCP chip 모드 감지: match_rate_thresh={match_rate_thresh} 사용")
        
        # STEP 13: 매칭 결과 정리
        if MATCH_METHOD.upper() == "LOFTR":
            print("\n" + "=" * 80)
            print("STEP 13: LoFTR 기반 정밀 매칭")
            print("=" * 80)
            print("🎯 패치 영역에서 LoFTR로 고정밀 특징점 매칭 수행")
            matching_results = Step_13_LoFTR(OUTPUT_DIR, MATCH_METHOD, inlier_min_count=100, visualize=True,
                                             target_resolution=target_resolution, match_rate_thresh=match_rate_thresh)

        elif MATCH_METHOD.upper() == "SATLOFTR":
            print("\n" + "=" * 80)
            print("STEP 13: Sat LoFTR 기반 정밀 매칭")
            print("=" * 80)
            print("🎯 패치 영역에서 Sat LoFTR로 고정밀 특징점 매칭 수행")
            matching_results = Step_13_LoFTR(OUTPUT_DIR, MATCH_METHOD, inlier_min_count=100, visualize=True,
                                             target_resolution=target_resolution, match_rate_thresh=match_rate_thresh)

        elif MATCH_METHOD.upper() == "LIGHTGLUE":
            print("\n" + "=" * 80)
            print("STEP 13: Superpoint + Lightglue 기반 정밀 매칭")
            print("=" * 80)
            print("🎯 패치 영역에서 LIGHTGLUE로 고정밀 특징점 매칭 수행")
            matching_results = Step_13_super_light(OUTPUT_DIR, visualize=True)

        elif MATCH_METHOD.upper() == "SIFT":
            print("\n" + "=" * 80)
            print("STEP 13: SIFT 기반 정밀 매칭")
            print("=" * 80)
            print("🎯 패치 영역에서 OpenCV SIFT (Descriptor + Matcher)로 고정밀 특징점 매칭 수행")
            matching_results = Step_13_LoFTR(OUTPUT_DIR, MATCH_METHOD, inlier_min_count=100, visualize=True,
                                             target_resolution=target_resolution, match_rate_thresh=match_rate_thresh)

        elif MATCH_METHOD.upper() == "ROMAV2":
            print("\n" + "=" * 80)
            print("STEP 13: RoMaV2 기반 정밀 매칭")
            print("=" * 80)
            print("🎯 패치 영역에서 RoMaV2 (dense warp)로 고정밀 특징점 매칭 수행")
            print("   ⚡ MPS / CUDA / CPU 자동 감지")
            
            # RoMaV2는 임계값을 0.7로 설정 (기본은 0.8)
            romav2_thresh = 0.8 if use_gcp_chip_mode else 0.8
            if not use_gcp_chip_mode:
                print(f"   ℹ️  RoMaV2 지정: match_rate_thresh={romav2_thresh} 사용")

            try:
                import romav2
                # 현재 환경에 RoMaV2가 설치되어 있다면 직접 실행 (geo_romav2)
                matching_results = Step_13_RoMaV2(OUTPUT_DIR, inlier_min_count=100, visualize=True,
                                                   target_resolution=target_resolution,
                                                   match_rate_thresh=romav2_thresh,
                                                   num_corresp=2000, batch_size=4, setting="fast")
            except ImportError:
                # geo_unified 등 다른 환경에서 실행된 경우 별도 프로세스로 위임
                print("   🔄 현재 환경에 RoMaV2가 없어 geo_unified 환경의 별도 프로세스로 실행합니다...")
                import subprocess

                # 실행할 geo_unified Python 절대경로 찾기
                romav2_python = "/mnt/hdd/miniconda3/envs/geo_unified/bin/python"
                if not os.path.exists(romav2_python):
                    # fallback (conda가 경로에 다른 곳에 있을 수 있음)
                    base_cmd = ["conda", "run", "-n", "geo_unified", "python"]
                else:
                    base_cmd = [romav2_python]

                standalone_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_romav2_standalone.py")
                cmd = base_cmd + [
                    standalone_script,
                    "--dir", OUTPUT_DIR,
                    "--match_rate_thresh", str(romav2_thresh),
                    "--setting", "fast"
                ]
                if target_resolution is not None:
                    cmd.extend(["--target_resolution", str(target_resolution)])

                # KMP_DUPLICATE_LIB_OK=TRUE 환경변수 설정 (macOS OpenMP 충돌 방지)
                env = os.environ.copy()
                env["KMP_DUPLICATE_LIB_OK"] = "TRUE"
                env["PYTHONUNBUFFERED"] = "1"

                try:
                    print(f"   ▶️  실행 명령: {' '.join(cmd)}")
                    print("   ── geo_unified subprocess 출력 시작 ──")
                    proc = subprocess.Popen(
                        cmd, env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True, bufsize=1,
                    )
                    last_lines = []
                    for line in iter(proc.stdout.readline, ""):
                        print(f"   │ {line.rstrip()}")
                        last_lines.append(line.rstrip())
                        if len(last_lines) > 40:
                            last_lines.pop(0)
                    proc.stdout.close()
                    returncode = proc.wait()
                    print(f"   ── subprocess 종료 (exit code: {returncode}) ──")

                    if returncode != 0:
                        tail = "\n".join(last_lines[-15:])
                        raise RuntimeError(f"geo_unified 프로세스 오류 (exit code: {returncode})\n최근 출력:\n{tail}")

                    # 실행 결과인 stage4_matches.npz 파일을 다시 로드하여 리턴값 재구성
                    npz_path = os.path.join(OUTPUT_DIR, "05_ROMAV2_result", "stage4_matches.npz")
                    if os.path.exists(npz_path):
                        data = np.load(npz_path)
                        ref_pts = data["ref_points"]
                        tar_pts = data["tar_points"]
                        matching_results = {
                            "stage4": {
                                "ref_points": ref_pts,
                                "tar_points": tar_pts,
                                "num_matches": int(ref_pts.shape[0]),
                            }
                        }
                    else:
                        # returncode=0인데 결과 npz가 없는 케이스 — RoMa가 매칭 부족 등으로 stage4 도달 못함
                        result_dir = os.path.join(OUTPUT_DIR, "05_ROMAV2_result")
                        produced = sorted(os.listdir(result_dir)) if os.path.isdir(result_dir) else []
                        tail = "\n".join(last_lines[-15:])
                        raise FileNotFoundError(
                            f"RoMaV2 결과 파일을 찾을 수 없습니다: {npz_path}\n"
                            f"   ▸ subprocess는 정상 종료(exit=0)했으나 stage4_matches.npz가 생성되지 않음\n"
                            f"   ▸ 결과 디렉토리 내용: {produced if produced else '(없음 또는 디렉토리 자체가 없음)'}\n"
                            f"   ▸ 최근 출력 tail:\n{tail}"
                        )

                except Exception as e:
                    raise RuntimeError(f"geo_unified 연동 실행 실패: {e}")

        # 업데이트 예정
        # elif MATCH_METHOD.upper() == "ZNCC":
        # elif MATCH_METHOD.upper() == "Siamese U-NET":

        else:
            raise ValueError(f"❌ Unknown MATCH_METHOD: {MATCH_METHOD}")

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        raise
    
    return matching_results
