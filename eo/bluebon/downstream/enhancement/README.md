# eo/bluebon/downstream/enhancement

화질 개선 실험 (모델 본체는 제3자라 미포함).

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `enhance_lotte.py` | JPG 위성영상 품질 개선 파이프라인 (lotte.jpg) | JPG | — |
| `enhance_png.py` | PNG 위성영상 품질 개선 파이프라인 (tehran.png) | PNG | — |
| `realesrgan_sr.py` | Real-ESRGAN Super-Resolution | JPG | — |
| `resshift_sr.py` | ResShift Super-Resolution (NeurIPS 2023) | JPG · PNG | — |
| `swin2_mose_sr.py` | Swin2-MoSE Super-Resolution | 이미지 | — |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate bldseg      # PyTorch · transformers
```

- 환경 정의: [`environment/`](../../../../environment/)

### 상수를 고쳐 돌리는 스크립트

- 명령줄 인자가 없음. 파일 위쪽 상수를 대상 자료에 맞게 바꾼 뒤 `python <파일>` 로 실행함

| 파일 | 고칠 상수 | 현재값 |
|---|---|---|
| `realesrgan_sr.py` | `INPUT_IMAGE` | `lotte_enhanced_0.01_0.1_0.003_0.9.jpg` |
|  | `OUTPUT_IMAGE` | `lotte_realesrgan_sr.jpg` |
| `swin2_mose_sr.py` | `INPUT_IMAGE` | `lotte_enhanced_0.01_0.1_0.003_0.9.jpg` |
|  | `OUTPUT_IMAGE` | `lotte_swin2mose_sr.jpg` |

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `enhance_lotte.py`, `enhance_png.py`, `resshift_sr.py`
