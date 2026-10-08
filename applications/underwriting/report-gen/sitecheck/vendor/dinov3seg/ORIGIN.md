# vendor/dinov3seg — DINOv3(동결) + Mask2Former 건물 분할기 사본

`building_seg/dinov3_v2`(원본 작업 폴더 `<WORK_ROOT>/building_seg/dinov3_v2`)에서 **추론에
필요한 코드만** 가져왔음. 2026-08-26 이관.

## 담은 것 — 원본과 바이트가 같음

| 파일 | 무엇 | 왜 필요한가 |
|---|---|---|
| `infer.py` | 타일 슬라이딩 · 경계 인스턴스 제거 · 전역 중복제거 · 청소 · 점수 조합 · TTA | 추론 절차 그 자체 |
| `polygonize.py` | 마스크 → 폴리곤(비겹침 분할 · 직교 정규화 · 자유형 대체) | sitecheck 이 필요한 것이 폴리곤이다 |
| `heads.py` | mask-IoU 머리(`MaskIoUHead` · `attach_maskiou_head` · `predict_iou`) | 점수를 이 머리가 낸다 |
| `train_dinov3_mask2former.py` | `build_model` · `DINOv3Pyramid` · `expand_queries` · `resolve_taps` | **체크포인트를 모델로 다시 세우는 코드가 여기 있다** |
| `runlog.py` | `resolve_ckpt` · `cli_flags` | `infer.py` 가 `--ckpt` 로 런 디렉터리를 받는 길 |
| `losses.py` · `augment.py` | 학습용 손실·증강 | 추론에 쓰이지 않지만 `train_dinov3_mask2former.py` 가 모듈 최상위에서 import 한다 |
| `UPSTREAM_README.md` | 원본 README(54 KB) | 인자마다의 권장값과 그 근거가 여기 있다 — 값을 바꾸기 전에 읽으세요 |

**고치지 않음.** 우리 쪽 절차는 전부 아래 두 파일에 있고, 원본을 건드리면 위 폴더와 diff 로
대조할 수 없음. 사본이 진짜인지는 원본 `__pycache__/*.pyc` 와 바이트코드를 견줘 확인함
(코드객체 49/49 · 70/70 · 18/18 일치).

## 우리가 더한 것 — 이 폴더에서 sitecheck 것은 셋뿐임

* `build_offline.py` — `build_model` 의 **오프라인 쌍둥이**. 원본은 구조를 세울 때
  허깅페이스에서 사전학습 가중치를 함께 받아 오는데(`from_pretrained`), 그 가중치는 바로 다음
  줄에서 체크포인트가 전부 덮어씀. 그래서 설정만 읽어 세우고(`from_config`) 가중치는
  체크포인트에서만 가져옴. **DINOv3 저장소는 gated 라** 그러지 않으면 이 폴더가 토큰 없이
  돌지 않음. `strict=True` 적재가 구조가 같다는 증명임.
* `sitecheck_worker.py` — 「장면의 한 창 → 장면 픽셀 좌표 폴리곤」. 원본 CLI 는 「폴더 안
  이미지 전부 → 겹친 그림 + npz」라 입출력이 다름. **안쪽은 원본 함수를 그대로 부름.**
* `hf/` — 구조를 세우는 데 필요한 설정 두 벌(`config.json` · `preprocessor_config.json`,
  각 몇 KB). **가중치는 담지 않는다** — 체크포인트에 다 있음.

부르는 곳은 [[../dinov3seg_run.py]] 이고, 그것을 부르는 곳은
[[../../steps/s1_building.py]] `_run_model` 한 군뎀.

## 빼 온 것

`pst.py`(HoliTracer 2차 폴리곤 정련) · `vertex.py`(이미지 조건 꼭짓점 정련) ·
`eval.py`(COCO mask AP · boundary IoU) · `selftest.py`. 앞 둘은 **각자 따로 학습한 가중치가
있어야** 돌고 run4 산출물은 그것들을 태우지 않았다(`output/run4` 에는 `_masks.npz` 와
`_polys.json` 만 있다). 뒤 둘은 지표와 자체시험이라 추론 경로에 없음. 나중에 태우려면 원본
폴더에서 가져오면 되고, 그때 필요한 가중치도 그쪽에 있음.

## 가중치

`models/building/dinov3_v2_run4_best_ep11.pth` (1.32 GB · LFS) — 원본 `runs/run4/best_ep11.pth`
그대로. 790개 텐서에 **동결 백본까지 다 들어 있다**(그래서 오프라인으로 세울 수 있다).
`epoch 11 · val 21.289 · val_ap 0.3826 · select_by ap`.

체크포인트 안의 `cfg` 가 구조를 말해 준다 — `image_size 1024 · num_queries 200 · taps auto ·
use_stem True · maskiou 256`. `infer.py` 도 이 값을 읽어 모델을 세움.

**재배포는 백본 라이선스를 따름.** 이 체크포인트에는 `facebook/dinov3-vitl16-pretrain-lvd1689m`
의 가중치가 동결된 채로 들어 있다(허깅페이스에서 gated 로 제공되는 그 모델). 머리는
`facebook/mask2former-swin-base-coco-instance` 에서 warm start 함. 저장소를 밖으로 낼 때는
그 두 모델의 조건을 확인하세요.

## 실행 환경

**담지 않았음.** torch 2.13 · transformers 5.15 가 필요하고, 저장소의 `requirements.txt` 가
그것을 담음. 2026-08-27 까지는 `requirements-dinov3.txt` 로 만든 별도 venv 였는데 — 그때
`.venv` 가 torch 2.0 + mmcv 2.0(그 전 모델)이라 한 환경에 담기지 않았다 — 그 mmcv 를 걷어
내고 환경을 하나로 합쳤음. `settings.DINOV3_PYTHON`(환경변수 `SITECHECK_DINOV3_PYTHON`)은
남아 있고, 값이 없으면 본체 파이썬으로 떨어짐.

원본 학습 환경은 torch 2.13.0+**cu130** 인데 이 장비 드라이버(535 · CUDA 12.2)로는 GPU 를
못 잡아 **cu126** 으로 깔았음. torch 버전은 같다 — 자세한 것은 `requirements.txt` 머리글.

## 이 사본이 원본과 같은 것을 내는지

원본이 낸 `output/run4/namdong/*_polys.json` 을 이 코드로 다시 만들어 견줬다(12타일 ·
원본 436동 · 재현 433동 · 2026-08-26):

| 설정 | 짝지음 | 폴리곤 IoU 중앙 | 면적합 비 |
|---|---|---|---|
| tta 없음 | 92.9 % | 0.912 | 1.020 |
| **tta 있음** | **97.5 %** | **0.984** | **1.004** |

점수 분포가 tta 없이는 계통적으로 높게 나오는 것으로 **run4 가 `--tta` 로 돌았다**는 것을
알았음. 남은 차이는 GPU 세대가 달라서 생기는 bf16 수치 차이다(원본 A6000+cu130).
`--threshold` 도 산출물에서 읽었다(네 묶음 모두 점수 최저가 정확히 0.100 → **0.1**).
재현에 쓴 값과 그 근거는 [[sitecheck_worker.py]] 머리글에 그대로 적어 두었음.
