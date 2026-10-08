# eo/bluebon/geometric/Code/03.geometric_correction/geometric_correction/utils

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `__init__.py` | Utilities Module | — | — |
| `device.py` | Device Selection Utility | — | — |
| `geo.py` | 지리공간 유틸리티 모듈 | — | — |
| `io.py` | 영상·RPC·메타데이터 입출력 | GeoTIFF | — |
| `visualization.py` | Utility Functions Module | GeoTIFF | PNG 그림 |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate bldseg      # PyTorch · transformers
```

- 환경 정의: [`environment/`](../../../../../../../environment/)
