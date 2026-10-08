"""DINOv3 + Mask2Former 추론 — **이 폴더 안에서** 돈다. `sampoly_run.py` 와 같은 자리다.

    모델 코드   `<WORK_ROOT>/building_seg/dinov3_v2` → `sitecheck/vendor/dinov3seg/`
                (`infer.py` · `polygonize.py` · `heads.py` · 학습기 · 그 import 사슬)
    감싸는 절차 이 파일 + `dinov3seg/sitecheck_worker.py`

**부르는 쪽에서 보면 `sampoly_run.run` 과 똑같다** — 장면 폴더와 tag 를 주면
`out/<tag>_poly.json` 을 남기고 그 경로를 돌려준다. 파일 안의 키도 같다(`polys`(장면 픽셀
좌표) · `scores` · `source` · `stats`). 그래서 [[steps/s1_building.py]] 뒤쪽(임계값 · 경위도
변환 · 합치기 · 귀속 · id)은 **한 줄도 바뀌지 않는다.** 모델만 갈렸다.

**서브프로세스로 부른다** — 환경이 같아도 그렇다([[settings.DINOV3_PYTHON]]). GPU 메모리와
전역 설정을 본체와 섞지 않으려는 것이고, SAMPolyBuild 를 부를 때와 같은 방식이다.

2026-08-27 까지는 **환경이 달라서**이기도 했다 — 이 모델은 torch 2.13 · transformers 5.15 에서
학습됐는데(학습 기록 `runs/run4/run_config.json`) 그때 저장소의 `.venv` 는 torch 2.0 · mmcv
2.0(SAMPolyBuild 가 컴파일된 그 조합)이라 여기서 돌지 않았다. 그 mmcv 를 걷어 내고 환경을
하나로 합쳤으므로 지금은 `requirements.txt` 하나로 만든 `.venv` 에서 그대로 돈다. 부르는 방식은
바꾸지 않았다 — 위의 이유가 남아 있고, 모델만 다른 환경으로 갈라야 할 날의 자리이기도 하다.

    python -m sitecheck.vendor.dinov3seg_run --scene assets/scenes/daegu --tag t1 \
        --region 1000,1000,1600,1600 --tta
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE / "dinov3seg"                     # 벤더한 코드
WORKER = REPO / "sitecheck_worker.py"


def pick_gpu():
    """free 메모리가 가장 큰 GPU. 공유 장비에서 남의 작업 위에 얹지 않으려는 것.

    예전에는 `sampoly_run` 에 있던 것을 빌려 썼는데, 그 파일이 옛 모델과 함께 걷혀서
    (2026-08-27) 여기로 옮겼다 — 모델이 하나면 이 판단도 한 곳에 있는 것이 맞다.
    """
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=index,memory.free", "--format=csv,noheader,nounits"],
            text=True)
        best, free_max = 0, -1
        for line in out.strip().splitlines():
            idx, free = (int(v) for v in line.split(","))
            if free > free_max:
                best, free_max = idx, free
        return best
    except Exception:                                        # noqa: BLE001
        return 0


def run(scene_dir, tag, ckpt, *, python, crop=512, overlap=256, input_size=0,
        threshold=0.1, score_mode="cls_iou", mask_thr=0.5, min_area=100,
        iou_thr=0.5, ios_thr=0.8, clean_ios_thr=0.6, min_side=8.0,
        max_aspect=6.0, tta=False, clean=True, poly_min_area=200,
        poly_min_iou=0.70, dp_eps=3.0, angle_tol=20.0, min_edge=3.0,
        region=None, gpu=None, verbose=True):
    """장면(또는 그 일부) → `out/<tag>_poly.json`. 그 경로를 돌려준다.

    기본값은 **run4 가 실제로 돌았던 값**이다(`--threshold 0.1` · `--tta` · polygonize CLI
    기본값). 어떻게 알아냈는지는 [[dinov3seg/sitecheck_worker.py]] 머리글에 있다.
    """
    scene_dir = Path(scene_dir).resolve()
    ckpt = Path(ckpt).resolve()               # 워커는 cwd 가 벤더 폴더라 상대경로가 깨진다
    if not Path(python).exists():
        raise FileNotFoundError(
            f"추론용 파이썬이 없다: {python}\n"
            f"  torch 2.13 · transformers 5.15 가 든 venv 경로를 SITECHECK_DINOV3_PYTHON "
            f"으로 주세요(만드는 법은 README 5절 · 모델 코드는 {REPO} 에 있습니다)")
    if not ckpt.exists():
        raise FileNotFoundError(f"건물 모델 가중치가 없다: {ckpt}")

    out = scene_dir / "out"
    out.mkdir(parents=True, exist_ok=True)
    pj = out / f"{tag}_poly.json"
    t0 = time.time()

    cmd = [str(python), str(WORKER), "--scene", str(scene_dir), "--out", str(pj),
           "--ckpt", str(ckpt), "--crop", str(crop), "--overlap", str(overlap),
           "--input-size", str(input_size), "--threshold", str(threshold),
           "--score-mode", score_mode, "--mask-threshold", str(mask_thr),
           "--min-area", str(min_area), "--iou-thr", str(iou_thr),
           "--ios-thr", str(ios_thr), "--clean-ios-thr", str(clean_ios_thr),
           "--min-side", str(min_side), "--max-aspect", str(max_aspect),
           "--poly-min-area", str(poly_min_area), "--poly-min-iou", str(poly_min_iou),
           "--dp-eps", str(dp_eps), "--angle-tol", str(angle_tol),
           "--min-edge", str(min_edge)]
    if tta:
        cmd.append("--tta")
    if not clean:
        cmd.append("--no-clean")
    if region:
        cmd += ["--region", region if isinstance(region, str)
                else ",".join(str(int(v)) for v in region)]
    if not verbose:
        cmd.append("--quiet")

    env = dict(os.environ,
               CUDA_VISIBLE_DEVICES=str(pick_gpu() if gpu is None else gpu),
               TOKENIZERS_PARALLELISM="false",
               # 설정을 폴더 안에서만 읽는다 — 게이트된 저장소를 받으러 나가지 않는다
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    r = subprocess.run(cmd, cwd=str(REPO), env=env,
                       capture_output=not verbose, text=True)
    if r.returncode:
        tail = ((r.stdout or "")[-1200:] + "\n" + (r.stderr or "")[-1600:]) if not verbose else ""
        raise RuntimeError(f"추론 실패(rc={r.returncode})\n{tail}")
    if not pj.exists():
        raise RuntimeError(f"{pj} 가 없다 — 워커가 아무것도 남기지 않았다")
    if verbose:
        d = json.loads(pj.read_text("utf-8"))
        print(f"  → {pj.name} {len(d['polys'])}동 ({time.time() - t0:.0f}s)", flush=True)
    return pj


def main(argv=None):
    sys.path.insert(0, str(HERE.parents[1]))     # 저장소 뿌리 — 직접 실행할 때만 필요하다
    from sitecheck import settings as config
    ap = argparse.ArgumentParser(description="DINOv3+Mask2Former 추론(폴더 안에서)")
    ap.add_argument("--scene", required=True)
    ap.add_argument("--tag", default="dinov3")
    ap.add_argument("--ckpt", default=str(config.BUILDING_CKPT))
    ap.add_argument("--python", default=str(config.DINOV3_PYTHON))
    ap.add_argument("--crop", type=int, default=config.INFER_DINOV3["crop"])
    ap.add_argument("--overlap", type=int, default=config.INFER_DINOV3["overlap"])
    ap.add_argument("--threshold", type=float, default=config.INFER_DINOV3["threshold"])
    ap.add_argument("--region", default=None)
    ap.add_argument("--gpu", type=int, default=None)
    ap.add_argument("--tta", action="store_true", default=config.INFER_DINOV3["tta"])
    ap.add_argument("--no-tta", dest="tta", action="store_false")
    a = ap.parse_args(argv)
    kw = dict(config.INFER_DINOV3)
    kw.update(crop=a.crop, overlap=a.overlap, threshold=a.threshold, tta=a.tta)
    p = run(a.scene, a.tag, a.ckpt, python=a.python, region=a.region, gpu=a.gpu, **kw)
    print(f"  → {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
