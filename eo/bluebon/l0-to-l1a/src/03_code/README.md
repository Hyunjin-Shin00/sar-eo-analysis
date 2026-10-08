# eo/bluebon/l0-to-l1a/src/03_code

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`06_Read_Raw_bin_file/`](06_Read_Raw_bin_file/) |  |
| [`sub/`](sub/) |  |

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `01_DN_to_L.py` | DN → 복사휘도(Radiance) 변환 — 암전류·PRNU 보정 포함, 전 밴드 일괄 | GeoTIFF · CSV | GeoTIFF · Excel · 텍스트/로그 |
| `01_DN_to_L_band.py` | DN → 복사휘도 변환, 단일 밴드 단위 처리판 | GeoTIFF · CSV | GeoTIFF · Excel · NumPy · 텍스트/로그 |
| `01_DN_to_L_darkTest.py` | 암전류(dark) 시험 영상 전용 DN → 복사휘도 변환 | GeoTIFF · CSV | GeoTIFF · Excel · 텍스트/로그 |
| `01_DN_to_L_manual.py` | 보정계수를 수동 지정해 DN → 복사휘도 변환 (시험·디버그용) | GeoTIFF · CSV | GeoTIFF · Excel · 텍스트/로그 |
| `02_L_to_TOAR.py` | 복사휘도 → TOA 반사도 변환 (태양천정각·일-지 거리·Thuillier F0 적용) | GeoTIFF · CSV | GeoTIFF · 텍스트/로그 |
| `RGB.py` | 밴드 합성 → RGB 영상 생성 (스트레치·감마 보정) | GeoTIFF · CSV | GeoTIFF · Excel · 텍스트/로그 |
| `bluebon_radiance_to_TOAR_for_IPB.py` | IPB 납품 포맷용 복사휘도 → TOA 반사도 변환 | GeoTIFF · CSV | GeoTIFF · 텍스트/로그 |
| `plot_m.py` | 밴드별 통계·히스토그램 진단 그림 | GeoTIFF · CSV | GeoTIFF · Excel · 텍스트/로그 |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../../../environment/)

- 명령줄 인자가 없는 스크립트 — 파일 안의 입력 경로를 확인한 뒤 실행함: `01_DN_to_L.py`, `01_DN_to_L_band.py`, `01_DN_to_L_darkTest.py`, `01_DN_to_L_manual.py`, `02_L_to_TOAR.py`, `RGB.py`, `bluebon_radiance_to_TOAR_for_IPB.py`, `plot_m.py`
