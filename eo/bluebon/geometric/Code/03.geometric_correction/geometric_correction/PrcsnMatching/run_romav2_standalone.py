import os
import sys
import argparse

# ── RoMaV2 패키지 경로를 sys.path에 추가 (geo_unified 환경 실행 전용) ──
_this_dir  = os.path.dirname(os.path.abspath(__file__))   # PrcsnMatching/
_code_dir  = os.path.dirname(os.path.dirname(_this_dir))  # Code/
_repo_root = os.path.dirname(_code_dir)                   # BlueBON_gui/
_romav2_src = os.path.join(_repo_root, 'RoMaV2', 'src')
for _p in [_romav2_src, _code_dir, os.path.dirname(_this_dir)]:
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

# 부모 디렉토리도 추가 (geometric_correction 패키지 인식)
sys.path.insert(0, os.path.dirname(_this_dir))

from PrcsnMatching.Matching_performance_v3 import Step_13_RoMaV2

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run RoMaV2 independent of main conda environment")
    parser.add_argument("--dir", type=str, required=True, help="OUTPUT_DIR")
    parser.add_argument("--target_resolution", type=float, default=None)
    parser.add_argument("--match_rate_thresh", type=float, default=0.8)
    parser.add_argument("--setting", type=str, default="fast")
    parser.add_argument("--batch_size", type=int, default=4,
                        help="GPU 추론 배치 크기 (클수록 GPU 활용률 높아짐, 기본값: 8)")

    args = parser.parse_args()

    try:
        Step_13_RoMaV2(
            dir=args.dir,
            inlier_min_count=100,
            visualize=True,
            target_resolution=args.target_resolution,
            match_rate_thresh=args.match_rate_thresh,
            num_corresp=2000,
            batch_size=args.batch_size,
            setting=args.setting
        )
        print("✅ RoMaV2 독립 실행 완료")
    except Exception as e:
        import traceback
        print(f"❌ RoMaV2 독립 실행 오류: {e}")
        traceback.print_exc()
        sys.exit(1)
