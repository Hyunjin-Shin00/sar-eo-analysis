"""
Real-ESRGAN Super-Resolution
입력: lotte_enhanced_0.01_0.1_0.003_0.9.jpg
출력: lotte_realesrgan_sr.jpg
"""

import os
import urllib.request

import cv2
import numpy as np
import torch

INPUT_IMAGE  = "lotte_enhanced_0.01_0.1_0.003_0.9.jpg"
OUTPUT_IMAGE = "lotte_realesrgan_sr.jpg"
SCALE        = 4

WEIGHTS_URL  = "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth"
WEIGHTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "RealESRGAN_x4plus.pth")


# ─── 가중치 다운로드 ──────────────────────────────────────────────────────────
def download_weights():
    if os.path.exists(WEIGHTS_PATH):
        print("[1/3] 가중치 이미 존재함.\n")
        return

    print(f"[1/3] 가중치 다운로드 중... ({WEIGHTS_URL})")

    def _progress(block_num, block_size, total_size):
        downloaded = block_num * block_size
        if total_size > 0:
            pct = min(downloaded / total_size * 100, 100)
            print(f"\r      {pct:.1f}%  ({downloaded//1024//1024} MB / {total_size//1024//1024} MB)",
                  end="", flush=True)

    urllib.request.urlretrieve(WEIGHTS_URL, WEIGHTS_PATH, _progress)
    print("\n      완료.\n")


# ─── 모델 로드 ────────────────────────────────────────────────────────────────
def load_model(device):
    from basicsr.archs.rrdbnet_arch import RRDBNet
    from realesrgan import RealESRGANer

    print("[2/3] 모델 로드 중...")
    print(f"      디바이스: {device}")

    model = RRDBNet(
        num_in_ch=3, num_out_ch=3,
        num_feat=64, num_block=23, num_grow_ch=32,
        scale=SCALE
    )
    upsampler = RealESRGANer(
        scale=SCALE,
        model_path=WEIGHTS_PATH,
        model=model,
        tile=512,          # 8GB VRAM: OOM 방지용 타일 처리
        tile_pad=32,
        pre_pad=0,
        half=True,         # fp16으로 VRAM 절약
        device=device,
    )
    print("      완료.\n")
    return upsampler


# ─── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    base_dir    = os.path.dirname(os.path.abspath(__file__))
    input_path  = os.path.join(base_dir, INPUT_IMAGE)
    output_path = os.path.join(base_dir, OUTPUT_IMAGE)

    print("\n" + "=" * 55)
    print("  Real-ESRGAN Super-Resolution")
    print("=" * 55 + "\n")

    # 1. 가중치
    download_weights()

    # 2. 모델
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    upsampler = load_model(device)

    # 3. 추론
    print(f"[3/3] 이미지 추론: {INPUT_IMAGE}")
    img = cv2.imread(input_path, cv2.IMREAD_UNCHANGED)
    h, w = img.shape[:2]
    print(f"      입력 크기: {w} × {h} px")

    output, _ = upsampler.enhance(img, outscale=SCALE)

    cv2.imwrite(output_path, output, [cv2.IMWRITE_JPEG_QUALITY, 95])

    oh, ow = output.shape[:2]
    print(f"\n      입력:  {w} × {h} px")
    print(f"      출력:  {ow} × {oh} px  ({SCALE}x 업스케일)")
    print(f"      저장:  {OUTPUT_IMAGE}")
    print("\n" + "=" * 55)
    print("  완료!")
    print("=" * 55 + "\n")


if __name__ == "__main__":
    main()
