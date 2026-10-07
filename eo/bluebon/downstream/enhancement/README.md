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
