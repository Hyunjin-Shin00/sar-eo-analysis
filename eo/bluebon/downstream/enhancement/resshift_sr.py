"""
ResShift Super-Resolution (NeurIPS 2023)
입력: lotte_enhanced_0.01_0.1_0.003_0.9.jpg
출력: resshift_out/lotte_enhanced_0.01_0.1_0.003_0.9.png

inference_resshift.py를 직접 호출 (가중치 다운로드 포함)
"""

import os
import sys
import subprocess
from pathlib import Path

BASE_DIR   = Path(__file__).resolve().parent
REPO_DIR   = BASE_DIR / "ResShift"

INPUT_IMAGE = BASE_DIR / "lotte_enhanced_0.01_0.1_0.003_0.9.jpg"
OUTPUT_DIR  = BASE_DIR / "resshift_out"


def main():
    print("\n" + "=" * 55)
    print("  ResShift Super-Resolution (NeurIPS 2023)")
    print("=" * 55 + "\n")

    assert INPUT_IMAGE.exists(), f"입력 이미지 없음: {INPUT_IMAGE}"
    OUTPUT_DIR.mkdir(exist_ok=True)

    import cv2
    img = cv2.imread(str(INPUT_IMAGE))
    h, w = img.shape[:2]
    print(f"입력 크기: {w} × {h} px\n")

    # inference_resshift.py 실행
    # chop_size=512, chop_stride=448 → 64px overlap, 8GB VRAM 대응
    cmd = [
        sys.executable,
        str(REPO_DIR / "inference_resshift.py"),
        "-i", str(INPUT_IMAGE),
        "-o", str(OUTPUT_DIR),
        "--task",       "realsr",
        "--scale",      "4",
        "--version",    "v3",       # 4 steps (빠름, journal 버전)
        "--chop_size",  "64",
        "--chop_stride","64",
        "--bs",         "8",
    ]

    print("실행 명령:", " ".join(cmd), "\n")
    result = subprocess.run(cmd, cwd=str(REPO_DIR))

    if result.returncode != 0:
        print("\n오류 발생. 위 로그를 확인하세요.")
        sys.exit(1)

    result_path = OUTPUT_DIR / f"{INPUT_IMAGE.stem}.png"
    if result_path.exists():
        sr = cv2.imread(str(result_path))
        oh, ow = sr.shape[:2]
        print(f"\n입력:  {w} × {h} px")
        print(f"출력:  {ow} × {oh} px  (4x 업스케일)")
        print(f"저장:  {result_path}")

    print("\n" + "=" * 55)
    print("  완료!")
    print("=" * 55 + "\n")


if __name__ == "__main__":
    main()
