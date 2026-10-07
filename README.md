# sar-eo-analysis

**SAR 중심** 위성영상 분석 코드 모음 — 간섭측량(InSAR)으로 지반변위를 재고, 변화탐지로 재난 피해를
가려내고, 지원 소프트웨어가 없는 위성을 쓰려고 센서모델을 직접 세운 작업들의 최종본.
광학·수동 마이크로파 작업도 함께 들어 있습니다.

> SAR-first Earth observation code — InSAR ground deformation, SAR change detection,
> and sensor models written from scratch for satellites no software supports.
> Optical and passive-microwave work included. Final versions only.

분석 결과와 프로젝트 설명은 **[hyunjin-shin00.github.io](https://hyunjin-shin00.github.io)** 에 정리되어 있습니다.
이 저장소에는 코드만 둡니다.

---

## 구조 — 센서 → 위성 → 분석 기법

프로젝트가 아니라 **무엇으로 무엇을 했는가**로 나눴습니다.
같은 기법을 여러 사업에서 썼으면 한곳에 모았고, 쓴 영상이 다르면 분리했습니다.

```
sar/                        능동 마이크로파
  sentinel-1/               C-band · 가장 많이 쓴 위성
    preprocessing/            SLC·GRD 전처리, 스택 코레지   ← 모든 기법의 공통 입구
    insar/                    간섭측량
      sbas/                     분산 산란체, 변위 시계열
      psinsar/                  영구산란체, 도심·구조물
      dinsar/                   단일 간섭쌍, 지진 등 단발 변위
      decomposition/            상승·하강 → 수직·동서 성분
    change-detection/         위상 대신 코히런스·진폭
      coherence/                CCD — 건물 붕괴·침수
      amplitude/                ACD — 코히런스가 없을 때
    water/                    물은 SAR에서 어둡다
      flood/ · oil-spill/ · soil-moisture/
    isce2-patches/            Sentinel-1D 지원 패치
  cosmo-skymed/             X-band 상용 · preprocessing · insar/psinsar
  nextsat-2/                국산 X-band · 지원 SW 없음 → 직접 구현
    sensor-model/             거리-도플러 엄밀센서모델 (step01~13)
    isce2-spoofing/           ISCE2 런타임 패치 우회
    insar/ · change-detection/ · offset-tracking/
  umbra/                    25 cm 상용 · SICD 파싱, σ⁰

eo/                         광학·열적외
  sentinel-2/
    burn-severity/            dNBR 산불 피해등급
    thermal-anomaly/          TAI 제련소 가동 판정
  bluebon/                  자사 초소형 위성 — 센서를 직접 다루는 유일한 모듈
    l0-to-l1a/                원시 패킷 → DN → 복사휘도 → TOA 반사도 → RGB
    radiometric/              복사보정 · 밴드 정합 · 정확도 검증
    geometric/                기하보정 V3 — 특징점 정합, RPC, 웹 UI
    deblur-mtf/               에지법 MTF 측정과 커널 디블러링
    pointing/ · research/
    downstream/               AOD · 연무제거 · 해색(적조) · 초해상화

passive-microwave/          구름·극야 무관, 해상도 낮음
  sea-ice/                  SIC · SIT · 표류 (OSI-SAF · NSIDC · SMOS)
  soil-moisture/            SMAP

applications/               위성 산출물 → 판정·경보·보고
  subsidence-warning/ · arctic-route/ · disaster-damage/
  dam-monitoring/ · rail-hazard/ · underwriting/

common/                     다운로드 · 유틸 · 시각화
environment/                conda 환경 정의
docs/projects/              인수인계·방법론 문서
```

**각 디렉터리에 `README.md` 가 있고, 그 안에 파일별 역할 · 입력 · 출력 표**가 있습니다.
브라우징할 때 그 폴더가 뭘 받아서 뭘 내놓는지 바로 보입니다.

---

## 어디서부터 볼까

| 하려는 일 | 시작점 |
|---|---|
| 지반변위를 재고 싶다 | [`sar/sentinel-1/insar/`](sar/sentinel-1/insar/) — SBAS와 PS 중 무엇을 쓸지부터 |
| 재난 피해를 가리고 싶다 | [`sar/sentinel-1/change-detection/coherence/`](sar/sentinel-1/change-detection/coherence/) |
| 홍수 범위를 내고 싶다 | [`sar/sentinel-1/water/flood/`](sar/sentinel-1/water/flood/) — Edge-Otsu |
| 지원 SW 없는 위성을 쓰고 싶다 | [`sar/nextsat-2/sensor-model/`](sar/nextsat-2/sensor-model/) — 거리-도플러부터 직접 |
| 위성 영상을 처음부터 만들고 싶다 | [`eo/bluebon/l0-to-l1a/`](eo/bluebon/l0-to-l1a/) — 원시 패킷부터 반사도까지 |
| 안 된 기록이 궁금하다 | [`docs/projects/`](docs/projects/) — 재현 실패 · 탈상관 대조실험 |

### 기법 고르기

| | SBAS | PS-InSAR | CCD / ACD | Offset Tracking |
|---|---|---|---|---|
| **보는 것** | 위상 | 위상 | 코히런스·진폭 | 진폭 상관 |
| **유리한 곳** | 분산 산란체(농지·나지) | 영구산란체(도심·구조물) | 산란 구조가 바뀐 곳 | 큰 변위 |
| **변위 감도** | mm/yr | mm/yr | 정성 | m 급 |
| **탈상관 시** | 불가 | 불가 | **동작** | **동작** |

X-band는 식생·사구에서 수 일 내 탈상관합니다. 그때는 위상 기반(SBAS·PS)이 아니라
오른쪽 두 칸으로 가야 합니다 — 그 근거는 [`docs/projects/taean-sar-methodology.md`](docs/projects/taean-sar-methodology.md) 에 있습니다.

---

## 시작하기

```bash
git clone https://github.com/Hyunjin-Shin00/sar-eo-analysis.git
cd sar-eo-analysis

python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env     # 자격증명을 채운다 (.env 는 커밋되지 않는다)
```

ISCE2, snaphu, ESA SNAP, StaMPS, MintPy, PyGMTSAR 는 pip 로 설치되지 않습니다.
`requirements.txt` 하단과 [`environment/`](environment/) 를 참고하세요.

### 자격증명

모든 자격증명은 **환경변수**로만 읽습니다. 코드에 값을 직접 적지 마세요.

```python
EDL_USER = os.environ.get("EARTHDATA_USER", "")
```

필요한 키 목록은 [`.env.example`](.env.example) 에 있습니다.

---

## 이 저장소의 규칙

- **최종본만 둔다.** 중간본은 올리지 않습니다. 목적이 다른 두 버전(운영용 vs 벤치마크 평가용)은 이름을 달리해 둘 다 둡니다.
- **데이터는 올리지 않는다.** GeoTIFF·NetCDF·HDF5·SAFE·산출 그림은 `.gitignore` 로 제외합니다.
- **자격증명은 올리지 않는다.** 환경변수로만 읽습니다.
- **노트북은 출력을 지우고 올린다.**
- **고객사 정보는 올리지 않는다.** 기관명·계약 정보·사내 서버 경로가 코드와 문서에 들어가지 않게 합니다.

경로는 `<DATA_ROOT>`(데이터), `<WORK_ROOT>`(작업), `$CONDA_PREFIX`(conda 환경)로 일반화돼 있습니다.

---

## 외부 도구

- **StaMPS** 파이썬 포팅본과 **snaphu** 바이너리는 제3자 저작물이라 포함하지 않았습니다.
  [`sar/sentinel-1/insar/psinsar/stamps_patches/`](sar/sentinel-1/insar/psinsar/stamps_patches/) 에는
  제가 적용한 패치만 있습니다. 원본은 [StaMPS](https://github.com/dbekaert/StaMPS) 에서 받으세요.
- **ISCE2**, **MintPy**, **PyGMTSAR**, **SNAP** 은 별도 설치가 필요합니다.
- `sar/nextsat-2/isce2-spoofing/` 은 ISCE2 설치본을 **고치지 않고** 런타임에 패치합니다.
- BlueBON 쪽에서 제외한 제3자 라이브러리(RoMa · LightGlue · rpcfit · ResShift · Swin2-MoSE ·
  deblur-l0 · spdlog)는 [`eo/bluebon/THIRD_PARTY.md`](eo/bluebon/THIRD_PARTY.md) 에 정리했습니다.

## 라이선스

[MIT](LICENSE) — 단, 위 외부 도구들은 각자의 라이선스를 따릅니다.
