"""
Swin2-MoSE Super-Resolution
입력: lotte_enhanced_0.01_0.1_0.003_0.9.jpg
출력: lotte_swin2mose_sr.jpg

주의: Swin2-MoSE는 원래 4채널 위성 영상(Sentinel-2) 용으로 훈련됨.
      RGB 이미지를 적용할 때 grayscale 채널을 4번째 채널로 추가하여 적응시킴.
"""

import os
import sys
import subprocess
import urllib.request
import zipfile
import math

import torch
import numpy as np
from PIL import Image
import yaml

# ─── 설정 ─────────────────────────────────────────────────────────────────────
INPUT_IMAGE  = "lotte_enhanced_0.01_0.1_0.003_0.9.jpg"
OUTPUT_IMAGE = "lotte_swin2mose_sr.jpg"
REPO_DIR     = os.path.join(os.path.dirname(os.path.abspath(__file__)), "swin2-mose")

# GitHub Releases v1.1 (2x upscale, Sen2Venus)
WEIGHTS_ZIP  = "sen2venus_exp4_2x_v5_1.zip"
WEIGHTS_URL  = "https://github.com/IMPLabUniPr/swin2-mose/releases/download/v1.1/sen2venus_exp4_2x_v5_1.zip"
CHECKPOINT_SUBDIR = os.path.join("output", "sen2venus_exp4_2x_v5_1", "checkpoints")


# ─── 레포 클론 ────────────────────────────────────────────────────────────────
def setup_repo():
    if not os.path.exists(REPO_DIR):
        print("[1/4] Swin2-MoSE 레포 클론 중...")
        subprocess.run(
            ["git", "clone", "https://github.com/IMPLabUniPr/swin2-mose.git", REPO_DIR],
            check=True
        )
        print("      완료.\n")
    else:
        print("[1/4] 레포 이미 존재함.\n")


# ─── 가중치 다운로드 ──────────────────────────────────────────────────────────
def download_weights():
    ckpt_dir    = os.path.join(REPO_DIR, CHECKPOINT_SUBDIR)
    cfg_path    = os.path.join(ckpt_dir, "config-70.yml")
    weights_path = os.path.join(ckpt_dir, "model-70.pt")

    if os.path.exists(cfg_path) and os.path.exists(weights_path):
        print("[2/4] 가중치 이미 존재함.\n")
        return cfg_path, weights_path

    os.makedirs(ckpt_dir, exist_ok=True)
    zip_path = os.path.join(REPO_DIR, WEIGHTS_ZIP)

    if not os.path.exists(zip_path):
        print(f"[2/4] 가중치 다운로드 중... ({WEIGHTS_URL})")

        def _progress(block_num, block_size, total_size):
            downloaded = block_num * block_size
            if total_size > 0:
                pct = min(downloaded / total_size * 100, 100)
                print(f"\r      {pct:.1f}%  ({downloaded//1024//1024} MB / {total_size//1024//1024} MB)",
                      end="", flush=True)

        urllib.request.urlretrieve(WEIGHTS_URL, zip_path, _progress)
        print("\n      다운로드 완료.")

    print("      압축 해제 중...")
    with zipfile.ZipFile(zip_path, "r") as z:
        z.extractall(REPO_DIR)
    print("      완료.\n")

    return cfg_path, weights_path


# ─── 정규화 유틸 (run.py 동일) ────────────────────────────────────────────────
def _to_shape(t, ref):
    t = t[None].repeat(ref.shape[0], 1)
    return t.view(ref.shape[:2] + (1, 1))


def normalize(tensor, mean, std):
    m = torch.tensor(mean, dtype=torch.float32).to(tensor.device)
    s = torch.tensor(std,  dtype=torch.float32).to(tensor.device)
    return (tensor - _to_shape(m, tensor)) / _to_shape(s, tensor)


def denormalize(tensor, mean, std):
    m = torch.tensor(mean, dtype=torch.float32).to(tensor.device)
    s = torch.tensor(std,  dtype=torch.float32).to(tensor.device)
    return tensor * _to_shape(s, tensor) + _to_shape(m, tensor)


# ─── RGB → 4채널 변환 ─────────────────────────────────────────────────────────
def rgb_to_4ch(rgb_tensor):
    """
    (1, 3, H, W) → (1, 4, H, W)
    4번째 채널: grayscale (luminance) 로 위성 영상의 NIR 밴드 자리를 채움.
    """
    r, g, b = rgb_tensor[:, 0:1], rgb_tensor[:, 1:2], rgb_tensor[:, 2:3]
    lum = 0.2989 * r + 0.5870 * g + 0.1140 * b   # ITU-R BT.601
    return torch.cat([r, g, b, lum], dim=1)


# ─── 타일 처리 (메모리 절약) ──────────────────────────────────────────────────
def infer_tiled(model, img_4ch, device, tile=256, overlap=32):
    """
    큰 이미지를 tile×tile 패치로 잘라 추론 후 합성.
    overlap: 경계 아티팩트 방지를 위한 겹침 픽셀 수.
    """
    _, C, H, W = img_4ch.shape
    scale = 2   # 2x upscale

    out_H, out_W = H * scale, W * scale
    output = torch.zeros(1, C, out_H, out_W, device=device)
    weight = torch.zeros(1, C, out_H, out_W, device=device)

    step = tile - overlap
    ys = list(range(0, H - tile, step)) + [H - tile]
    xs = list(range(0, W - tile, step)) + [W - tile]

    total = len(ys) * len(xs)
    idx = 0

    for y in ys:
        for x in xs:
            idx += 1
            patch = img_4ch[:, :, y:y+tile, x:x+tile].to(device)

            with torch.no_grad():
                sr_patch = model(patch)
                if not torch.is_tensor(sr_patch):
                    sr_patch, _ = sr_patch

            oy, ox = y * scale, x * scale
            th, tw = sr_patch.shape[2], sr_patch.shape[3]

            output[:, :, oy:oy+th, ox:ox+tw] += sr_patch
            weight[:, :, oy:oy+th, ox:ox+tw] += 1.0

            print(f"\r      타일 {idx}/{total} 처리 중...", end="", flush=True)

    print()
    return output / weight.clamp(min=1e-6)


# ─── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    input_path  = os.path.join(base_dir, INPUT_IMAGE)
    output_path = os.path.join(base_dir, OUTPUT_IMAGE)

    print("\n" + "=" * 55)
    print("  Swin2-MoSE Super-Resolution")
    print("=" * 55 + "\n")

    # 1. 레포 준비
    setup_repo()

    # 2. 가중치 다운로드
    cfg_path, weights_path = download_weights()

    # 3. 모델 임포트 & 로드
    model_dir = os.path.join(REPO_DIR, "swin2_mose_model")
    if model_dir not in sys.path:
        sys.path.insert(0, model_dir)

    print("[3/4] 모델 로드 중...")
    from model import Swin2MoSE   # noqa: E402  (레포 클론 후 임포트)

    with open(cfg_path, "r") as f:
        cfg = yaml.safe_load(f)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"      디바이스: {device}")

    model = Swin2MoSE(**cfg["super_res"]["model"])
    ckpt  = torch.load(weights_path, map_location=device)
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval().to(device)
    print("      완료.\n")

    # 4. 이미지 추론
    print(f"[4/4] 이미지 추론: {INPUT_IMAGE}")
    img = Image.open(input_path).convert("RGB")
    print(f"      입력 크기: {img.width} × {img.height} px")

    # [0,1] float tensor (1, 3, H, W)
    img_np = np.array(img).astype(np.float32) / 255.0
    img_t  = torch.from_numpy(img_np.transpose(2, 0, 1)).unsqueeze(0)

    # RGB → 4채널
    img_4ch = rgb_to_4ch(img_t)   # (1, 4, H, W)

    # 입력 통계 계산 (위성 통계 대신 이미지 자체 통계 사용)
    lr_mean = img_4ch.mean(dim=[0, 2, 3]).tolist()
    lr_std  = [max(s, 1e-6) for s in img_4ch.std(dim=[0, 2, 3]).tolist()]

    img_norm = normalize(img_4ch, lr_mean, lr_std)

    # 타일 추론
    sr_norm = infer_tiled(model, img_norm, device, tile=256, overlap=32)

    # 역정규화
    sr = denormalize(sr_norm, lr_mean, lr_std)

    # 4채널 → RGB (처음 3채널만 사용)
    sr_np  = sr.squeeze(0).cpu().numpy()          # (4, H*2, W*2)
    sr_rgb = sr_np[:3].transpose(1, 2, 0)         # (H*2, W*2, 3)
    sr_rgb = np.clip(sr_rgb, 0, 1)
    sr_u8  = (sr_rgb * 255).astype(np.uint8)

    out_img = Image.fromarray(sr_u8)
    out_img.save(output_path, quality=95)

    print(f"\n      입력:  {img.width} × {img.height} px")
    print(f"      출력:  {out_img.width} × {out_img.height} px  (2x 업스케일)")
    print(f"      저장:  {OUTPUT_IMAGE}")
    print("\n" + "=" * 55)
    print("  완료!")
    print("=" * 55 + "\n")


if __name__ == "__main__":
    main()
