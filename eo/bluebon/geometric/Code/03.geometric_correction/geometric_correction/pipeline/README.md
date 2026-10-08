# eo/bluebon/geometric/Code/03.geometric_correction/geometric_correction/pipeline

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `__init__.py` | Geometric Correction Pipeline Module | — | — |
| `hierarchical_matching.py` | Hierarchical Matching Module | GeoTIFF | PNG 그림 |
| `initial_matching.py` | Initial Matching Module | GeoTIFF | GeoTIFF · 텍스트/로그 |
| `precision_correction.py` | Precision Correction Module | GeoTIFF · 이미지 | GeoTIFF · CSV · PNG 그림 · 텍스트/로그 |
| `preprocessing.py` | Stage 1 Preprocessing Module | GeoTIFF | GeoTIFF · 텍스트/로그 |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate bldseg      # PyTorch · transformers
```

- 환경 정의: [`environment/`](../../../../../../../environment/)
