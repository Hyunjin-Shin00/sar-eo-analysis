"""경로·키·영상 등록부. **이 폴더 밖을 가리키는 것은 전부 여기 한 곳에만 둔다.**"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent          # sitecheck/ — 코드
HERE = PKG.parent                              # 저장소 뿌리 — run.py · 자산 · 결과가 여기 있다
ASSETS = HERE / "assets"
MODELS = HERE / "models"
OUT = HERE / "out"

# 비교분석은 **폴더를 따로 쓴다.** 산출물이 두 종류라 한 폴더에 섞으면 무엇이 무엇인지
# 폴더만 보고 알 수 없다 — 위험분석은 주소마다 한 폴더인데, 비교분석은 주소마다 보고서
# 한 부에 날짜분 두 폴더(`t1/` · `t2/`)가 딸린다. 손보정 길이 이미 그렇게 갈라 두었다
# (`demo/` 3건 · `demo_cmp/` 2건 — [[hand_writting.py]]), 모델 길도 같은 모양으로 둔다.
#
#     out/<주소>/                    위험분석 — 한 촬영일
#     out_cmp/위성_비교분석_<주소>.pdf  비교분석 — 두 촬영일
#     out_cmp/t1/<주소>/ · t2/<주소>/  그 두 날짜분 값(보고서의 재료)
OUT_CMP = HERE / "out_cmp"

# GT 원본이 있는 곳 — **선택이다.** GT 경로([[gt.py]])는 `assets/gt/<장면>.json` 사본을
# 먼저 보고, 없을 때만 여기를 찾는다. 사본이 저장소에 있으므로 보통은 쓰이지 않는다.
SEGLAB = Path(os.environ.get("SITECHECK_SEGLAB", HERE.parent / "seglab"))


def _first(*paths):
    for q in paths:
        if q and Path(q).exists():
            return Path(q)
    return Path(paths[-1])


# **파이프라인 파이썬** — 뿌리의 `.venv`(`requirements.txt` · `uv venv`).
#
# 건물 모델은 여기서 돌지 않는다(아래 `DINOV3_PYTHON`) — 이 값은 그 환경을 못 찾았을 때의
# 마지막 기댈 곳이고, `SITECHECK_PYTHON` 으로 바꿀 수 있다. 예전에는 SAMPolyBuild 가 이
# 환경에서 돌았는데(torch 2.0 · mmcv 2.0) 2026-08-27 에 그 모델을 걷어 냈다.
INFER_PYTHON = _first(os.environ.get("SITECHECK_PYTHON"),
                      HERE / ".venv" / "bin" / "python",
                      sys.executable)

# **건물 모델용 파이썬을 따로 줄 수 있다** — 다만 기본은 본체와 같은 환경이다.
#
# 2026-08-27 에 환경 둘을 하나로 합쳤다. 여기 「합칠 수 없다」고 적혀 있었고 그때는 맞았다 —
# 파이프라인이 torch 2.0 + mmcv 2.0 이었고 mmcv 는 torch 버전에 맞춰 컴파일되는 패키지라
# torch 를 올리면 그 자리에서 깨졌다. 그 mmcv 를 SAMPolyBuild 와 함께 걷어 내고 나니
# 파이프라인 쪽에 torch 를 쓰는 코드가 한 줄도 없어, 막고 있던 것이 사라졌다(README 5절).
#
# **그래도 서브프로세스로 가르는 것은 그대로다** — GPU 메모리와 전역 설정을 본체와 섞지
# 않으려는 것이기도 하다([[vendor/dinov3seg_run.py]]). 그래서 이 값도 남겨 둔다: 모델만 다른
# 환경에서 돌려야 할 날이 오면 `SITECHECK_DINOV3_PYTHON` 하나로 갈라진다. 값이 없고
# `.venv-dinov3` 도 없으면 `INFER_PYTHON`(본체)으로 떨어진다.
#
# 만드는 법은 README 5절. `requirements.txt` 하나로 만들어진다.
DINOV3_PYTHON = _first(os.environ.get("SITECHECK_DINOV3_PYTHON"),
                       HERE / ".venv-dinov3" / "bin" / "python",
                       INFER_PYTHON)


# ── 건물 폴리곤 모델 ──────────────────────────────────────────────────────
# **단일 모델이다.** 예전에는 5-멤버 앙상블(SAMPolyBuild 3 + GCP 2)을 합쳤는데, val 홀드아웃
# (`crop_gumi4` · GT 292동 · ≥20 ㎡ · IoU 0.5)에서 같은 잣대로 다시 재 보니 **단일 v2aug 가
# 앙상블과 같거나 낫다**(2026-08-19 측정, F1 최대점):
#
#     구성                      F1     운용 thr   P       R
#     v2aug 단일 (증강 + TTA×4) 0.774   0.85      0.785   0.764   ← 채택
#     gcp_lowlr 단일            0.772   0.85      0.780   0.764
#     5-앙상블 (합의 재점수)     0.766   0.35      0.765   0.767
#     v2base 단일               0.733   0.88
#
# 앙상블의 이득은 mAP·AR(점수 전 구간의 순위 품질)과 임계값 안정성이었고, **운용 임계값에서의
# F1 은 단일이 지지 않는다.** 경계도 v2aug 가 최고다(PoLiS 0.79 m — 앙상블도 기하는 이 모델에서
# 가져왔다). 면적을 재서 대장과 대조하는 파이프라인이라 경계가 곧 정확도다.
#
# 그래서 멤버 하나만 돌린다 — 추론 비용이 1/5 이고, 점수가 모델 원본 스케일이라 임계값의 뜻이
# 분명하다(앙상블은 백분위 정규화 때문에 0.28 이 무엇인지 설명하기 어려웠다).
#
# 앙상블을 되살리려면 `BUILDING_MODELS` 에 멤버를 더하면 된다.
#
# ── 2026-08-26: 모델을 갈았다 ───────────────────────────────────────────────
# 위의 SAMPolyBuild 이야기는 **그 전 모델의 기록**이다. 지금 도는 것은 DINOv3(동결) +
# Mask2Former 인스턴스 분할기다(`<WORK_ROOT>/building_seg/dinov3_v2` 의 run4).
#
#     백본    facebook/dinov3-vitl16-pretrain-lvd1689m  **동결**(24층 · hidden 1024 · patch 16)
#     머리    facebook/mask2former-swin-base-coco-instance  질의 100→200 확장
#     피라미드 ViT 블록 6·12·18·24 탭 → stride 4/8/16/32 · 채널 [128,256,512,1024] + stride-4 stem
#     점수    mask-IoU 머리가 낸다 (`cls × pred_iou`) — `cls × mask_quality` 가 아니다
#     학습    tile 512 · stride 128 · 회전 0/15/30/45 · image_size 1024 · 20 epoch · best ep11
#
# **갈아 끼운 것은 이 한 줄과 [[steps/s1_building._run_model]] 의 갈림뿐이다.** 산출물 형식
# (`out/<tag>_poly.json` 의 `polys`·`scores`)이 같으므로 임계값·경위도 변환·합치기·귀속·id·
# 그림·보고서는 한 줄도 바뀌지 않았다.
#
# 왜 갈았는지는 사람이 정한 것이고(성능 비교는 seglab 쪽 기록), 여기서는 **무엇으로 갈았는지와
# 어떻게 그대로 돌리는지**만 적는다. 이식이 원본과 같은 것을 낸다는 근거는
# [[vendor/dinov3seg/sitecheck_worker.py]] 머리글의 재현표에 있다(run4 산출물과 폴리곤
# IoU 중앙 0.984 · 면적합 비 1.004).
BUILDING_MODELS = (
    {"tag": "dinov3v2", "kind": "dinov3", "tta": 8, "geom": True,
     "ckpt": MODELS / "building" / "dinov3_v2_run4_best_ep11.pth"},
)

# **갈기 전 모델(SAMPolyBuild)은 걷어 냈다**(2026-08-27, 사용자 결정) — 코드
# (`vendor/sampoly/` · `vendor/sampoly_run.py`) · 가중치(`models/building/best.ckpt` 629 MB) ·
# 그 모델이 남긴 추론 캐시(`assets/scenes/*/out/*__v2aug_*`)를 다 지웠다. 되살릴 일이 생기면
# git 이력에 있다(가중치는 LFS). 아래 F1 표는 **그 모델 안에서의 비교 기록**으로만 남긴다.
#
# 멤버를 둘 이상 넣는 길은 열려 있으나, **점수 스케일이 다른 두 모델을 합치지는 마세요** —
# `_predict` 의 합의 재점수는 백분위 정규화라 임계값의 뜻이 사라진다. 견주려면 tag 를 달리해
# 따로 돌리고 결과를 나란히 놓는 편이 낫다.

ENSEMBLE = {"iou": 0.5, "mode": "consensus"}     # 멤버가 둘 이상일 때만 쓴다

# 기하 담당 = 단일로 돌릴 때 쓰는 그 체크포인트.
BUILDING_CKPT = next(m["ckpt"] for m in BUILDING_MODELS if m.get("geom"))


def available_models():
    """가중치가 실제로 있는 멤버만. 없는 것을 조용히 빼지 않고 몇으로 돌았는지 결과에 적는다."""
    return [m for m in BUILDING_MODELS if Path(m["ckpt"]).exists()]


# 추론 설정(DINOv3+Mask2Former) — **run4 가 실제로 돌았던 값 그대로.**
#
# 이름과 기본값은 원본 `infer.py`·`polygonize.py` 의 것을 그대로 쓴다. 원본에서 어떻게
# 확인했는지:
#
#   `threshold` 0.1   run4 산출물 네 묶음(val · val_tta · namdong · changwon)의 점수 최저가
#                     모두 정확히 0.100 이었다. README 는 0.05 를 권하지만 그 값이 아니었다.
#                     **이 점수는 예측 IoU(`cls × pred_iou`)라 v1 의 포화된 신뢰도와 스케일이
#                     다르다** — 0.5 로 자르면 참인 검출의 대부분이 사라진다(원본 주석).
#   `tta` True        켰을 때만 재현이 맞았다(폴리곤 IoU 중앙 0.912 → 0.984 · 점수 분포 일치).
#                     8개 대칭을 돌려 **맞는 질의끼리만** 평균한다 — 경계를 다듬는 것이고
#                     놓친 건물을 되찾지는 않는다. 값 8 은 몇 방향인지를 적어 둔 것이다.
#   polygonize 쪽     `poly_min_area` 200 px²(=50 ㎡) · `poly_min_iou` 0.70 · `dp_eps` 3.0 은
#                     `polygonize.py` 의 **CLI 기본값**이다(`regularize` 자체 기본값 2.0 과
#                     다르다 — 산출물을 만든 것은 CLI 쪽이다).
#
# **crop 과 input_size 는 다른 값이다.** 창은 512 px 로 자르고 모델에는 1024 로 넣는다(2배) —
# 학습이 본 배율이 그것이다. 원본은 `--tile-size` 하나로 두 값을 함께 정하는데, run4 는 512
# 타일을 미리 잘라 두고 `--tile-size` 를 cfg 의 1024 로 두어 그 상태를 만들었다. 자세한 것은
# [[vendor/dinov3seg/sitecheck_worker.py]] 머리글. `input_size` 0 = 체크포인트 cfg 값(1024).
INFER_DINOV3 = {"crop": 512, "overlap": 256, "input_size": 0,
                "threshold": 0.1, "score_mode": "cls_iou", "mask_thr": 0.5,
                "min_area": 100, "iou_thr": 0.5, "ios_thr": 0.8,
                "clean_ios_thr": 0.6, "min_side": 8.0, "max_aspect": 6.0,
                "tta": True, "clean": True,
                "poly_min_area": 200, "poly_min_iou": 0.70,
                "dp_eps": 3.0, "angle_tol": 20.0, "min_edge": 3.0}

# **영상마다 다른 값** — 그 영상에서만 바꾼다.
#
# 2차 영상(`daegu2` · ssc1 · 06-28)은 1차(`daegu` · ssc8 · 06-18)와 센서도 촬영각도 달라
# 같은 지붕이 더 어둡고 경계가 무르다. 기본값으로 돌리면 **마스크가 지붕 안쪽으로 들어앉고**
# 약한 검출이 임계값 아래로 떨어진다 — 두 촬영일을 견주는 문서에서 그것은 「변화」로 읽힌다.
#
# 여기 두는 것은 **검출 임계값**뿐이다. 호산동 702-5 창에서 재 보면(2026-08-27):
#
#     threshold   2차 검출   1차(31동)와 IoU≥0.4 로 짝
#     0.10 (기본)    25동            24동
#     **0.05**     **27동**        **25동**   ← 채택
#     0.02           29동            25동   (는 것 둘은 헛것이다)
#
# 2차 영상은 같은 지붕이 더 어두워 약한 검출이 임계값 아래로 떨어진다. 0.05 로 내리면 그중
# 하나가 되살아나고, 0.02 까지 내리면 헛것만 는다. 판정 임계값(`score_threshold`)도 같이
# 내려야 한다 — 안 내리면 되살린 검출을 [[steps/s1_building.predict]] 가 다시 잘라 낸다.
#
# **마스크 임계값은 여기 두지 않는다.** 그 값은 영상이 아니라 **물건마다** 달라야 한다 —
# 같은 daegu2 에서 호산동은 0.35 로 내려야 1차와 면적이 맞는데(−70 → −15 ㎡) 신당동은
# 그러면 반대로 벌어진다(+18 → +91 ㎡). 그래서 물건별 손보정에 둔다
# (`hand_writting.TABLE_MODEL` 의 `infer_fix` · 그 표에 측정값이 있다).
INFER_DINOV3_BY_SCENE = {
    "daegu2": {"threshold": 0.05, "score_threshold": 0.05},
}


def infer_for(scene_key):
    """(추론 설정, 판정 임계값) — 영상별 덮어쓰기를 얹은 것."""
    kw = dict(INFER_DINOV3)
    kw.update(INFER_DINOV3_BY_SCENE.get(scene_key) or {})
    thr = kw.pop("score_threshold", None)
    return kw, (SCORE_THRESHOLD if thr is None else thr)


# ── 2026-08-26: 점수의 뜻이 바뀌었다 ────────────────────────────────────────
# 새 모델의 점수는 `cls × pred_iou` 다 — **분류 신뢰도가 아니라 예측 IoU**다(mask-IoU 머리가
# 「이 마스크가 정답과 얼마나 겹칠 것 같은가」를 내고, 거기에 분류 확률을 곱한다). 예전 모델의
# 점수는 포화된 신뢰도라 0.85 근처였고, 새 점수는 잘 잡은 것이 0.8 · 어중간한 것이 0.4 다.
# **그래서 예전 값 0.70 을 그대로 두면 안 된다** — 실측으로 잡힌 GT 의 43 %만 남고 300 ㎡
# 미만은 한 동도 남지 않는다.
#
# 표본 7창(데모·비교분석에 저장된 그 창 · 대구 4 · 대구2차 2 · 남동공단 1 · GT 173동 ·
# IoU 0.5 로 짝지음 · 2026-08-26 측정):
#
#     GT 크기(㎡)     GT수   잡힘   점수 하위10%   25%    중앙
#     20 ~   100       23     8        0.104   0.202   0.342
#     100 ~  300       48    36        0.235   0.319   0.448
#     300 ~ 1000       62    52        0.450   0.629   0.737
#     1000 ~           37    35        0.576   0.657   0.819
#
#     thr     창 전체 P / R / F1        이 지번 안 P / R / F1
#     0.10    0.565 0.757 **0.647**     1.000 1.000 1.000
#     0.20    0.575 0.728   0.643       1.000 1.000 1.000
#     0.30    0.591 0.676   0.631       1.000 1.000 1.000
#     0.50    0.592 0.538   0.564       1.000 1.000 1.000
#     0.70    0.571 0.324   0.413       1.000 0.818 0.900
#
# **이 지번 건물은 0.5 까지 임계값에 둔감하다**(11동 전부 맞고 헛것 없음). 임계값이 실제로
# 가르는 것은 **옆 지번 건물**이고, 그것을 놓치면 이격(A1)이 과소평가된다 — GT 창에 여유를
# 두는 이유와 같다([[gt.rings_in_window]]). 그리고 F1 은 0.10 에서 최대다.
#
# 그래서 **0.10** — 모델 자신의 추론 임계값(`INFER_DINOV3["threshold"]`)과 같은 값이다. 즉
# 지금은 여기서 더 자르지 않는다. 값을 남겨 두는 이유는 두 가지다: `predict()` 의 계약이고,
# 추론 쪽 임계값을 낮춰 볼 때 판정용 임계값을 따로 올릴 자리가 여기이기 때문이다.
#
# **남은 숙제.** 창 전체 정밀도가 0.57 인데, 그 「헛것」의 상당수는 GT 가 그리지 않은 실제
# 구조물(캐노피 · 컨테이너 · 작은 헛간)일 수 있다 — GT 는 학습용으로 그린 것이라 포함 기준이
# 이 파이프라인과 같지 않다. 그림을 놓고 세어 보지 않고는 가를 수 없으므로 여기 적어만 둔다.
SCORE_THRESHOLD = 0.10

# 갈기 전 모델(SAMPolyBuild)의 운용 임계값과 그 근거 — 되살릴 때 이 값으로 돌아가야 한다.
# 판정에 쓰는 운용 임계값 — **모델 원본 점수 스케일**(v2aug 는 0.35 이하를 내지 않는다).
#
# F1 만 보면 0.85 가 최대다(val 홀드아웃 crop_gumi4 · GT 292동). 그런데 F1 이 큰 건물에 눌린
# 값이라 그대로 쓰면 **작은 동이 조용히 사라진다.** 잡힌 GT 를 크기별로 나눠 그 GT 를 잡은
# 예측의 점수를 보면(같은 val 창, 2026-08-19 측정):
#
#     GT 크기(㎡)     GT수   IoU0.5 로 잡힘   점수 하위10%   25%    중앙
#     20 ~   100      14         1            0.62        0.62   0.62
#     100 ~  300      28        23            0.70        0.73   0.80
#     300 ~ 1000     127       112            0.90        0.94   0.96
#     1000 ~         123       108            0.95        0.97   0.97
#
# 300 ㎡ 이상은 0.90 이상으로 나와 임계값에 둔감하다. **100~300 ㎡ 대는 중앙이 0.80, 하위 10%가
# 0.70** 이라 0.85 로 자르면 그 대의 절반이 날아간다 — 실측: 고잔동 524-8(대장 80 ㎡)의 건물이
# 0.719 로 나와 0.85·0.75 에서 모두 탈락해 「건물 0동」이 됐다. 이 파이프라인이 찾는 것이 대장에
# 없는 건물이라 놓치는 쪽이 더 나쁘고, 헛것은 지번 귀속(면적 지분)과 대장 대조가 걸러 낸다.
#
# 그래서 **0.70**. val F1 은 0.774 → 0.730 으로 내려가지만 100~300 ㎡ 대를 살린다.
# 20~100 ㎡ 는 임계값과 무관하다 — 14동 중 1동만 잡힌다(0.5 m/px 의 한계).
_SAMPOLY_SCORE_THRESHOLD = 0.70

# ── 영상 등록부 ───────────────────────────────────────────────────────────
# **새 정사영상은 폴더만 놓으면 잡힌다.** `assets/scenes/<key>/` 에 `*.tif` 와
# `meta.json`(bbox·res_m) 이 있으면 아래 `_discover()` 가 훑어 등록한다 — 이 파일을
# 고칠 필요가 없다. 만드는 법은
# `python -m sitecheck.tools.add_scene --tif 새영상.tif --key <key>`.
# 다른 곳에 둔 영상은 `SITECHECK_SCENES=/경로1:/경로2` 로 더 붙일 수 있다.
#
# 주소가 어느 영상에도 안 들어가면 '영상 없음'으로 낸다 — 없는 것을 있는 것처럼
# 비워 내면 '건물 0동'과 구분되지 않는다.
# **같은 지역의 다른 촬영일**은 키를 따로 둔다(`daegu` · `daegu2`). `scene_for` 는 먼저
# 등록된 것을 고르므로(정렬상 daegu < daegu2) 한 날짜만 쓰는 기존 실행은 그대로 1차 영상을
# 쓴다. 두 날짜를 견주는 비교분석은 `run.py --scene <key>` 로 **명시해서** 고른다 —
# 좌표만으로는 어느 날짜를 원하는지 알 수 없다.
SCENE_NAMES = {"daegu": "대구", "gumi": "구미", "namdong": "남동공단",
               "daegu2": "대구(2차)"}

# **창원은 일부러 뺐다** — 되돌리기 전에 이 이유를 먼저 읽으세요.
# 학습셋(`seglab/poly/datasets_v2`)의 라벨 crop 은 daegu1·daegu2 · gumi1~4 · namdong1
# 일곱 장이고 창원은 한 장도 없다. 창원 주소를 돌리면 결과가 나쁠 때 그것이 파이프라인
# (대장 대조·이격·귀속) 문제인지 미학습 지역의 일반화 실패인지 구분할 수 없다. 지금 이
# 폴더의 용도는 파이프라인 검증이라 그 구분이 안 되는 표본은 넣지 않는다.
# 일반화를 재 보려면 여기 되살리는 대신 seglab 쪽에서 창원 벤치로 따로 재는 것이 맞다.
EXCLUDED_SCENES = {"changwon": "학습 라벨 crop 이 없다 — 파이프라인/일반화 구분 불가"}

SCENE_ROOTS = [ASSETS / "scenes"] + [Path(p) for p in
                                     os.environ.get("SITECHECK_SCENES", "").split(os.pathsep) if p]


def _discover():
    """등록 가능한 장면을 훑는다 — tif(지오레퍼런스) + meta.json(bbox) 둘 다 있어야 한다.

    tif 를 요구하는 이유: 벡터↔픽셀 변환이 tif 의 geotransform 과 CRS 에서 나온다
    (`steps/georef.raw_xform`). bbox 만 있는 옛 SkySat 장면(시화·안산)은 그 변환이
    없어 필지도 대장도 영상에 얹을 수 없다.
    """
    out = {}
    for root in SCENE_ROOTS:
        if not Path(root).is_dir():
            continue
        for d in sorted(Path(root).iterdir()):
            key = d.name
            if not d.is_dir() or key.startswith((".", "_")) or key in out or key in EXCLUDED_SCENES:
                continue
            mp = d / "meta.json"
            if not mp.exists() or not any(d.glob("*.tif")):
                continue
            try:
                m = json.loads(mp.read_text("utf-8"))
            except Exception:                                # noqa: BLE001
                continue
            # 제외는 **영상**을 막는 것이지 폴더 이름을 막는 것이 아니다 — 같은 영상을
            # 다른 폴더명으로 두면 이름 검사만으로는 그냥 통과한다(seglab 의
            # `test_changwon_ortho` 가 그랬다). meta.area 로도 본다.
            if m.get("area") in EXCLUDED_SCENES:
                continue
            if not m.get("bbox"):
                continue
            out[key] = {"ko": SCENE_NAMES.get(key) or m.get("area") or key, "dir": d}
    return out


SCENES = _discover()

# **주소별 손보정은 여기 없다.** 예전에는 도로 방향(`ROAD_SIDE`) · 옆 지번 제외·이동
# (`NEIGHBOR_DROP`·`NEIGHBOR_SHIFT`) · 대장 동 제외(`LEDGER_DROP`) 넷이 이 파일에 있었고,
# 나머지 다섯은 `tools/for_demo.py` 에 있었다. 그래서 **`run.py` 가 그중 넷을 자기도 모르게
# 쓰고 있었다** — 「모델이 스스로 낸 값」이라고 말할 수 없는 상태였다.
#
# 지금은 열 가지가 전부 저장소 뿌리의 [[hand_writting.py]] 한 곳에 있다(열째는 그림 창
# 여백 `win_pad` 로, `draw.py` 에 주소 표로 남아 있던 것이다). 이 파일은 **경로·키·
# 영상 등록부**만 담는다 — 물건마다 달라지는 값이 여기 섞이면 「설정」과 「손보정」이 구분되지
# 않는다. 담는 그릇과 적용 함수는 [[hand.py]].

GIS_BUILDINGS = ASSETS / "gis" / "buildings.gpkg"   # GIS건물통합정보(대장 통합 SHP)

# 데이터 — 큰 자산이라 기본은 심볼릭이다. `python bundle.py --copy` 로 실제 사본을 넣으면
# 폴더 하나로 완전히 자립한다(정사영상 18 GB + GIS건물 4.5 GB).


def scene_meta(key):
    """영상 메타(bbox·크기·해상도). 없으면 None."""
    p = SCENES[key]["dir"] / "meta.json"
    return json.load(open(p, encoding="utf-8")) if p.exists() else None


def scene_for(lon, lat):
    """경위도를 담는 영상 key. 없으면 None — 이 PoC 가 커버하지 않는 지역이다."""
    for k in SCENES:
        m = scene_meta(k)
        if not m:
            continue
        x0, y0, x1, y1 = m["bbox"]
        if x0 <= lon <= x1 and y0 <= lat <= y1:
            return k
    return None


def _env(path, *names):
    """KEY=값 형식 파일에서 키를 읽는다. 환경변수가 있으면 그쪽이 우선."""
    out = {}
    if path.exists():
        for line in path.read_text("utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return {n: os.environ.get(n) or out.get(n, "") for n in names}


def keys():
    """VWORLD_KEY(지오코딩·연속지적도) · DATA_GO_KR_KEY(건축물대장) · OPENAI_API_KEY(야적 판독)."""
    k = _env(ASSETS / ".env.geodata", "VWORLD_KEY", "DATA_GO_KR_KEY")
    k.update(_env(ASSETS / ".env.openai", "OPENAI_API_KEY"))
    return k
