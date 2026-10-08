"""장면(또는 그 일부) → 건물 폴리곤. **`infer.py` 의 함수를 그대로 부른다.**

이 파일은 벤더한 코드에 손대지 않기 위해 있다. 원본의 `infer.py main()` 은 「폴더 안 이미지
전부 → 겹친 그림 + npz」를 내고, `polygonize.py main()` 은 「npz 폴더 → polys.json」을 낸다.
우리가 원하는 것은 「장면의 한 창 → 장면 픽셀 좌표 폴리곤 하나의 목록」이라 입출력이 다르다.
그 **바깥만** 여기서 다시 쓰고, 안쪽(추론·중복제거·청소·폴리곤화)은 원본 함수를 부른다.

    predict_image → clean_instances → polygonize_scene      (전부 원본 그대로)

**크기를 두 값으로 가른다 — 이것이 이 파일의 핵심이다.**

원본 `infer.py` 는 `--tile-size` 하나로 두 가지를 동시에 정한다: 창을 몇 픽셀로 자를지와
모델에 몇 픽셀로 넣을지(`Mask2FormerImageProcessor(size=…)`). 그런데 run4 의 산출물은
그 둘이 **다른** 상태로 나왔다 — 512 px 타일을 미리 잘라 두고(`tile_img.py --size 512
--stride 256`) `--tile-size` 는 체크포인트 `cfg` 의 **1024** 로 두었기 때문이다. 그러면
`predict_image` 의 「이미지가 창보다 작다」 갈래로 들어가 512 짜리 한 장이 1024 로 올라간다.
학습이 본 것이 바로 그것이다(512 crop → image_size 1024 · 2배). 실측으로 확인했다
(2026-08-26 · namdong 12타일 · 아래 「재현」 절).

그래서 여기서는 **창 = 512 · 모델 입력 = 1024** 를 따로 준다. `predict_image` 에는 창 크기를
주고, 프로세서는 `cfg["image_size"]` 로 만든다 — 원본 함수를 한 줄도 고치지 않고 run4 와
같은 배율이 나온다.

창이 512 보다 작으면 **검정으로 채워 512 로 만든다.** 작은 창을 그대로 넣으면 1024 로
올리는 배율이 2배가 아니게 되고(300 px 창이면 3.4배), 그러면 모델이 학습에서 본 지상
해상도와 다른 것을 보게 된다. 채우는 쪽이 낫다 — 이 영상은 nodata 가 검정이고 학습 타일도
회전 뒤 모서리가 검정이라, 검정은 모델이 이미 본 것이다([[augment.rotate_any]] mode="pad").

**재현(2026-08-26).** run4 가 낸 `output/run4/namdong/*_polys.json` 을 이 코드로 다시 만들어
견줬다(12타일 · 원본 436동 · 재현 433동):

    설정                    짝지음   폴리곤 IoU 중앙   면적합 비   점수 중앙(재현/원본)
    tta 없음                 92.9%       0.912         1.020      0.768 / 0.647
    **tta 있음**             97.5%      **0.984**      1.004      0.661 / 0.647

점수 분포가 tta 없이는 계통적으로 높게 나온다 — 그것으로 **run4 가 `--tta` 로 돌았다**는
것을 알았다(tta 는 맞는 질의끼리 평균하므로 의견이 갈리는 만큼 점수가 내려간다). 남은
차이(IoU 0.984)는 GPU 가 달라서 생기는 bf16 수치 차이다(원본 A6000+cu130 · 여기 4090+cu126).

`--threshold` 도 산출물에서 읽었다: 네 묶음 모두 점수 최저가 정확히 0.100 이라 **0.1** 이다
(README 는 0.05 를 권한다 — 그 값이 아니었다).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))          # 벤더한 코드는 평평한 import 다(패키지가 아니다)
Image.MAX_IMAGE_PIXELS = None


def main(argv=None):
    ap = argparse.ArgumentParser(description="장면 한 창 → 건물 폴리곤(장면 픽셀 좌표)")
    ap.add_argument("--scene", required=True, help="assets/scenes/<key> 폴더")
    ap.add_argument("--out", required=True, help="쓸 json 경로")
    ap.add_argument("--ckpt", required=True)
    ap.add_argument("--region", default=None, help="x0,y0,x1,y1 (없으면 전장면)")
    # 창과 모델 입력 — 위 머리글의 그 두 값
    ap.add_argument("--crop", type=int, default=512)
    ap.add_argument("--overlap", type=int, default=256)
    ap.add_argument("--input-size", type=int, default=0, help="0=체크포인트 cfg 값")
    # infer.py 의 이름·기본값 그대로
    ap.add_argument("--threshold", type=float, default=0.1)
    ap.add_argument("--score-mode", default="cls_iou")
    ap.add_argument("--mask-threshold", type=float, default=0.5)
    ap.add_argument("--min-area", type=int, default=100)
    ap.add_argument("--iou-thr", type=float, default=0.5)
    ap.add_argument("--ios-thr", type=float, default=0.8)
    ap.add_argument("--tta", action="store_true")
    ap.add_argument("--no-clean", action="store_true")
    ap.add_argument("--min-side", type=float, default=8.0)
    ap.add_argument("--max-aspect", type=float, default=6.0)
    ap.add_argument("--min-frac", type=float, default=0.15)
    ap.add_argument("--max-hole-frac", type=float, default=0.25)
    ap.add_argument("--open-k", type=int, default=3)
    ap.add_argument("--close-k", type=int, default=5)
    ap.add_argument("--clean-ios-thr", type=float, default=0.6)
    # polygonize.py 의 이름·기본값 그대로(CLI 기본값 — regularize 자체 기본값과 다르다)
    ap.add_argument("--poly-min-area", type=int, default=200)
    ap.add_argument("--poly-min-iou", type=float, default=0.70)
    ap.add_argument("--dp-eps", type=float, default=3.0)
    ap.add_argument("--angle-tol", type=float, default=20.0)
    ap.add_argument("--min-edge", type=float, default=3.0)
    ap.add_argument("--free-form", action="store_true")
    ap.add_argument("--no-corner-restore", action="store_true")
    ap.add_argument("--no-fallback", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    import torch
    from transformers import Mask2FormerImageProcessor

    import build_offline
    from infer import clean_instances, predict_image
    from polygonize import polygonize_scene

    t0 = time.time()
    scene = Path(a.scene).resolve()
    img = np.asarray(Image.open(scene / "scene.png").convert("RGB"))
    ox = oy = 0
    if a.region:
        x0, y0, x1, y1 = (int(v) for v in str(a.region).split(","))
        img = img[y0:y1, x0:x1]
        ox, oy = x0, y0
    H0, W0 = img.shape[:2]

    # 창보다 작으면 검정으로 채운다 — 머리글의 그 이유(배율을 2배로 지킨다).
    pad_h, pad_w = max(0, a.crop - H0), max(0, a.crop - W0)
    if pad_h or pad_w:
        pad = np.zeros((H0 + pad_h, W0 + pad_w, 3), np.uint8)
        pad[:H0, :W0] = img
        img = pad

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, cfg = build_offline.load(a.ckpt, device=device, verbose=not a.quiet)
    size = a.input_size or int(cfg.get("image_size") or a.crop)
    processor = Mask2FormerImageProcessor(
        do_resize=True, size={"height": size, "width": size},
        do_normalize=True, image_mean=[0.485, 0.456, 0.406],
        image_std=[0.229, 0.224, 0.225], do_reduce_labels=False, ignore_index=255)

    stages = predict_image(model, processor, img, device,
                           tile_size=a.crop, overlap=a.overlap,
                           threshold=a.threshold, min_area=a.min_area,
                           iou_thr=a.iou_thr, ios_thr=a.ios_thr, tta=a.tta,
                           mask_thr=a.mask_threshold, return_stages=True,
                           score_mode=a.score_mode)
    insts = stages["dedup"]
    if not a.no_clean:
        insts = clean_instances(insts, max_hole_frac=a.max_hole_frac,
                                open_k=a.open_k, close_k=a.close_k,
                                min_frac=a.min_frac, min_area=a.min_area,
                                min_side=a.min_side, max_aspect=a.max_aspect,
                                iou_thr=a.iou_thr, ios_thr=a.clean_ios_thr,
                                verbose=False)

    # `polygonize.load_npz` 가 npz 에서 만들어 주는 것과 같은 dict — npz 를 거치지 않는
    # 이유는 그 파일이 우리 산출물이 아니기 때문이다(마스크는 bool 그대로 넘어간다).
    dicts = [{"mask": i.mask, "x0": i.x0, "y0": i.y0, "score": i.score} for i in insts]
    polys = polygonize_scene(dicts, img.shape[:2],
                             min_area=a.poly_min_area, min_iou=a.poly_min_iou,
                             dp_eps=a.dp_eps, angle_tol=a.angle_tol,
                             min_edge=a.min_edge, fallback=not a.no_fallback,
                             corner_restore=not a.no_corner_restore,
                             rectilinear=not a.free_form)

    # 창 좌표 → **장면 좌표.** 채워 넣은 자리에서 나온 폴리곤은 버린다(영상이 없던 곳이다).
    rings, scores, dropped = [], [], 0
    for p in polys:
        pts = np.asarray(p["polygon"], np.float64)
        if pts[:, 0].min() >= W0 or pts[:, 1].min() >= H0:
            dropped += 1
            continue
        rings.append([[float(x + ox), float(y + oy)] for x, y in pts])
        scores.append(float(p["score"]))

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "polys": rings, "scores": scores,
        "source": "DINOv3(frozen) + Mask2Former (vendor/dinov3seg) · sitecheck",
        "stats": {"ckpt": Path(a.ckpt).name, "cfg": cfg, "crop": a.crop,
                  "overlap": a.overlap, "input_size": size,
                  "threshold": a.threshold, "score_mode": a.score_mode,
                  "mask_thr": a.mask_threshold, "tta": bool(a.tta),
                  "clean": not a.no_clean, "poly_min_area": a.poly_min_area,
                  "poly_min_iou": a.poly_min_iou, "dp_eps": a.dp_eps,
                  "region": a.region, "window_px": [W0, H0],
                  "padded_to": list(img.shape[1::-1]),
                  "n_raw": len(stages["raw"]), "n_dedup": len(stages["dedup"]),
                  "n_clean": len(insts), "n_poly": len(polys),
                  "n_off_window": dropped, "n_kept": len(rings),
                  "device": device, "torch": torch.__version__,
                  "seconds": round(time.time() - t0, 1)}},
        ensure_ascii=False), encoding="utf-8")
    if not a.quiet:
        print(f"  raw {len(stages['raw'])} → 중복제거 {len(stages['dedup'])} → 청소 "
              f"{len(insts)} → 폴리곤 {len(polys)} → 창 안 {len(rings)}개 "
              f"({time.time() - t0:.0f}s)", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
