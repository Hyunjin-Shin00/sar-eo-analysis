# smelter-tai — 제련소 열원 활동 모니터링

Sentinel-2 SWIR 밴드로 용광로의 열 신호를 잡아 제련소 가동 여부를 원격 판정한다.

## 원리

SWIR(B11 1.6 µm, B12 2.2 µm)은 상온 지표에는 거의 반응하지 않지만,
수백~수천 K의 고온체에서는 플랑크 복사의 단파장 꼬리가 올라와 신호가 잡힌다.
이 대비를 지수화한 것이 **TAI (Thermal Anomaly Index)** 다.

## 파일

| 파일 | 역할 |
|---|---|
| `notebooks/tai.ipynb` | 단일 날짜 TAI 산출 · 임계값 설정 |
| `notebooks/tai_sum.ipynb` | 전체 관측일 누적 TAI(TAIsum) 맵 — 장기 가동 패턴 |
| `notebooks/false_color.ipynb` | SWIR 위색 합성 — 고온 지점 육안 확인 |
| `geocode_smelters.py` | 제련소 주소/좌표 목록 → AOI 폴리곤 생성 보조 |

대부분 Google Earth Engine Python API로 동작한다.

```bash
pip install earthengine-api
earthengine authenticate
```

## 적용 지역

- **철강**: 독일(딜링엔, 잘츠기터, 브레멘, HKM, TK), 호주(와이알라, 켐블라)
- **구리**: 칠레, 중국 — TAIsum 2018–2025

## 검증

가동 기록(GT)과 TAI 시계열의 상관으로 확인했다.
보조 지표로 **Sentinel-5P 대류권 NO₂ 칼럼**을 함께 봤다 — 열 신호와 배출 신호가
같은 방향으로 움직이는지 확인하는 용도.

## 한계

- **구름.** 광학 기반이라 흐리면 시계열이 끊긴다. Sentinel-3 SLSTR 열적외와 엮으면
  보완될 텐데 시도하지 못했다.
- **GT 확보.** 기업은 가동률을 공개하지 않는다. 검증 설계 자체가 작업의 절반이었다.
- **AOI 품질.** 용광로·슬래그장·원료야적장을 공정 지식으로 구분해 수동으로 그렸다.
  이 경계가 틀리면 TAI 집계가 통째로 흔들린다.
