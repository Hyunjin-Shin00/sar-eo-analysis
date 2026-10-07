"""
JPG 위성영상 품질 개선 파이프라인 (lotte.jpg)
순서: Colorspace linear → BM3D → Deblocking → Wiener → Edge-preserving sharpening
"""

import cv2
import numpy as np
import bm3d
from scipy.signal import wiener
from PIL import Image
import os

head = 'jamsil'
INPUT = f"{head}.jpg"
OUTPUT = f"{head}_enhanced.jpg"


# ──────────────────────────────────────────
# STEP 0: 로드 + linear colorspace 변환
# ──────────────────────────────────────────
def load_linear(path):
    img_bgr = cv2.imread(path, cv2.IMREAD_COLOR)
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    # sRGB → linear (gamma 2.2 제거)
    img_f = img_rgb.astype(np.float32) / 255.0
    img_linear = np.where(img_f <= 0.04045,
                          img_f / 12.92,
                          ((img_f + 0.055) / 1.055) ** 2.4)
    return img_linear  # [0,1] float32, linear


def linear_to_srgb(img_linear):
    img_srgb = np.where(img_linear <= 0.0031308,
                        img_linear * 12.92,
                        1.055 * (img_linear ** (1.0 / 2.4)) - 0.055)
    return np.clip(img_srgb, 0, 1)


# ──────────────────────────────────────────
# STEP 1: BM3D — 낮은 강도 (over-smoothing 방지)
# ──────────────────────────────────────────
def apply_bm3d(img_linear, sigma=0.04):
    """
    sigma: 노이즈 표준편차 추정값 (0~1 스케일)
    JPG용 권장: 0.03~0.06 (낮을수록 덜 smoothing)
    """
    print(f"  BM3D sigma={sigma} ...")
    result = np.zeros_like(img_linear)
    for c in range(3):
        result[:, :, c] = bm3d.bm3d(img_linear[:, :, c], sigma_psd=sigma)
    return np.clip(result, 0, 1)


# ──────────────────────────────────────────
# STEP 2: DCT-domain Deblocking
# JPEG 8×8 블록 경계만 타겟팅
# ──────────────────────────────────────────
def apply_deblocking(img_linear, strength=0.4):
    """
    strength: 0~1 (블록 경계 스무딩 강도)
    JPG용 권장: 0.3~0.5
    """
    print(f"  Deblocking strength={strength} ...")
    img_u8 = (np.clip(img_linear, 0, 1) * 255).astype(np.uint8)

    # JPEG 8×8 블록 경계 마스크 생성
    h, w = img_u8.shape[:2]
    mask = np.zeros((h, w), dtype=np.float32)
    mask[7::8, :] = 1.0   # 수평 경계
    mask[:, 7::8] = 1.0   # 수직 경계

    # 경계 주변 부드럽게 (dilate → blur)
    kernel = np.ones((3, 3), np.uint8)
    mask_dilated = cv2.dilate(mask, kernel, iterations=1)
    mask_blur = cv2.GaussianBlur(mask_dilated, (5, 5), 1.0)

    # 경계 영역만 bilateral filter로 스무딩
    smoothed = cv2.bilateralFilter(img_u8, d=5, sigmaColor=15, sigmaSpace=3)

    # 마스크로 블렌딩
    mask3 = np.stack([mask_blur] * 3, axis=-1) * strength
    result_u8 = (img_u8.astype(np.float32) * (1 - mask3)
                 + smoothed.astype(np.float32) * mask3).astype(np.uint8)

    return result_u8.astype(np.float32) / 255.0


# ──────────────────────────────────────────
# STEP 3: Wiener filter (선택, 약하게)
# blur 보정 — JPG에서 RL보다 안전
# ──────────────────────────────────────────
def apply_wiener(img_linear, mysize=3, noise=0.01):
    """
    mysize: 필터 윈도우 크기 (홀수, 작을수록 안전)
    noise:  노이즈 분산 추정 (높을수록 덜 선명, 더 안전)
    JPG용 권장: mysize=3, noise=0.005~0.02
    """
    print(f"  Wiener mysize={mysize}, noise={noise} ...")
    result = np.zeros_like(img_linear)
    for c in range(3):
        result[:, :, c] = wiener(img_linear[:, :, c], mysize=mysize, noise=noise)
    return np.clip(result, 0, 1)


# ──────────────────────────────────────────
# STEP 4: Edge-preserving sharpening (매우 약하게)
# ──────────────────────────────────────────
def apply_sharpening(img_linear, amount=0.3, radius=1.0):
    """
    amount: 선명도 강도 (0~1, JPG용 권장: 0.2~0.4)
    radius: unsharp mask 반경 (작을수록 fine detail)
    """
    print(f"  Sharpening amount={amount}, radius={radius} ...")
    img_u8 = (np.clip(img_linear, 0, 1) * 255).astype(np.uint8)

    # Unsharp masking
    blur_size = max(3, int(radius * 2) * 2 + 1)  # 홀수 보장
    blurred = cv2.GaussianBlur(img_u8, (blur_size, blur_size), radius)
    unsharp = cv2.addWeighted(img_u8, 1.0 + amount,
                               blurred, -amount, 0)

    # Edge-preserving blend (edge 영역만 sharpen 적용)
    gray = cv2.cvtColor(img_u8, cv2.COLOR_RGB2GRAY)
    edges = cv2.Laplacian(gray, cv2.CV_32F)
    edge_mask = np.clip(np.abs(edges) / 30.0, 0, 1)
    edge_mask = cv2.GaussianBlur(edge_mask, (5, 5), 1.0)
    edge_mask3 = np.stack([edge_mask] * 3, axis=-1)

    # edge 있는 곳만 sharpening 적용
    result_u8 = (img_u8.astype(np.float32) * (1 - edge_mask3)
                 + unsharp.astype(np.float32) * edge_mask3).astype(np.uint8)

    return result_u8.astype(np.float32) / 255.0


# ──────────────────────────────────────────
# 비교용 타일 저장 (원본 vs 결과)
# ──────────────────────────────────────────
def save_comparison(original_linear, enhanced_linear, path="lotte_compare.jpg"):
    orig_u8 = (linear_to_srgb(original_linear) * 255).astype(np.uint8)
    enh_u8  = (linear_to_srgb(enhanced_linear) * 255).astype(np.uint8)

    # 중앙 500×500 크롭으로 비교
    h, w = orig_u8.shape[:2]
    cy, cx = h // 2, w // 2
    crop_size = 500
    y1, y2 = cy - crop_size // 2, cy + crop_size // 2
    x1, x2 = cx - crop_size // 2, cx + crop_size // 2

    orig_crop = orig_u8[y1:y2, x1:x2]
    enh_crop  = enh_u8[y1:y2, x1:x2]

    # 좌(원본) | 우(개선) 배치
    divider = np.full((crop_size, 4, 3), 255, dtype=np.uint8)  # 흰 구분선
    compare = np.concatenate([orig_crop, divider, enh_crop], axis=1)

    # 라벨
    cv2.putText(compare, "Original", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 80, 80), 2)
    cv2.putText(compare, "Enhanced", (crop_size + 14, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (80, 200, 80), 2)

    cv2.imwrite(path, cv2.cvtColor(compare, cv2.COLOR_RGB2BGR),
                [cv2.IMWRITE_JPEG_QUALITY, 95])
    print(f"  비교 이미지 저장: {path}")


# ──────────────────────────────────────────
# 메인
# ──────────────────────────────────────────
def main():
    print(f"\n{'='*50}")
    print(f"  JPG 품질 개선: {INPUT}")
    print(f"{'='*50}\n")

    # ── Step 0: Load
    print("[0] 로드 + linear 변환")
    img = load_linear(INPUT)
    original = img.copy()
    print(f"    이미지 크기: {img.shape[1]}×{img.shape[0]} px\n")

    # ── Step 1: BM3D
    print("[1] BM3D artifact 제거")
    img = apply_bm3d(img, sigma=0.01)
    print()

    # ── Step 2: Deblocking
    print("[2] DCT Deblocking")
    img = apply_deblocking(img, strength=0.1)
    print()

    # ── Step 3: Wiener
    print("[3] Wiener filter")
    img = apply_wiener(img, mysize=3, noise=0.003)
    print()

    # ── Step 4: Sharpening
    print("[4] Edge-preserving sharpening")
    img = apply_sharpening(img, amount=0.9, radius=1.0)
    print()

    # ── 저장
    print("[5] 결과 저장")
    result_srgb = (linear_to_srgb(img) * 255).astype(np.uint8)
    result_bgr = cv2.cvtColor(result_srgb, cv2.COLOR_RGB2BGR)
    cv2.imwrite(OUTPUT, result_bgr, [cv2.IMWRITE_JPEG_QUALITY, 95])
    print(f"    개선 이미지: {OUTPUT}")

    save_comparison(original, img)

    print(f"\n{'='*50}")
    print("  완료!")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    main()
