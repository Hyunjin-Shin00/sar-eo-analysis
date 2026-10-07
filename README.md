# eo-analysis

위성영상 분석 코드 모음 — SAR · 광학 위성으로 재난, 환경, 산업활동을 정량화한 작업들의 최종본.

> Earth observation analysis code — SAR and optical processing for disaster response,
> environmental monitoring and industrial activity. Final versions only.

분석 결과와 프로젝트 설명은 **[hyunjin-shin00.github.io](https://hyunjin-shin00.github.io)** 에 정리되어 있습니다.
이 저장소에는 코드만 둡니다.

---

## 모듈

| 디렉터리 | 내용 | 주요 센서 |
|---|---|---|
| [`flood-sar/`](flood-sar/) | Edge-Otsu 자동 침수 탐지 파이프라인 | Sentinel-1 GRD |
| [`insar/`](insar/) | InSAR — CSK 처리, PS-InSAR, SBAS 산사태 | Sentinel-1 SLC, COSMO-SkyMed |
| [`n2-sensor-model/`](n2-sensor-model/) | 국산 X-band SAR 엄밀센서모델 기하보정 | NEXTSat-2 |
| [`taean-sar/`](taean-sar/) | 해안사구 다중기법 — InSAR · OT · ACD | NEXTSat-2, Sentinel-1 |
| [`smelter-tai/`](smelter-tai/) | 제련소 열이상지수(TAI) 산출 | Sentinel-2 SWIR |
| [`arctic-sea-ice/`](arctic-sea-ice/) | 북극 해빙 농도·두께·표류, 항로 개방 분석 | OSI-SAF, NSIDC, SMOS, GFW |
| [`bluebon-calibration/`](bluebon-calibration/) | 초소형 위성 전처리 · 포인팅 오차 분석 | 자사 CubeSat |
| [`wildfire/`](wildfire/) | dNBR 산불 피해등급 분류 | Sentinel-2 |
| [`oil-spill/`](oil-spill/) | SAR dark-spot 기름유출 탐지 | Sentinel-1 |
| [`umbra-sar/`](umbra-sar/) | 초고해상도 SAR — SICD 파싱, σ⁰ 산출 | Umbra (25 cm) |
| [`data-download/`](data-download/) | 영상 자동 수집 유틸 | Sentinel-2, Landsat 8/9 |

**눈여겨볼 곳** — [`n2-sensor-model/`](n2-sensor-model/)은 상용·공개 SAR 소프트웨어가
전혀 지원하지 않는 국산 위성을 쓰기 위해 거리-도플러 엄밀센서모델을 처음부터 구현한 것입니다.
[`taean-sar/`](taean-sar/)은 같은 위성에 세 가지 기법을 적용하고, **왜 잘 안 되는지**까지
물리적으로 규명한 기록입니다.

---

## 시작하기

```bash
git clone https://github.com/Hyunjin-Shin00/eo-analysis.git
cd eo-analysis

python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env     # 자격증명을 채운다 (.env 는 커밋되지 않는다)
```

ISCE2, snaphu, ESA SNAP 은 pip 로 설치되지 않습니다. `requirements.txt` 하단 안내를 참고하세요.

### 자격증명

모든 자격증명은 **환경변수**로만 읽습니다. 코드에 값을 직접 적지 마세요.

```python
EDL_USER = os.environ.get("EARTHDATA_USER", "")
```

필요한 키 목록은 [`.env.example`](.env.example) 에 있습니다.

---

## 이 저장소의 규칙

- **최종본만 둔다.** 작업 중 생긴 v1~v7 중간본은 올리지 않습니다. 목적이 다른 두 버전(예: SAFE zip 입력용과 벤치마크 GeoTIFF 입력용)은 각각 이름을 달리해 둘 다 둡니다.
- **데이터는 올리지 않는다.** GeoTIFF, NetCDF, HDF5, SAFE, 산출 그림은 `.gitignore` 로 전부 제외합니다.
- **자격증명은 올리지 않는다.** 환경변수로만 읽습니다.
- **노트북은 출력을 지우고 올린다.** 커밋 전에 `Cell → All Output → Clear` 또는 `nbstripout`.
- **고객사 정보는 올리지 않는다.** 코드와 문서에 기관명·계약 정보·사내 서버 경로가 들어가지 않게 합니다.

경로 표기는 `<DATA_ROOT>`(데이터 루트), `<WORK_ROOT>`(작업 루트), `$CONDA_PREFIX`(conda 환경)로
일반화해 두었습니다. 실행 시 현지 경로로 바꿔 쓰세요.

---

## 외부 도구 관련

- `insar/psinsar/` 에는 ISCE2 `stackSentinel` 실행 래퍼와 PS 추출 스크립트만 두었습니다.
  StaMPS 파이썬 포팅본과 snaphu 는 제3자 저작물이라 포함하지 않았으니
  각 업스트림에서 직접 받으세요.
- SNAP GPT 그래프(XML)를 쓰는 스크립트는 SNAP이 별도 설치되어 있어야 동작합니다.
- `taean-sar/` 의 S1 위상 InSAR는 공식 ISCE2 topsApp 2.6.3 을 씁니다. 나머지 기법은 자체 구현입니다.

## 라이선스

[MIT](LICENSE) — 단, 위 외부 도구들은 각자의 라이선스를 따릅니다.
