# BlueBON 전처리·응용 자료 정리

> 작성일: 2026-10-07
> 대상: Telepix BlueBON 위성(8밴드 push-broom: PAN + MS1~MS7)의 L0 → L1A → L1C 전처리 전체, 다운스트림 응용 코드, 대표 영상 샘플
> 이 문서는 패키지에 들어 있는 코드를 직접 분석해 작성했음. 코드에서 직접 확인한 사실과 해석을 구분해 두었고, 해석이거나 확인이 필요한 부분에는 **[추정]**, **[검토 필요]**를 붙였음.

---

## 목차

0. [패키지 구성과 빠진 자료](#0-패키지-구성과-빠진-자료)
1. [센서 기본 사양](#1-센서-기본-사양)
2. [처리 레벨과 전체 흐름](#2-처리-레벨과-전체-흐름)
3. [L0 생성: Raw bin 디코딩 (bin2png)](#3-l0-생성-raw-bin-디코딩-bin2png)
4. [L1A 생성 (구 운영판): prep `01_DN_to_L_band.py`](#4-l1a-생성-구-운영판-prep-01_dn_to_l_bandpy)
5. [복사보정 (신 파이프라인 v5): `02_Radiometric_Correction`](#5-복사보정-신-파이프라인-v5-02_radiometric_correction)
6. [절대 복사보정, TOA 반사율, 대리검증](#6-절대-복사보정-toa-반사율-대리검증)
7. [기하보정 (L1A → L1C): `03_Geometric_Correction/V3`](#7-기하보정-l1a--l1c-03_geometric_correctionv3)
8. [보조 전처리 자료 (`04_Auxiliary`)](#8-보조-전처리-자료-04_auxiliary)
9. [운영 절차: 다운로드, 업로드, FEE/CEM, 미션 시트](#9-운영-절차-다운로드-업로드-feecem-미션-시트)
10. [실행 환경](#10-실행-환경)
11. [알려진 문제와 주의사항](#11-알려진-문제와-주의사항)
12. [다운스트림 응용 (`06_Downstream_Applications`)](#12-다운스트림-응용-06_downstream_applications)
13. [영상 샘플 (`07_Sample_Data`)](#13-영상-샘플-07_sample_data)
14. [코드 최신판 검증 결과](#14-코드-최신판-검증-결과)

---

## 0. 패키지 구성과 빠진 자료

```
BlueBON_Full_Package_20261007/
├── 00_README_BlueBON_정리.md               ← 이 문서
├── 01_L0_to_L1A_prep/                     ← L0 디코딩, 구 L1A 복사보정, 업로드·운영 스크립트
│   ├── src/                               (loop.sh, run_band.sh, merge_bands.py, upload*.sh …)
│   │   ├── 03_code/                       (01_DN_to_L*.py, 02_L_to_TOAR*.py, sub/, 06_Read_Raw_bin_file/)
│   │   └── sharepoint/                    (SharePoint 미처리 영상 자동 다운로드)
│   ├── fee_cem/                           (텔레메트리 FEE/CEM 온도 추출)
│   ├── L1C_batch/run_preprocess.sh        (L1A → L1C 일괄 실행)
│   ├── docs/                              (작업 절차 메모 txt, tilt_info)
│   └── environment_prep.yml
├── 02_Radiometric_Correction/             ← 현행 복사보정 v5 (dark/flat PRNU/δ + 밴드정합 + radiance/TOAR)
│   ├── README.md, doc/                    (PIPELINE, RADIANCE_TOAR, REGISTRATION, REGISTRATION_ACCURACY)
│   ├── src/ (pipeline.py = 최신), src/radcal/ (절대보정·RadCalNet 검증)
│   ├── ref/master/                        (밴드별 dark/flat PRNU/δ 보정 계수, 실제 사용본)
│   ├── ref/radcal_sample/                 (RadCalNet La Crau 샘플 파일)
│   └── results_sample/                    (장면별 registration_shifts.csv, La Crau 검증 보고서)
├── 03_Geometric_Correction/
│   ├── V3/                                ← 현행 기하보정 (S2 참조 매칭 → RPC → 정사보정)
│   ├── V3_sample_run_20260708/            (실행 로그, GCP json, 시각화 샘플)
│   └── 260317_previous_version/           (이전 버전 코드, 비교용)
├── 04_Auxiliary/
│   ├── bluebon_L0_L1_research/            (S2 교차검교정, affine 밴드정합, Rayleigh LUT, 줄무늬 보정 등 연구 코드)
│   ├── pointing/                          (TLE 기반 지향오차 along/across 계산)
│   └── deblur_MTF/                        (L0 blind deblurring, MTF 측정)
├── 05_Reference_Data/
│   ├── sensor_calibration/                (FM1 지상검교정 PRNU CSV 390MB, SRF, Thuillier F0, 밴드별 gain 표)
│   ├── docs/                              (패킷 정의서 PDF, La Crau 논문, SatRev API 문서)
│   └── mission_sheet/                     (BlueBON Mission 시트 백업)
├── 06_Downstream_Applications/            ← L1 이후 응용 코드
│   ├── AOD/                               (BlueBON L1C 에어로졸 광학두께, MAIAC/S2 검증)
│   ├── Dehazing/                          (영상기반 연무 제거 src_dehaze, Windows GUI 소스)
│   ├── OceanColor_HAB/                    (해색 IOP 역산, 적조 탐지)
│   ├── SR/                                (사내 SR 서버 호출 스크립트와 예시)
│   └── Enhancement/                       (BM3D/Real-ESRGAN/ResShift/Swin2-MoSE 영상 향상)
└── 07_Sample_Data/                        ← 대표 영상 샘플 (약 15GB)
    ├── A_260928_103939_Drvenik_raw_to_L1A/   (raw bin → L0 → L1A(prep))
    ├── B_260708_074748_L0_to_L1C/            (L0 → L1A(v5) → L1C)
    ├── C_LaCrau_20260528_radcal/             (복사보정 대리검증 장면)
    └── D_Radiometric_Reference_Raw/          (dark/flat 참조 원본, RadCalNet LCFR 전체)
```

### 0.1 의도적으로 뺀 자료

| 분류 | 뺀 자료 | 이유 / 받는 방법 |
|---|---|---|
| **인증정보** | GEE 서비스계정 키(`Code/auth/*.json`), `ee-hyunjin-*.json`, `.keys.txt`, rclone/OAuth 토큰 | 공유 금지. 각자 발급해 `V3/Code/auth/ee-service-account-key.json` 위치에 두면 됩니다 |
| **복호화 키가 들어 있는 파일** | `bin2png` C++ 소스(`main.cpp`)와 빌드 바이너리·오브젝트, `read_raw_bin00.py`, `unpack-tpx.sh`, `pack-tpx.sh`, `unpack-img.sh` | 영상 AES-256-CTR key/IV와 텔레메트리 복호화 비밀번호가 평문으로 들어 있음. 필요하면 **담당자에게 보안 채널로 따로 요청**하세요. 알고리즘은 3장에서 설명합니다 |
| **영상 데이터 (대부분)** | 원본 `data/`(약 1TB, 6200여 장면 파일) 등 전체 영상 | 1.2TB가 넘어 대표 장면 4세트만 `07_Sample_Data`에 넣었습니다(13장) |
| **딥러닝 가중치, 참조 다운로드** | RoMaV2/DINOv3/Real-ESRGAN 가중치(`*.pt/*.pth`), S2 모자이크, DEM | 실행할 때 자동으로 받거나 공개 저장소에서 받을 수 있습니다 |
| **빌드 산출물** | DehazingGUI `build/`, `dist/`(3.2GB), node_modules | 소스로 다시 빌드할 수 있습니다 |
| **비밀번호 하드코딩 파일** | `AOD/BlueBON/data/download_s2_l2a.py` | Copernicus 계정 비밀번호가 평문으로 들어 있어 뺐음. CDSE 다운로드는 각자 계정으로 하세요 |
| **실험용 중복본** | `prep/tmp`, `test/` 사본, deblur 결과 영상 | 원본과 같은 내용입니다 |

---

## 1. 센서 기본 사양

### 1.1 밴드 구성

| idx | 이름 | 파일명 | SRF 가중 중심 (nm) | FWHM (nm) | 공칭 중심/대역폭 (nm) | 운영 TDI | 대역폭 BW (nm, 코드값) | F0 (W/m²/µm) |
|---|---|---|---|---|---|---|---|---|
| 0 | PAN | `_0_gray`, PAN | 616.0 | 246 | 625 / 250 | 2 | 250 | 1653 |
| 1 | Blue | `_1_gray`, MS1 | 483.2 | 63 | 490 / 65 | 4 | 65 | 2000 |
| 2 | Green | `_2_gray`, MS2 | 562.4 | 35 | 560 / 35 | 8 | 35 | 1819 |
| 3 | Red | `_3_gray`, MS3 | 664.6 | 30 | 665 / 30 | 8 | 30 | 1514 |
| 4 | RedEdge1 | `_4_gray`, MS4 | 704.8 | 14 | 705 / 15 | 16 | 15 | 1421 |
| 5 | RedEdge2 | `_5_gray`, MS5 | 739.2 | 13 | 740 / 15 | 16 | 15 | 1292 |
| 6 | RedEdge3 | `_6_gray`, MS6 | 781.9 | 19 | 783 / 20 | 16 | 20 | 1166 |
| 7 | NIR | `_7_gray`, MS7 | 836.6 | 101 | 842 / 115 | 4 | 115 | 1032 |

- SRF 원본은 `05_Reference_Data/sensor_calibration/SpectralResponseFunction.xlsx`임. 400–1000 nm 범위에 1 nm 간격이고, 우측 블록 "Total optical transmission × QE × ff"가 실제 응답임.
- F0는 Thuillier(2003) 태양복사(`Thuillier_F0.dat`, µW/cm²/nm에 ×10을 해서 W/m²/µm로 환산)를 SRF로 가중평균한 값임.
  - 계산식: `F0_b = Σ F0(λ)·SRF_b(λ) / Σ SRF_b(λ)`
- 공칭값은 제원표(bluebon_band.png)에서 왔고, SRF 가중 중심은 실측 SRF에서 계산한 값임. Blue와 NIR에서 차이가 나므로 **문서에서는 둘을 구분해서 쓰세요**.

### 1.2 검출기와 촬영 조건

- 검출기 폭: **4096 화소**(across-track)
- 라인 수: L0는 **16000 라인 고정**으로 저장됨. 실제 촬영 라인이 적으면 나머지는 0임.
- 양자화: **12 bit** (0–4095)
- TDI별 포화 DN: TDI1 = 1023, TDI2 = 2026, TDI4 = 4032, TDI8·16 = 4095
- Line rate: 운영값 **666** (코드 기본값 `lp=666`)
- 밴드 촬영 순서(초점면 배치 순서): **Blue → Green → Red → PAN → NIR → RE1 → RE2 → RE3**
  - 이 순서 때문에 밴드 간 변위가 Red에서 멀어질수록 단조롭게 커집니다(5.4절).
- TDI 설정은 미션 시트 R열 `Band [PAN,MS1..7]`에 문자열로 적혀 있습니다(예: `"2,4,8,8,16,16,16,4"`). 4밴드 모드는 `[0,4,8,8,0,0,0,4]`처럼 쓰고, 0은 미취득 밴드임.
  - **주의:** 코드는 이 값을 영상 메타데이터에서 읽지 않고 **하드코딩**합니다(11장 참고).
- 지상 해상도: 약 4.8 m (L1C 기준)
- 궤도: 경사각 약 97.4°, 고도 약 495–500 km의 태양동기궤도. TLE NORAD 62688임. [추정]

---

## 2. 처리 레벨과 전체 흐름

### 2.1 처리 레벨 정의

| 레벨 | 파일 | 내용 | 생성 코드 |
|---|---|---|---|
| raw | `capture-YYMMDD_HHMMSS.bin00…0b`, `.tlm.tpx??` | 다운링크 원본임. 64 MiB 단위 조각이고, 영상은 AES-256-CTR, 텔레메트리는 AES-256-CBC로 암호화되어 있습니다 | 위성 |
| **level-0** | `YYMMDD_HHMMSS_<b>_gray.tiff`, `_<b>.png` | 밴드별 12 bit DN, 4096×16000, uint16 | `bin2png` |
| **level-1A** | `bb_l1a_YYYYMMDD_HHMMSS_{8,4,3}band.tiff`, `bb_l1a-rgb_*.png` | 복사보정과 밴드정합을 거친 8밴드 스택임. 좌표계는 없습니다 | prep `01_DN_to_L_band.py` + `merge_bands.py` (구판) / `radiometric_correction/src/pipeline.py` (v5, 현행) |
| **level-1C** | `bb_l1c_YYYYMMDD_HHMMSS_8band.tiff` (+ 세그먼트별 `.RPB`) | 정사보정 결과. UTM, 4.8 m 격자 | `Geometric_Correction_V3/Code/Full_processing_v2.py` |

> 이력: 예전에는 L0를 "level-1A", L1A를 "level-1B"(`bb_l1b_`)라고 불렀음. `rename_levels.sh`로 현재 명칭으로 바꿨음.

### 2.2 전체 흐름

```
[다운링크] SharePoint TelePIX/00_LEOPS/01_downlinked/YYYYMMDD_<target>.tar.xz|zip
   │  (sharepoint/sp_download_unprocessed.py 로 자동 다운로드 가능)
   ▼
[L0]  run_band.sh: 압축해제 → cat *.bin* → bin2png → YYMMDD_HHMMSS_<0..7>_gray.tiff
   ▼
[L1A] 복사보정 + 밴드정합
   ├─ (구) prep/03_code/01_DN_to_L_band.py : FM1 지상검교정 gain/offset + 장면기반 PRNU + 정수 shift 정합
   │        → merge_bands.py → bb_l1a_*_8band.tiff (12bit 정규화)
   └─ (현행 v5) radiometric_correction/src/pipeline.py :
            (raw − dark_ref)·flat_PRNU − δ_persistent  → 서브픽셀 정합 + jitter/회전 보정
            → TOA radiance (f32) [+ 선택: TOA reflectance]
   ▼
[L1C] Geometric_Correction_V3/Full_processing_v2.py --input bb_l1a_*.tiff --lat --lon
        Top/Center/Bottom 3분할 → Sentinel-2 + Copernicus DEM + EGM2008 다운로드
        → SuperPoint+LightGlue 초기매칭 → 2차 다항식 1차 보정
        → RoMaV2 정밀매칭 → GCP → RPC 피팅(rpcfit) → RPC 정사보정(UTM 4.8 m) → 모자이크
   ▼
[검증] RadCalNet La Crau 대리검증 (radcal/), 정합정확도, pointing 오차(along/across)
```

---

## 3. L0 생성: Raw bin 디코딩 (bin2png)

> 관련 파일: `01_L0_to_L1A_prep/src/run_band.sh`, `03_code/06_Read_Raw_bin_file/telepix-bin2png-cpp-*/` (Readme, makefile, package.sh, check_tiff.py)
> 패킷 정의 원문: `05_Reference_Data/docs/SS_Packet Identification Document.pdf`
> ⚠ `main.cpp`(C++ 디코더 본체)와 Python 리더 `read_raw_bin00.py`는 **복호화 키가 들어 있어 패키지에서 뺐습니다**. 아래는 그 동작을 설명한 것임.

### 3.1 run_band.sh가 하는 일

1. **압축 해제**
   - `.zip`은 `bsdtar --strip-components=1`로 풂.
   - `.tar.xz`는 `tar -xJf … --strip-components=3`로 풂. tar 내부 경로가 `srv/payload/downlink/capture-…`이기 때문임.
2. **조각 결합**: `cat ${datdir}/*.bin* > capture-YYMMDD_HHMMSS.bin`. 조각은 `.bin00`~`.bin0b`처럼 16진수 접미사가 붙음.
3. **디코딩**: `bin2png <bin> <dir>/YYMMDD_HHMMSS 16000`
4. **밴드 수 확인 후 복사보정 호출**: 생성된 tiff 개수가 8, 4, 3, 2 중 하나이면 `python 01_DN_to_L_band.py <dir> <개수>`를 실행함.

### 3.2 패킷 구조 (리틀엔디언)

| 오프셋 | 크기 | 내용 |
|---|---|---|
| 0 | 2 | Sync `0x53 0x53` ("SS") |
| 2 | 1 | Flags. 암호화된 라인 데이터는 `0xC3` |
| 3 | 1 | Packet type |
| 4 | 3 | Payload length (24 bit LE) |
| 7 | 1 | Sub-packet |
| 8 | N | Payload |
| 8+N | 4 | CRC32 (zlib, 헤더 8 B + payload 대상) |

Packet type:

| 값 | 의미 |
|---|---|
| `0x00` | Session Start |
| `0x01` | Session End |
| `0x02` | Scene Start |
| `0x03` | Exposure Start (imager time 8 B) |
| **`0x04`** | **Line Data** |
| `0x07` | Time Sync (imagerTime, flag, platformTime) |
| `0x08` | Time Sync PPS |
| `0x80` | User Ancillary |
| `0xA1` | Imager Configuration |
| `0xA3` | Imager Telemetry |
| `0x0B` | CCSDS 압축 스트림 |
| `0xA6` | Compression Info |

### 3.3 Line Data 복호화와 언패킹

- payload 전체를 **AES-256-CTR**로 복호화함. key와 IV는 고정값이며 담당자에게 받아야 함.
- 복호화한 payload의 구조:

| 바이트 | 내용 |
|---|---|
| [0] | spectral band (0=PAN, 1..7=MS1..7) |
| [4..6] | line number (24 bit LE) |
| [8..9] | line length |
| [11] | encoding (`0x03` = 12 bit) |
| [12..] | packed 12 bit 화소. 4096화소면 6144 B |

- **12 bit 언패킹**은 3바이트에 2화소가 들어 있는 구조임.
  - `p0 = b0 | (b1 & 0x0F) << 8`
  - `p1 = (b1 >> 4) | b2 << 4`
- CRC가 맞을 때만 `img[band][line]`에 씀.

### 3.4 출력

- `<prefix>_<b>_gray.tiff`: 16 bit 무압축, 값 범위 0–4095. **CRC 오류 라인과 누락 라인은 0**임.
- `<prefix>_<b>.png`: 품질 확인용임. 정상 라인은 회색, **CRC 오류 라인은 빨강**, **누락 라인은 파랑**으로 표시됨.
- 콘솔에 밴드별 누락 라인 수와 CRC 오류율이 찍히고, 마지막에 `PASS : Decrypt a bin file` 또는 `FAIL`이 출력됨.
- `bin2png.log`(spdlog)에 LineData, ExposureStart, TimeSync가 기록됨. 이 로그는 계속 덧붙여지므로 주기적으로 지워야 합니다(현재 약 5.9 GB).
- 두 소스 버전의 차이: `86038fbd7142`(최신)은 **촬영된 밴드만 출력**하고 64 bit 시간 캐스팅 버그를 고쳤음. `f74b033ac075`는 8밴드를 모두 출력함.
- 빌드에는 `-lssl -lcrypto -lpng -lz -ltiff`가 필요하고 C++17을 씀. Readme와 makefile을 참고하세요.

### 3.5 텔레메트리 (`.tlm.tpx??`)

- 조각을 이어 붙인 뒤 **마지막 64 B(SHA-256 hex)로 무결성을 검증**하고, `openssl enc -d -aes-256-cbc -pbkdf2`로 복호화함.
- 복호화 결과는 `timestamp,level,a,b,c,message` 형식의 CSV 텍스트임. 9.3절의 FEE/CEM 온도 추출에 씀.

---

## 4. L1A 생성 (구 운영판): prep `01_DN_to_L_band.py`

> 관련 파일: `01_L0_to_L1A_prep/src/03_code/01_DN_to_L_band.py`, `merge_bands.py`, `05_Reference_Data/sensor_calibration/FM1_mean_output_PRNU_check.csv`
> 위치: `run_band.sh`가 자동으로 호출하는 **현재 일상 운영 경로**임. 더 정밀한 신판은 5장의 v5 파이프라인임.

### 4.1 실행

```bash
conda activate prep
cd 01_L0_to_L1A_prep/src
./loop.sh                      # data/ 아래 새 압축파일 전부: run_band.sh <archive> 16000 → upload.sh → upload4GDrive.sh
# 또는 단건
python 03_code/01_DN_to_L_band.py <L0 디렉터리> <8|4|3|2>
```

인자별 밴드와 TDI(하드코딩):

| 인자 | 밴드 | TDI |
|---|---|---|
| 8 | PAN, MS1..7 | 2,4,8,8,16,16,16,4 |
| 4 | MS1,2,3,7 | 4,8,8,4 |
| 3 | MS1,2,3 | 4,8,8 |
| 2 (야간) | PAN, MS7 | 16,16 |

### 4.2 지상검교정 자료 (FM1 PRNU CSV)

- 파일: `FM1_mean_output_PRNU_check.csv` (390 MB, 9240행 × 4106열). 2024-05-27~29 적분구로 측정했음.
- 열 구성: `BAND, Direction, Line rate, TDI, Temperature, Radiant intensity, radiance, lmap_level, Date, mean, 0..4095`
  - `lmap_level` 0~20은 적분구 광원 단계이고, **0은 암흑(dark)**임.
  - `radiance`는 해당 단계의 밴드 적분 복사휘도임.
  - `0..4095`는 검출 화소별 평균 DN임.
- 측정 조건: Line rate 500~1000 (11종), TDI 1/2/4/8/16

### 4.3 처리 단계

1. **밴드 간 이동량 추정** (`pixel_shift`)
   - MS1을 기준으로 각 밴드를 `phase_cross_correlation(upsample=10)`해서 정수 (dy, dx)로 반올림함. 야간 모드는 MS7이 기준임.
   - 결과는 `shift_px.npy`에 저장됨. 예: PAN(−26,13), MS2(−5,2), MS3(−14,7), MS4(−39,21), MS5(−46,25), MS6(−54,29), MS7(−32,17)
2. **포화 마스크**: TDI별 포화 DN과 같은 화소를 표시함.
3. **보정계수 산출** (`radiometric_cal_par`)
   - CSV에서 (밴드, Line rate=666, TDI)에 해당하는 행을 고름.
   - 포화 plateau 행(첫 행부터 `mean` 값이 같은 행들)과 마지막 dark 행은 회귀에서 뺌.
   - Dark `D_b(x)`는 lmap_level 0 행의 화소별 DN임.
   - **화소별 선형회귀**(4096회): `radiance = G_b(x)·(DN − D_b(x)) + B_b(x)`
4. **Dark 보정**: `DN − D_b(x)`
5. **Gain/Bias 적용**: `G_b(x)·(DN−D) + B_b(x)`
6. **대역폭 나누기**: `÷ BW_b` → 분광 복사휘도
7. **포화 화소 처리**: 해당 밴드 포화 화소들의 최대 복사휘도로 채움.
8. **정합과 크롭** (`ms_matching`)
   - `ndimage.shift`로 정수 이동함.
   - |shift|가 가장 큰 밴드를 기준으로 한쪽 가장자리만 잘라냅니다(예: 4096×16000 → 4067×15946).
9. **장면기반 PRNU** (`prnu_calibration`)
   - 열 평균 `m(x)`를 구하고 `g(x) = mean(m)/m(x)`를 계산함.
   - `g'(x) = g(x) / MA₂₁(g)(x)`로 저주파는 남기고 화소 간 고주파 편차만 제거함.
   - `L_p = L·g'(x)`

최종 식:

```
L_b(x,y) = g'_b(x) · [ G_b(x)·(DN_b(x,y) − D_b(x)) + B_b(x) ] / BW_b
```

화소 평균 gain 요약(Line rate 666, `05_Reference_Data/sensor_calibration/BlueBON_metadata.xlsx`, 화소별 값은 `_per_pixel.npz`):

| TDI | PAN | MS1 | MS2 | MS3 | MS4 | MS5 | MS6 | MS7 |
|---|---|---|---|---|---|---|---|---|
| 2 | 8.750 | 10.731 | 8.046 | 7.700 | 8.610 | 10.239 | 14.480 | 17.762 |
| 4 | 4.371 | 5.372 | 4.046 | 3.863 | 4.318 | 5.139 | 7.358 | 8.882 |
| 8 | 2.216 | 2.668 | 2.055 | 1.961 | 2.156 | 2.578 | 3.770 | 4.497 |
| 16 | 1.114 | 1.409 | 1.064 | 1.041 | 1.180 | 1.375 | 2.219 | 2.306 |

→ gain은 TDI에 거의 반비례합니다(gain ∝ 1/TDI). **TDI를 잘못 넣으면 결과가 수 배 어긋납니다**.

### 4.4 출력 (`<L0 dir>/radiometric/`)

| 파일 | 내용 |
|---|---|
| `MS{b}_DN_dark_rc_p_float32.tiff` | **실제 분광 복사휘도 (float32)**, 좌우반전 적용 |
| `MS{b}_DN_dark_rc_p.tiff` | ⚠ 밴드별 **min–max 정규화 후 0–4095로 스케일한 uint16**. 복사휘도가 아닙니다 (표시·배포용) |
| `DN_dark_rc_cs0.01_99.999_gm2.2_pc_v.png` | RGB(MS3/MS2/MS1) 미리보기. 백분위 클리핑 후 감마 2.2 |
| `rgb_statistics.xlsx` | 밴드별 Min/Max/Mean/Std, 포화화소 수, shift, dark/radiance 통계 |

이어서 `merge_bands.py`가 `MS*_DN_dark_rc_p.tiff`를 합쳐 `bb_l1a_YYYYMMDD_HHMMSS_{N}band.tiff`를 만듦. 밴드 설명은 `PAN, Blue, Green, Red, RedEdge1, RedEdge2, RedEdge3, NIR`임. **따라서 구판 L1A 8band 파일도 12 bit 정규화값임.**

### 4.5 스크립트 변형

| 파일 | 용도 / 차이 |
|---|---|
| `01_DN_to_L_band.py` | **운영판**. 밴드 수 인자, 야간 모드, `shift_px.npy` 저장 |
| `01_DN_to_L.py` | 초기판. 8밴드 고정, TDI [16,4,8,8,16,16,16,16] |
| `01_DN_to_L_manual.py` | 야간·특수 촬영용. TDI 전부 16 (`run_nightOb.sh`) |
| `01_DN_to_L_darkTest.py` | dark를 CSV 대신 관측 암흑영상으로 빼는 테스트 |
| `02_L_to_TOAR.py` / `_ori` | 복사휘도 → TOA 반사율 실험판. 파이프라인에 연결되어 있지 않고 Windows 경로가 하드코딩되어 있음. 6.2절 참고 |
| `bluebon_radiance_to_TOAR_for_IPB.py` | 같은 계산을 IPB 제공용으로 만든 판 [추정] |
| `make_rgb_png.py`, `03_code/RGB.py` | RGB PNG 재생성. RGB.py에는 green 채널에 blue를 쓰는 버그가 있습니다 |

---

## 5. 복사보정 (신 파이프라인 v5): `02_Radiometric_Correction`

> 최신 실행본은 **`src/pipeline.py`**(2026-08-08)임. 상세 문서는 같은 폴더의 `README.md`, `doc/PIPELINE.md`, `doc/REGISTRATION*.md`, `doc/RADIANCE_TOAR.md`에 있음.
> 구판(4장)과의 핵심 차이는 세 가지임. ① 참조 계수(dark/flat/δ)를 **사전에 고정 생성**하고, ② 정합을 **서브픽셀 + jitter/회전 모델 + 단일 리샘플**로 하며, ③ 절대 gain은 **밴드 스칼라**만 씀.

### 5.1 최종 보정식

```
DN_corr(r,c) = (raw(r,c) − dark_ref[c]) × flat_prnu[c] − δ_persistent[c]        (열 단위, raw 열공간에서 수행)
   → 밴드정합 (RGBN anchor, 평행이동 + jitter/회전 필드, 단일 remap)
   → 공통 crop → 좌우 flip
L_b   = DN_corr · gain_b(TDI, line rate) / BW_b                                (TOA 분광 복사휘도)
ρ_b   = π · L_b / (F0_b · cos θs) / d_r,    d_r = 1 + 0.033·cos(2π·DOY/365)     (선택: TOA 반사율)
```

- 입력: L0 `YYMMDD_HHMMSS_{0..7}_gray.tiff` (16000×4096, uint16)
- 참조 파일 이름: band0은 `PAN`, 1~7은 `MS{n}`

### 5.2 단계 구성

| 단계 | 내용 | 스크립트 | 실행 시점 |
|---|---|---|---|
| R1 | dark_ref(MS1~7) 생성 (+ 잔차 PRNU 창21, 현재 미사용) | `make_correction_ref.py` | 참조를 갱신할 때 |
| R2 | PAN dark 생성 | `make_pan_ref.py` | 〃 |
| R3 | **flat PRNU**(full-width) 생성 | `make_flat_prnu.py` | 〃 |
| R4 | **δ_persistent**(창51) 생성 + leave-one-out 검증 | `make_delta_persistent.py` | 〃 |
| R4' | 밴드별 적응형 δ (실험, 미채택) | `make_delta_adaptive.py` | 사용하지 않음 |
| R5 | 참조 검증 | `verify_correction_ref.py` | 선택 |
| **P1** | **장면 처리: 보정 → 정합 → crop/flip → radiance(/TOAR) → RGB, shifts.csv** | **`pipeline.py`** | 장면마다 |
| P2 | 기존 DN 8밴드 → radiance/TOAR 변환 | `radcal/dn_to_radiance.py --convert` | 선택 |
| V1 | RadCalNet La Crau 대리 gain 산출 | `radcal/run_lcfr_calib.py` | 검증 |
| V2 | 파이프라인 TOAR와 RadCalNet 비교 보고서 | `radcal/scene_report.py` | 검증 |

### 5.3 참조 계수 생성 (`ref/master/`)

밴드마다 아래 파일이 있으며, 모두 길이 4096의 열 벡터임.

| 파일 | 형식 |
|---|---|
| `{rn}_dark_ref.dat` | 텍스트 4096줄 |
| `{rn}_prnu_flat_coef.dat` | 헤더 1줄 + 4096값 |
| `{rn}_delta_persistent.dat` | 헤더 1줄 + 4096값 |

#### (1) Dark reference: `make_correction_ref.py`, `make_pan_ref.py`

- 입력: 야간 원양 촬영 dark 세션 2개(`260606_190315`, `260424_114919`)
- 계산: `dark_ref[c] = mean_session( mean_line(raw_s[:, c]) )`. 라인 방향 단순 평균을 세션끼리 다시 평균함.
  - docstring에는 sigma-clip이라고 적혀 있지만 **실제 코드는 단순 평균**임. 그 효과도 0.01 DN 미만임.
- 두 세션의 밴드 평균 차이는 1% 이내입니다(재현성 확인).
- dark 평균은 TDI에 거의 비례합니다: PAN(TDI2) ≈129, Blue·NIR(TDI4) ≈215, Green·Red(TDI8) ≈410, RE1~3(TDI16) ≈835 DN.
  → **TDI나 line rate 설정이 바뀌면 dark를 다시 만들어야 함.**

#### (2) Flat PRNU: `make_flat_prnu.py` (채택)

- 입력: Libya-4 PICS(사막 표준지) 촬영 `260607_094318`
- 계산:
  ```
  sig  = median_line(Libya_raw) − dark_ref
  gain = mean(sig) / sig            (창 없이 full-width flat-field)
  ```
- 검출소자 PRNU와 across-track vignetting(약 5.8%)을 함께 곱셈으로 평탄화함. Libya 기준으로 vignetting 5.8%가 0.0%가 되었음.
- 한계: PAN은 Libya에서 포화되어 flat ≈ 1, 즉 사실상 무보정임. 그만큼 PAN의 열 패턴은 δ에 많이 남음.

#### (3) δ_persistent: `make_delta_persistent.py` (채택)

- 입력: 바다를 포함한 5장면(Hormuz, GBR, Khark, Sohae, Bushehr)
- 계산:
  ```
  corr = (raw − dark)·flat
  rm   = corr.mean(axis=1)                         # 라인별 평균
  dk   = corr[ rm ≤ percentile(rm, 12) ]           # 가장 어두운 12% 라인 = 바다
  r    = hp( median_col(dk), k=51 )                # hp(x) = x − movavg(x, 51)
  δ    = mean_scenes(r)                            # 장면 성분은 상쇄되고 검출기 고정 가산패턴만 남음
  ```
- 검증(leave-one-out): 한 장면을 빼고 만든 δ를 그 장면에 적용했을 때 전 밴드에서 std가 37~48% 줄었고, 악화된 사례는 없었음.
- 창을 51로 제한한 이유: 200~800 px의 넓은 밴딩은 장면마다 부호가 바뀌고(Green), Red·NIR에서는 실제 해양 신호이기도 해서 고정 벡터로 보정할 수 없기 때문임.

master 계수 통계:

| 밴드 | dark 평균 (DN) | flat std | δ std (DN) |
|---|---|---|---|
| PAN | 128.6 | 0.41% | 7.31 |
| Blue | 213.3 | 1.98% | 1.81 |
| Green | 409.3 | 1.56% | 2.17 |
| Red | 411.6 | 1.26% | 1.82 |
| RE1 | 835.0 | 3.44% | 1.77 |
| RE2 | 838.0 | 4.58% | 1.62 |
| RE3 | 831.5 | 2.78% | 1.51 |
| NIR | 219.6 | 1.96% | 1.42 |

### 5.4 밴드 정합 (`pipeline.py`)

상수:
- `CAP_ORDER = [1,2,3,0,7,4,5,6]` (촬영 순서)
- `RGBN = [1,2,3,7]`
- `UPSAMPLE = 10` (0.1 px 정밀도)
- `JIT_WIN = 1200`, `JIT_STEP = 400`, `JIT_SMTH = 500`, `NX_BLK = 7`
- `MAX_CHAIN_SHIFT = 64 px`

처리 순서:

1. **복사보정 적용** (`load_corrected`): float32로 `(raw − dark)·flat − δ`를 계산함.
2. **High-pass 위상상관** (`pcc`)
   - `im − Gaussian(σ=3)`로 고역통과한 뒤 `phase_cross_correlation(upsample_factor=10)`을 함.
3. **인접쌍 체인** (`chain_shifts`)
   - 촬영 순서상 인접한 밴드끼리 이동량을 구해 누적합니다: `S[b] = S[ref] + pcc(ref, b)`
   - 인접쌍 shift가 64 px를 넘으면 실패로 봄. 그때는 직전 신뢰 밴드의 값을 물려받고, 다음 밴드는 그 신뢰 밴드와 직접 상관(bridge)함.
   - **완전 포화 밴드**(`min==max`)는 정합에서 빼고 crop만 적용함. RGBN 밴드가 포화이면 종료함.
4. **Anchor 선택**
   - `anchor = argmin_{a∈RGBN} max_{b∈RGBN} ‖S[b]−S[a]‖`. 대부분 **Red**가 선택됨.
   - 각 밴드의 이동량: `apply_shift[b] = S[b] − S[anchor]`
5. **잔차 필드 (jitter + 회전 + keystone)** (`residual_field`, collin 모델)
   ```
   dy(r,c) = ay(r) + by(r)·(c − W/2)
   dx(r,c) = ax(r) + bx(r)·(c − W/2)
   ```
   - 1200행 윈도우를 400행 간격으로 이동하면서, 윈도우마다 across-track 7블록을 PCC합니다(텍스처 ≥ 0.4·std, |s| ≤ 8).
   - 블록 결과를 1차 직선으로 맞춰 절편(ay, ax: jitter)과 기울기(by: 회전/yaw, bx: 스케일/keystone)를 구함.
   - 행 방향으로 median(3) → 보간 → Gaussian(σ=500 행) 순서로 평활함. 표본이 부족하면 평행이동만 적용함.
6. **단일 리샘플** (`field_warp`)
   - `out[r,c] = map_coordinates(img, [r − tot_dy, c − tot_dx], order=1)`
   - 원본에서 한 번만 보간하므로 이중 보간 블러가 생기지 않음.
7. **공통 crop과 flip**
   - 전 밴드의 최대 변위만큼 상하좌우를 자릅니다(예: 16000×4096 → 15986×4078).
   - 그 다음 `np.fliplr`로 좌우를 뒤집음.

`registration_shifts.csv` 형식(`results_sample/*/radiometric_v5/`):

```
# anchor=Red (RGBN 중심) ; jitter=collin(회전+keystone)
# output shape (band,H,W)=(8, 15986, 4078) ; crop margin rows+-7 cols+-9
band,name,shift_dy,shift_dx
1,Blue,-0.1000,1.2000
...
```

- `shift_dy`, `shift_dx`는 평행이동 체인 값(px)만 담고 있음. **jitter와 회전 필드는 기록되지 않음.**
- 예시 (La Crau 0528): Blue (−0.1, 1.2), PAN (−1.1, −1.0), NIR (1.3, −2.1), RE3 (3.1, −4.5)
- 예시 (Bushehr 0721): RE3 (−25.4, −77.2). off-nadir가 크면 변위도 커짐.

**정합 정확도** (`doc/REGISTRATION_ACCURACY.md`, 정상 8장면): 평균 **0.47 px**임. 밴드별로는 Blue 0.24, Green 0.21, PAN 0.27, RE1 0.38, RE2 0.64, RE3 0.90, NIR 0.63 px임.

### 5.5 산출물 (`<장면>/radiometric_v5/`)

| 파일 | 내용 |
|---|---|
| `bb_l1a_20{stem}_8band_f32.tiff` | **TOA 분광 복사휘도 float32 8밴드** (정량 분석은 이 파일을 쓰세요) |
| `bb_l1a_20{stem}_8band.tiff`, `MS{0..7}_DN_dark_rc_p.tiff` | 장면별 min–max 정규화 12 bit (표시용). 이름에 `_DN_`이 있지만 DN이 아닙니다 |
| `bb_l1a-ref_20{stem}_8band_f32.tiff` | TOA 반사율 (`--to-reflectance --sza` 옵션을 줬을 때) |
| `bb_l1a-rgb_20{stem}.png` | 보정 DN으로 만든 RGB(3/2/1). 백분위 0.01–99.999, 감마 2.2 |
| `registration_shifts.csv` | 위 5.4절 |

- 저장 방식: rasterio, deflate 압축, `transform = Affine(1,0,0,0,−1,0)`, CRS 없음
- DN 그대로 보존한 산출물이 필요하면 `pipeline_dnonly_backup.py`를 쓰세요.

### 5.6 실행

```bash
conda activate prep
cd 02_Radiometric_Correction/src           # 상대경로 때문에 src에서 실행
python3 pipeline.py <장면 디렉터리>          # 기본: flat + δ + 정합 → radiance
python3 pipeline.py <장면> --to-reflectance --sza <태양천정각deg>
#   옵션: --no-delta  --out-name <dir>  --tdi 2,4,8,8,16,16,16,4  --lp 666
#   ※ --prnu-mode residual 은 ref/master에 잔차 PRNU 파일이 없어 동작하지 않습니다
bash test_run.sh                            # flist.txt 목록 일괄 처리 (TDI/lp 기본값으로 돌아감에 주의)

# 참조 재생성 (스크립트 안의 <WORK_ROOT>/prep/data/... 경로를 먼저 수정해야 함)
python3 make_correction_ref.py; python3 make_pan_ref.py; python3 make_flat_prnu.py; python3 make_delta_persistent.py
python3 verify_correction_ref.py
```

### 5.7 버전 비교

| 파일 | 보정식 | 출력 | 비고 |
|---|---|---|---|
| `pipeline_20260723.py` | (raw−dark)·잔차PRNU(창21). PAN은 무보정 | f32/u16 | 최초 통합판 |
| `pipeline_dnonly_backup.py` | (raw−dark)·flat − δ | **uint16 DN 보존** | DN 전용 |
| `pipeline_v5.py` | 위와 같음 | radiance(+TOAR) | v5 확정판 |
| **`pipeline.py`** | 위와 같음 | radiance(+TOAR) | **최신**. 포화 밴드 처리, 체인 bridge, crop 이상 감지 추가 |

### 5.8 보조 스크립트

- `apply_to_observation*.py`, `apply_fullstrip*.py`: 초기 적용 테스트임. 실관측에서 FPN이 3~4배 줄었음.
- `finalize_observation.py`: 정합 개발판입니다(평행이동판 / jitter판, `residual_check`로 5×4 타일 잔차 RMS).
- `diag_rotation.py`: 밴드 간 미세 회전을 진단합니다(Blue +0.03°, RE3 −0.08° 수준).
- `rgb_from_8band.py`, `merge_bands.py`, `convert_dtype.py`: 변환 유틸리티임.

---

## 6. 절대 복사보정, TOA 반사율, 대리검증

> 관련 파일: `02_Radiometric_Correction/src/radcal/`, `doc/RADIANCE_TOAR.md`, `results_sample/*la_crau*/radcal_lcfr/`

### 6.1 DN → TOA 분광 복사휘도 (`radcal/dn_to_radiance.py`)

- FM1 CSV에서 (밴드, line rate 666, TDI)에 해당하는 행을 고르고 포화 plateau를 제거함. dark는 lmap 0 행임.
- 열마다 `LinearRegression(DN−dark → radiance)`를 맞춘 뒤 **열 평균 gain을 밴드 스칼라로 씀.**
  - intercept는 버림. 영향은 3% 미만임.
  - 열별 gain을 쓰지 않는 이유는 flat PRNU와 이중 보정이 되기 때문임.
- 변환식: `L = DN_corr · gain_b / BW_b`

| 밴드 | TDI | gain | BW (nm) | F0 |
|---|---|---|---|---|
| PAN | 2 | 8.750 | 250 | 1653 |
| Blue | 4 | 5.372 | 65 | 2000 |
| Green | 8 | 2.055 | 35 | 1819 |
| Red | 8 | 1.961 | 30 | 1514 |
| RE1 | 16 | 1.180 | 15 | 1421 |
| RE2 | 16 | 1.375 | 15 | 1292 |
| RE3 | 16 | 2.219 | 20 | 1166 |
| NIR | 4 | 8.882 | 115 | 1032 |

> **단위 주의:** 코드 주석과 문서에는 L의 단위가 "W/m²/sr/nm"로 적혀 있음. 그런데 F0가 W/m²/µm 단위(Blue ≈ 2000)이고, 반사율 식이 맞으려면 L은 **W/m²/sr/µm (= mW/m²/sr/nm)**이어야 함. 값의 크기(Blue ≈ 91, ρ ≈ 0.16)도 µm 단위와 맞음.

### 6.2 복사휘도 → TOA 반사율

```
ρ_b = π · L_b / (F0_b · cos θs) / d_r ,   d_r = 1 + 0.033·cos(2π·DOY/365)  ≈ (1AU/d)²
```

- 물리식 `ρ = π L d² / (F0 cosθs)`에서 `d² = 1/d_r`이므로 **÷d_r**이 맞음.
- ⚠ 구 코드(`prep/03_code/02_L_to_TOAR.py`, `04_Auxiliary/.../bluebon_calibration.py`)는 `× d_r²`를 씀. 방향과 거듭제곱이 모두 틀렸고, 계절에 따라 최대 약 ±10% 오차가 남. v5(`dn_to_radiance.py`)에서 고쳤음.
- θs(태양천정각)는 장면 중심 한 점의 값을 씁니다(`--sza`로 입력하거나 pvlib로 계산).
- DOY는 파일명 `YYMMDD`에서 계산함.

### 6.3 RadCalNet La Crau 대리검증

구성 요소:
- `parse_radcalnet.py`: RadCalNet `.output`(400–2500 nm, 10 nm 간격, 30분 간격 13개 시간열)을 읽음. 촬영 UTC에 가장 가까운 열을 고르고, 불확도와 대기조건(AOD, WV, O3, SZA, esd)도 함께 읽음.
- `band_integrate.py`: RadCalNet 반사율을 BlueBON SRF로 적분함. `ρ_b = Σ SRF·ρ / Σ SRF`
- `extract_roi_dn.py`: L1A에 좌표가 없으므로 픽셀 bbox `(r0,r1,c0,c1)`로 ROI를 지정하고 mean, std, CV를 구함.
- `vicarious_calib.py` / `run_lcfr_calib.py`
  - 대리 gain: `gain_b = ρ_b / mean_DN_b`
  - 불확도: `√[(σρ/ρ)² + (CV)²]`
- `scene_report.py`: 파이프라인 TOAR와 RadCalNet을 비교한 보고서를 만듦.

**결과 1: 2026-05-28 La Crau** (`results_sample/20260528_la_crau_france/radcal_lcfr/report_20260528.md`)

| 밴드 | BB L | BB TOAR | RadCalNet ρ ± σ | 비율 |
|---|---|---|---|---|
| PAN | 66.44 | 0.1415 | 0.1575 ± 0.0064 | 0.899 |
| Blue | 91.41 | 0.1609 | 0.1386 ± 0.0039 | 1.161 |
| Green | 77.66 | 0.1504 | 0.1424 ± 0.0053 | 1.056 |
| Red | 68.37 | 0.1590 | 0.1677 ± 0.0078 | 0.948 |
| RE1 | 71.99 | 0.1784 | 0.1874 ± 0.0079 | 0.952 |
| RE2 | 75.73 | 0.2064 | 0.2222 ± 0.0091 | 0.929 |
| RE3 | 85.68 | 0.2588 | 0.2505 ± 0.0100 | 1.033 |
| NIR | 70.92 | 0.2420 | 0.2497 ± 0.0096 | 0.969 |

- 평균 비율 **0.993**, RMSE **8.0%**, ±10% 이내 밴드는 **6/8**입니다(Blue +16%, PAN −10%).
- 조건: SZA 23.49°, AOD 0.21, roll −5.28°
- README에는 "8밴드 모두 ±10% 이내"라고 적혀 있지만 실제 보고서는 6/8임.

**결과 2: 2026-07-04 La Crau**
- RadCalNet 당일 자료가 없어 DOY 184 자료를 대신 썼음.
- 평균 비율 약 **1.23**으로 계통적으로 높게 나왔음. 원인으로는 참조일 불일치와 큰 off-nadir(roll −9.85°)를 꼽고 있음.
- 대리 gain은 0528보다 밴드마다 13~22% 낮음.

교훈:
- **gain은 TDI와 line rate에 강하게 의존함.** 처음에 TDI를 잘못 가정했을 때 PAN은 약 7.6배, NIR은 약 3배 어긋났음.
- 옅고 균일한 연무(haze)는 비교에 문제가 없음. 패치 형태의 구름이나 그림자가 있는 장면은 쓰면 안 됨.

실행 예:

```bash
python3 src/radcal/dn_to_radiance.py                         # gain/BW/F0 표 출력
python3 src/radcal/dn_to_radiance.py --convert <8band.tiff> --out-radiance L.tiff --out-toar R.tiff --sza 23.49 --doy 148
python3 src/radcal/run_lcfr_calib.py --tiff <8band.tiff> --srf ref/SpectralResponseFunction.xlsx \
     --radcal ref/radcal_sample/LCFR01_2026_184_v04.06.output --utc 11:08:33 --roi R0 R1 C0 C1 --out <dir>
```

---

## 7. 기하보정 (L1A → L1C): `03_Geometric_Correction/V3`

> 진입점: `V3/Code/Full_processing_v2.py`
> 핵심 모듈: `V3/Code/03.geometric_correction/geometric_correction.py` (STEP 1~16), 패키지 `geometric_correction/pipeline/{preprocessing, initial_matching, precision_correction}.py`, `PrcsnMatching/`, `models/rpc.py`, `V3/Code/rpcfit/`, `Strip_correction_3D.py`
> ⚠ `V3/README.md`는 구 버전 설명(Ridge RPC + `gdalwarp -rpc`)이라 **실제 코드와 다릅니다**. 이 장의 설명이 실제 코드 기준임.

### 7.1 기본 개념

- BlueBON L1A에는 **궤도·자세 메타데이터나 센서 RPC가 없습니다**. 그래서 **영상 매칭으로 RPC를 처음부터 만드는(부트스트랩)** 방식임.
- 입력은 세 가지임.
  - L1A 8밴드 tiff (CRS 없음)
  - 장면 중심 위경도(`--lat/--lon`, 미션 시트의 Target Lat/Lon)
  - 가정 해상도(`--res`, 기본 4.8 m)
- 참조 데이터는 Google Earth Engine에서 자동으로 받음.
  - **Sentinel-2** `COPERNICUS/S2_HARMONIZED`: B4/B3/B2, 10 m, 세그먼트 중심별 60 km 박스
  - **DEM** `COPERNICUS/DEM/GLO30`: 30 m, 150 km 박스. SRTM으로 바꿀 수 있음
  - **Geoid** EGM2008 1′ 격자(공개 S3 URL), 200 km 박스
  - 모든 GCP 고도는 **타원체고 = DEM(정표고) + Geoid 높이**로 계산함
- S2 날짜 선택(`find_best_sentinel_mosaic`)
  - 1차 탐색: 촬영일 ±90일, 운량 10% 미만, 중첩률 0.5 이상
  - 2차 탐색: 1년 전 ±30일
  - 3차 탐색: ±180일
  - 점수 = 0.4·중첩률 + 0.5·(100 − 운량) + 0.1·(100 − |Δ일|). 날짜별로 mosaic을 만듦
- 다운로드 결과는 `_shared/`에 한 번만 받고, 각 세그먼트에서는 심볼릭 링크로 씀.

### 7.2 Strip 3분할 (Step 0)

push-broom 스트립(약 16000행)은 한 번에 하나의 RPC로 표현하기 어려움. 그래서 3개 구간으로 나눠 각각 보정함.

| 세그먼트 | 행 범위 (H = 전체 높이) | 중심좌표 |
|---|---|---|
| Center | [H/2−3000, H/2+3000) → 6000행 | (lat, lon) |
| Top | [0, Center 시작 + 1000) | (lat + 0.216399°, lon + 0.098737°) |
| Bottom | [Center 끝 − 1000, H) | (lat − 0.216399°, lon − 0.098737°) |

- 세그먼트끼리 1000행이 겹침.
- `--segment 2`이면 오프셋을 0.75배로 쓰고, `--segment 1`이면 전체를 한 번에 처리함.
- [검토 필요] 고정 위경도 오프셋은 특정 진행 방향(NNE)을 가정한 값임. 다른 궤도 방향에서도 맞는지 확인이 필요함.

### 7.3 세그먼트별 처리 단계 (`geometric_correction.py`)

#### [1단계] 1차 보정: STEP 1~10

| STEP | 내용 | 주요 파라미터 |
|---|---|---|
| 1–2 | 입력 검증, 참조 CRS(EPSG:4326)로 통일 | |
| 3 | 참조, DEM, Geoid를 crop | 범위 = 중심 ± (W·res, H·res)×1.5/2 |
| 4 | 참조를 4.8 m로 리샘플 (bilinear, 필요하면 2.4 m를 거침) | |
| 5 | 참조와 타깃을 1/8로 다운샘플 (≈38 m/px) | `INITIAL_MATCHING_RESOLUTION=8` |
| 6 | **SuperPoint + LightGlue** 특징점 매칭 | max_kp 4096, CLAHE(2.0, 8×8). 타깃은 밴드 2,3,4 평균, 참조는 B4 |
| 7 | **RANSAC Homography** 이상치 제거 | thr 3 px(1/8 해상도), 5000 iter, conf 0.99 |
| 8 | 좌표를 ×8 해서 원래 해상도로 복원 | |
| 9 | GCP 생성: 참조 픽셀 → 위경도, z = DEM + Geoid | `02_Initial_matching/initial_gcps.json` |
| 10 | **1차 기하보정**: `gdal_translate -gcp …` → `gdalwarp -order 2 -r cubic -t_srs EPSG:4326` | 이름은 "AFFINE"이지만 실제로는 **2차 다항식** |

샘플(Center): 키포인트 ref 2198 / tgt 1403, 매칭 1055, RANSAC 인라이어 972 (92%), 회전 약 14.25°

#### [2단계] 정밀 매칭: STEP 11~13

| STEP | 내용 |
|---|---|
| 11 | 1차 보정 영상을 새 타깃으로 삼아 STEP 1~4를 다시 수행 |
| 12 | **특징점 선정**: Red 밴드를 512×512 타일(step 448)로 나누고 타일당 SuperPoint 200 kp를 뽑음 → 점수 기반 NMS(반경 300 px, 최대 300점) → 각 점 주변 512×512 패치(BlueBON / Sentinel) |
| 13 | **RoMaV2 정밀 매칭**: 패치 쌍마다 dense matching(DINOv3 ViT-L/16 백본, setting=fast, 2000 대응점) → 중심 ±100 px 안에서 50점 선택 → `estimateAffinePartial2D`(RANSAC 3 px) → 인라이어 ≥ 10이고 비율 ≥ 0.8이면 성공 → **패치당 tie-point 1개** |

- 샘플(Center): 13996 kp → NMS 후 175점 → RoMaV2 성공 169개
- `--gcp_chips`로 이전 실행에서 만든 GCP 칩(`06_GCPs`)을 넘기면 Sentinel 대신 그 칩을 참조로 씀.
- RoMaV2가 현재 환경에 없으면 `geo_unified` 환경의 python으로 `run_romav2_standalone.py`를 서브프로세스로 실행함. 이 경로는 하드코딩되어 있음.

#### [3단계] GCP 정리: STEP 14, 14.5, 14+

- **STEP 14**: Sentinel 픽셀 → 위경도·타원체고. 15×15 격자로 커버리지를 계산하고, 60% 미만이면 Pseudo GCP가 필요하다고 표시함.
  - RFM 기반 RANSAC 코드는 있지만 **꺼져 있습니다**(`rpc.py:335` `if False and …`). 그래서 로그에 항상 Inliers 100%가 찍힘.
- **STEP 14.5**: 빈 셀에 Pseudo GCP를 만들고 교대 최적화를 함. 다만 그 결과의 Pseudo는 STEP 14.9에서 버려짐.
- **STEP 14+**: 최종 GCP를 **원본 L1A 픽셀 좌표로 역투영**함.
  - STEP 9의 초기 GCP로 맞춘 **2D 3차 다항식 (위경도 → 원본 픽셀, Ridge α=1e-3)**을 씀.
  - 영상 밖의 점은 제외합니다(샘플: 262개 중 201개 사용).

#### [4단계] RPC 부트스트랩과 피팅: STEP 14.9, 15

RPC(RFM) 모델은 20항 3차 다항식의 비율로 표현함.

```
r_n = Σ a_i·t_i(P,L,H) / Σ b_i·t_i(P,L,H),   c_n = Σ c_i·t_i / Σ d_i·t_i,   b₁ = d₁ = 1
P = (φ − φ₀)/φ_s,  L = (λ − λ₀)/λ_s,  H = (h − h₀)/h_s,   row = r₀ + r_s·r_n
```

1. **Seed 모델** (`fit_3d_polynomial_seed`)
   - `(col,row) = f(X,Y,Z)` 다항식을 맞춤.
   - 차수는 GCP 수 N에 따라 자동으로 고릅니다: N < 30이면 1차, < 60이면 1.5차, < 100이면 2차, ≥ 100이면 3차.
2. **Pseudo 3D 격자** (`generate_pseudo_grid_3d_from_seed`)
   - X, Y는 Real GCP의 2~98 백분위, Z는 [min − 200 m, max + 200 m]로 잡아 15×15×5 = 1125점을 만듦.
   - 필터 세 가지(Real GCP convex hull + 5% 마진, 육지 마스크, 영상 내부)를 통과한 점만 남습니다(샘플 930점).
3. **Validation 분할**: 4분면별로 20%를 holdout으로 뗍니다(seed 42).
4. **STEP 15: rpcfit 피팅**
   - 호출: `calibrate_rpc(target, input_locs, separate=True, tol=1e-2, max_iter=20, orientation="projloc", init=seed)`
   - 선형화: `R·(1 + Σ_{i≥2} b_i t_i) = Σ a_i t_i` → 미지수 39개
   - 초기해는 **Tikhonov 정칙화**임. 정칙화 강도 h는 **L-curve 최대 곡률점**에서 고릅니다(로그 간격 200점 탐색).
   - 이후 **반복 가중 최소제곱**(가중치 w = 1/분모)과 ICCV 갱신 `θ_{k+1} = (XᵀWX + I)⁻¹(XᵀWy + θ_k)`을 반복함.
   - projection(지상→영상)과 localization(영상→지상) 계수를 모두 구함.
5. **[P-iter] 재귀 정제**: RPC v0로 Pseudo를 다시 만들고 다시 피팅함. 최대 2회, ΔRMSE < 0.05 px면 수렴으로 봄.
6. **STEP 15-2 bias 보정**: train 잔차 평균 (dc, dr)을 적용했을 때 holdout이 0.05 px 넘게 개선되면 `SAMP_OFF`와 `LINE_OFF`에 흡수함.
7. **STEP 15-3 잔차 진단**: 방향성 bias, row/col 비대칭(> 1.3이면 along-track jitter 의심), 고도 상관, 이상치 비율, 과적합을 자동으로 판정함.
8. **STEP 15-1**: self-fit RMSE와 5-fold CV를 계산합니다(`08_Evaluation/`).

#### [5단계] 정사보정: STEP 16 (`step16_orthorectification`)

1. 영상 가장자리 8점을 RPC localization으로 지상에 투영해 범위를 구함. **UTM zone을 자동 선택**하고 4.8 m 격자를 만듭니다(±48 m 버퍼).
2. 출력 픽셀마다 `h = DEM + Geoid`를 bilinear로 구함.
3. `(col,row) = RPC.projection(lon, lat, h)`
4. `cv2.remap(INTER_CUBIC)`으로 리샘플함. 범위 밖은 0임.
5. LZW로 저장하고 `.RPB` sidecar를 씀.
6. 이어서 Real GCP 위치에서 513×513 **GCP 칩**을 잘라 `06_GCPs/`에 저장함. 이 칩은 다음 실행에서 참조로 재사용할 수 있음.

- STEP 15나 16이 실패하면 STEP 10의 1차 보정 결과를 최종본으로 씁니다(`*_final_initial_corrected.tif`).

### 7.4 Top/Bottom 실패 시 외삽 (`Strip_correction_3D.py`)

- Center의 RPC로 겹침 영역(1000행)에 격자 GCP를 만듭니다(step 200 px, DEM + geoid).
- `lat/lon = poly(line 1차 × samp 2차)` 다항식으로 실패한 세그먼트 전체에 Pseudo GCP를 외삽함.
- 고도 ±10, ±100 m 레이어를 추가한 뒤 `calibrate_rpc`로 피팅하고, `gdalwarp -rpc -to RPC_DEM=…`으로 정사보정함.
- `Strip_correction_all.py`는 Bottom을 기준으로 위쪽 세그먼트를 연쇄 외삽하는 독립 스크립트임.

### 7.5 모자이크와 결과 정리

- `gdalbuildvrt -srcnodata 0` → `gdal_translate`(LZW, TILED, BIGTIFF)
- 블렌딩은 하지 않음. 겹치는 부분은 뒤 파일이 우선함.
- 최종 산출물: `level-1C/bb_l1c_YYYYMMDD_HHMMSS_8band.tiff`, `*_center_coordinates.txt/.xlsx`
  - 중심 좌표는 미션 시트의 Actual Lat/Lon에 반영됨.
- 샘플: EPSG:32639, 7076×16509 px, 처리 시간 약 28분(세그먼트당 9~10분)

세그먼트 폴더 구조 (`V3_sample_run_20260708/`에 일부 포함):

| 폴더 | 단계 | 내용 |
|---|---|---|
| `00_Divided_image/` | Step 0 | 분할 영상, `divided_coordinates.txt` |
| `01_Download_open_data/` | 링크 | S2, DEM, Geoid |
| `01_preprocessing/` | STEP 2–5 | 자동 삭제 |
| `02_Initial_matching/` | STEP 6–9 | `initial_matches.png`, `initial_gcps.json` |
| `03_Initial_correction/` | STEP 10 | 1차 보정 영상 |
| `04_patches/` | STEP 12 | 특징점 패치 |
| `05_ROMAV2_result/` | STEP 13 | `stage4_matches.npz` |
| `05_SuperPoint_result/step14_visualizations/` | STEP 14+ | `step14_final_gcps_original_target.json`, GCP 위치 그림 |
| `08_Evaluation/{production,validation}/` | STEP 15-x | RMSE, CV, holdout, 잔차 진단 |
| `07_Final_results/` | STEP 16 | `bb_l1c_*_{seg}.tiff/.RPB` |
| `06_GCPs/` | STEP 16 이후 | GCP 칩 513×513, `gcp_chips_metadata.json` |
| `pipeline_log_*.txt` | 전체 | 단계별 상세 로그 |

### 7.6 정확도 지표 해석 주의 [검토 필요]

- 샘플의 self-fit RMSE는 0.0008~0.004 px이고 holdout도 0.001~0.004 px임. 그러나 **이 값은 실제 위치 정확도가 아님.**
  - STEP 14+에서 원본 픽셀 좌표를 매끄러운 3차 다항식으로 다시 계산하므로, RPC가 그 다항식을 재현하는지만 재는 셈이기 때문임.
- 실제 정확도를 보려면 다음 중 하나를 써야 함.
  - Sentinel-2 대비 독립 영상정합 평가(`Code/eval_utils.py`). 64×64 패치 위상상관으로 RMSE를 냄. 다만 현재는 외삽 경로에서만 호출됨.
  - 미션 시트의 Actual vs Target 위경도 오차
- 같은 구조 때문에 RoMaV2 정밀 매칭 결과가 최종 RPC에 충분히 반영되지 않을 가능성이 있음. 개선할 때 검토할 지점임.

### 7.7 실행 방법

```bash
# 단건 CLI
python Code/Full_processing_v2.py --input bb_l1a_20260708_074748_8band.tiff --lat 17.9439 --lon 52.6422 \
       [--segment 3] [--res 4.8] [--intermediate]
#   --input을 생략하면 tkinter GUI(pipeline_gui.py)가 뜹니다

# 일괄 (미션 시트 기반)
python Code/batch_processing.py --sheet <sheet.csv> --tiff-dir <dir> --batch-count N [--dry-run]
bash ../01_L0_to_L1A_prep/L1C_batch/run_preprocess.sh       # 목록 txt(name otime dtime lat lon)로 순차 실행

# 웹 앱 (FastAPI :8000 + React/Vite :5173): 시트 로드 → TIFF 매칭 → 처리 → Drive 업로드
bash BlueBON.sh ; bash stop.sh

# Docker (CUDA 12.4, 단일 env geocorrect, 가중치 포함 약 15–20 GB)
cd docker && bash build.sh && bash run.sh --input … --lat … --lon … --key <GEE키.json> --gpu
```

필수 조건:
- GDAL CLI
- CUDA GPU (RoMaV2)
- **GEE 서비스계정 키**: `Code/auth/ee-service-account-key.json`. 패키지에는 없으니 각자 준비해야 함.
- 웹/배치 모드: rclone, Google OAuth

> ⚠ Docker `build.sh`는 `Code/` 전체를 이미지에 복사하는데, `.dockerignore`가 `Code/auth`를 제외하지 않음. 키가 이미지에 들어가지 않도록 **빌드 전에 `.dockerignore`에 `Code/auth`를 추가하세요**.

### 7.8 260317 버전과 V3 비교

| 항목 | 260317 (이전) | V3 (현행) |
|---|---|---|
| 참조 다운로드 | 세그먼트마다 반복 | `_shared`에서 1회 + 링크 |
| S2 컬렉션 | `COPERNICUS/S2` (폐기 예정) | `S2_HARMONIZED` |
| RPC 학습 | Real GCP를 수천~수십만 번 복제하는 가중 방식 | 3D seed → Pseudo 3D 격자 → rpcfit(init) → 재귀 정제 + holdout/CV/잔차 진단 |
| 정사보정 | EPSG:4326 격자, INTER_LINEAR | **자동 UTM, 4.8 m, INTER_CUBIC** |
| RoMaV2 임계값 | 0.7 | 0.8 |
| 추가 기능 | – | 웹 앱, Docker, Download_BlueBON.py, Strip_correction_all.py |

---

## 8. 보조 전처리 자료 (`04_Auxiliary`)

### 8.1 `bluebon_L0_L1_research/`: 초기 L0→L1 연구 코드

> 실행에는 원 작성자 환경의 `../../tools`, `../../g2l1bpy` 등 형제 디렉터리와 `<WORK_ROOT>/...` 경로가 필요함. 그대로는 돌아가지 않으므로 **알고리즘 참고용**으로 보세요.

**`src/bluebon_calibration.py`**: 메인 체인. raw DN을 받아 nc 스택으로 만듦.

1. DN → L
   - 현행 방식은 **열별 선형식 `L = DN·slope_j + offset_j`**임. 계수는 `src_mdtest/dn2rad_coeffs_calpar.npz`, shape (8, 4096, 2)임.
   - 이어서 좌우반전하고 ×0.1을 곱합니다(단위 환산으로 [추정]).
2. ρt 계산: `π·L/(F0·cosθs)·d_r²`. 이 식의 d_r 항은 잘못되었습니다(6.2절).
3. **밴드정합 (affine)**: `coreg_tools.coreg_two_refs_affine_sobel_mask`
   - Sobel 엣지 → ORB(2000 kp) → cross-check 매칭 → 8×2 격자 thinning → RANSAC Affine(2 px)
   - 기준 밴드가 두 개임. VIS 그룹은 MS4, NIR 그룹은 MS5에 맞추고, 두 행렬을 합성해 VIS·NIR 간 밝기 반전 문제를 피함.
   - 대안으로 Fourier-Mellin(log-polar로 회전·스케일 추정)과 다중 타일 similarity 방식이 있습니다(`coreg_FourierMelin*.py`).
4. 선택 처리
   - 줄무늬 보정 `line_correction.py`: 열 방향 box 평균(w=31)과의 차이를 열 평균 내서 빼는 방식임. 어두운 해양 장면용임.
   - Rayleigh 보정 ρrc = ρt − ρr: 6S LUT(`LUT/LUT_Ray`, `genLUT/genLUT.py`)를 장면 중심 한 점에서 조회함.
5. 출력: `*_stacked_{DN|rad|rhot|rhorc}.nc` (uint16, scale 1/65535)

**`src_mdtest/bb2msi_calibration.py`**: **Sentinel-2 MSI를 기준으로 한 교차검교정**. 위 열별 계수를 만든 코드임.

1. raw 픽셀을 밴드정합 affine과 GCP affine으로 위경도로 바꾸고, MSI radiance를 bilinear로 샘플링함.
2. MSI 밴드를 BlueBON 중심파장으로 선형 보간함.
3. 열마다 (DN, L_MSI) 쌍을 모아 3σ 클리핑한 뒤 **ODR 직교회귀**를 함. 사용 장면은 260220 Suwon과 250926 Khuvsgul임.
4. 결과: slope 중앙값(PAN→MS7) 0.035, 0.066, 0.056, 0.075, 0.097, 0.120, 0.147, 0.115
- PAN은 정합이 실패해서 신뢰할 수 없다고 코드에 명시되어 있음.

**`src_geosim/`**: 궤도 시뮬레이션(Kepler 2체 문제, LVLH roll/pitch/yaw)으로 픽셀 → 위경도 매핑을 만들고, MSI 대비 cross-track 보정계수를 구하던 구버전 접근임.

**`calib/`**: SRF(csv/xlsx)와 in-band radiance 표임. FM1 PRNU 원본은 `05_Reference_Data`에 있음.

**`src/nc_to_warpedtiff.py`**: 수동 GCP로 `gdal.Warp`(UTM, cubicspline)를 하는 초기 기하보정임. 현재 활성 블록에는 구문 오류가 있음.

### 8.2 `pointing/`: 지향(pointing) 오차 평가

- 목적: 촬영 시각, 목표점, 실제 영상 중심을 넣으면 **along-track / across-track 오차(km)**를 냄.
  - along이 양수면 진행방향 앞쪽, across가 양수면 진행방향 왼쪽임.
- 알고리즘
  1. 하드코딩된 TLE를 SGP4로 전파해 t와 t+200 ms의 위치를 구함.
  2. TEME → ECEF 변환(GMST 회전)을 하고 진행 방위(heading)를 구함.
  3. 영상 중심 → 목표점 거리 D(haversine)와 방위 az를 구함.
  4. θ = az − heading으로 두고 `along = D·cosθ`, `across = D·sinθ`를 계산함.
- 실행: `conda run -n pt bash run_pt.sh input.txt`
  - 입력 줄 형식: `시각 tlat tlon clat clon`
  - 결과는 `output.txt`에 씀.
- 주의
  - TLE가 고정값(epoch 2026-03-17)이므로 날짜가 멀어지면 정확도가 떨어짐. 최신 TLE로 바꿔서 쓰세요.
  - 입력 파일의 마지막 줄에 개행이 없으면 그 줄이 누락됨.

### 8.3 `deblur_MTF/`: L0 blind deblurring과 MTF 측정

- **Deblur**: IPOL 2019 "Blind Image Deblurring using the l0 Gradient Prior"(논문 PDF 포함) C++ 구현의 로컬 수정판임.
  1. `estimate-kernel`: L0 gradient prior로 PSF를 추정함.
  2. `deconv`: TV 정칙화 deconvolution을 함.
  - 권장 파라미터(`bluebon-parameter.txt`): 커널 15 px, iteration 5, **alpha = 1000**. 기본값 3000은 줄무늬 노이즈를 증폭함.
  - `tile_deconv.py`: 2048 px 타일 + 128 px 겹침으로 병렬 처리함. 전역 max를 통일해서 단일 처리 대비 6.5배 빠르고, 차이는 최대 0.43 DN임.
  - `run_deblur.sh kernel|deconv|preview`
- **MTF**
  - `mtf_edge.py`: ISO 12233 계열 경사에지법임. Canny/Hough로 에지를 찾고, 0.25 px 초해상 ESF → LSF → FFT 순서로 계산함.
  - `mtf_kernel.py`: 추정 PSF의 |FFT|에서 MTF를 구함.
  - `mtf_spectral.py`: 스펙트럼 비율로 시스템 MTF를 구함.
  - `mtf_selftest.py`: 가우시안 PSF로 측정 코드를 검증함.
  - `satellite_MTF.md`: 일반 MTF 이론 정리임.

---

## 9. 운영 절차: 다운로드, 업로드, FEE/CEM, 미션 시트

> 원문 메모: `01_L0_to_L1A_prep/docs/0_전처리 코드 돌리기.txt`, `1_fee_cee 코드 돌리기.txt`

### 9.1 일상 처리 순서

1. SharePoint `TelePIX/00_LEOPS/01_downlinked`에서 새 영상(`YYYYMMDD_<지역>.tar.xz|zip`)을 받아 `prep/data/`에 둠.
   - `src/sharepoint/sp_download_unprocessed.py`를 쓰면 자동으로 받을 수 있음. 미션 시트에서 AD열이 빈 행을 ±20초 이내로 매칭함. 인증은 `sp_auth.sh`(rclone, 브라우저 로그인)로 함.
2. `conda activate prep; cd prep/src; ./loop.sh`를 실행함. L0, L1A, 업로드 폴더 구성까지 자동으로 진행됨.
3. `data/upload/yymmdd_HHMMSS`를 SharePoint `00_LEOPS/02_processed_images`에 올린 뒤 `upload/complete/`로 옮김.
4. `data/upload/GDrive/yymmdd_HHMMSS/{raw, level-0, level-1A}`를 Google Drive `LEOP/`로 옮김.
5. Google 시트 "BlueBON Mission"을 갱신합니다(Image, 복사보정 칸 O 표시, 색칠).
6. 색감이 이상하면 `make_rgb_png.py`를 다시 돌림.
7. FEE/CEM 온도를 처리합니다(9.3절).
8. L1C: `run_preprocess.sh`나 기하보정 웹 앱을 씀. 결과는 Drive `LEOP/<dir>/level-1C`에 올라감.

### 9.2 업로드 스크립트

- `upload.sh`: `radiometric/`의 12 bit tiff와 PNG를 `upload/<tdate>/`로 복사함.
- `upload4GDrive.sh`: raw, level-0, level-1A 폴더를 구성하고 `merge_bands.py`로 `bb_l1a_*_Nband.tiff`를 만듦.
- `aws_upload.sh`: tar.xz로 묶어 S3 호환 스토리지(`s3://telepix/processed_images/`)에 올림.
- `list_unprocessed_files.sh`, `rename_levels.sh`, `dir_restruct.sh`: 점검과 이름 변경 유틸리티임.

### 9.3 FEE/CEM 온도 (`fee_cem/`)

- 목적: 촬영 텔레메트리에서 **FEE(Front-End Electronics)와 CEM 온도**를 뽑아 미션 시트 AD열에 기록함.
- `process-all.sh`
  1. 압축을 풀고 `.tlm.tpx*`를 모음.
  2. `imaging-test.sh`를 실행함. 텔레메트리를 복호화하고 `check-tlm.sh`(Mission Result, 네트워크, tlm-checker)와 `see-thermal.sh`를 돌림.
     - `see-thermal.sh`: `4,0,9` 줄을 FEE, `4,0,8` 줄을 CEM으로 봄.
  3. `fee_cee_summary.csv`를 만들고 Drive에 업로드한 뒤 `update_sheet.py`로 시트를 갱신함.
- `process-from-drive.sh` → `process_empty_rows.py`: 시트에서 AD열이 빈 행만 Drive 자료로 처리함. `--dry-run`, `--date`, `--limit` 옵션이 있음.
- ⚠ 복호화 스크립트(`util/mission/unpack-tpx.sh` 등)와 Google 서비스계정 키는 패키지에서 뺐음.

### 9.4 미션 시트 열 구성 (`05_Reference_Data/mission_sheet/`)

| 열 | 내용 |
|---|---|
| A–D | ID, Plan Date, Target, Category |
| **E** | **Capture Start Time** (`2026-08-05T19:30:45.944`) |
| F–I | Time Offset, **Tilt(roll)**, Pitch, Direction(asc/desc) |
| J–M | Target Lat/Lon, Satellite Lat/Lon |
| N–Q | Sun Elevation, Cloud, Water Body, Space Weather |
| **R** | **Band [PAN,MS1..7] = TDI 문자열** |
| S–W | Downlink Date, Image, Telemetry, 복사보정, 기하보정 |
| X–AC | Time Offset, **Actual Lat/Lon과 오차**, Unusable Image |
| AD–AG | **FEE/CEM Temp**, saturation ratio, histogram, max shifted pixel |

---

## 10. 실행 환경

| 용도 | 환경 | 정의 파일 |
|---|---|---|
| L0, L1A (prep), 복사보정 v5 | conda `prep` (Python 3.13, numpy 2.3, rasterio 1.4, scikit-image 0.25, scikit-learn 1.7, scipy, openpyxl) | `01_L0_to_L1A_prep/environment_prep.yml`, `02_Radiometric_Correction/environment.yml` |
| TOAR 계산 (pvlib) | `prep` + `pip install pvlib` | – |
| 기하보정 V3 | `geo_unified` (코드 하드코딩) 또는 Docker `geocorrect` (Python 3.11, PyTorch 2.10, GDAL 3.10, rpcm, earthengine-api, kornia) | `03_Geometric_Correction/V3/docker/environment.yml` |
| 기하보정 260317 | `geo_correctionv2` + `geo_romav2` | `260317_previous_version/*.yml` |
| bin2png 빌드 | g++ (C++17), libssl, libpng, libtiff, zlib | `telepix-bin2png-cpp-*/makefile` |
| pointing | conda `pt` (sgp4) | – |

> 대부분의 스크립트에 `<WORK_ROOT>/...`, `/mnt/hdd/...`, `<WORK_ROOT>/...` 같은 **절대경로가 하드코딩**되어 있음. 새 환경에서 실행하려면 경로를 먼저 바꿔야 함.

---

## 11. 알려진 문제와 주의사항

| # | 위치 | 내용 |
|---|---|---|
| 1 | 전 단계 | **TDI와 line rate를 코드에 하드코딩**함. 미션 시트 R열과 다른 설정으로 찍은 장면은 gain과 dark가 틀어집니다 |
| 2 | prep, v5 | `*_DN_dark_rc_p.tiff`와 `bb_l1a_*_8band.tiff`(uint16)는 **장면별 min–max 정규화값**임. 정량 분석에는 `_float32` 또는 `_f32` 파일을 쓰세요 |
| 3 | prep `02_L_to_TOAR.py`, research 코드 | 지구-태양 거리 보정을 `×d_r²`로 함. 올바른 식은 `÷d_r`이고, 최대 약 ±10% 오차가 납니다 |
| 4 | 단위 표기 | 복사휘도 단위 "W/m²/sr/nm"는 실제로는 W/m²/sr/µm입니다 |
| 5 | 복사보정 v5 | `make_*` 스크립트의 입출력 경로가 `prep/data/...`로 하드코딩되어 있음. `--prnu-mode residual`은 동작하지 않습니다 |
| 6 | 복사보정 v5 | La Crau 0528은 6/8 밴드만 ±10% 이내이고, 0704는 약 +23% 편향임. 절대보정은 아직 검증 중입니다 |
| 7 | L0 | 항상 16000행으로 저장하므로, 실제 라인이 적으면 0 라인이 통계와 PRNU 계산에 섞입니다 |
| 8 | 기하보정 | README가 실제 코드와 다름. RFM RANSAC은 꺼져 있음. 보고되는 RMSE는 실제 위치 정확도가 아닙니다(7.6절) |
| 9 | 기하보정 | 최신 코드의 출력 루트는 `level-1C/`인데 batch와 웹 앱은 여전히 이전 폴더명에서 결과를 찾습니다 |
| 10 | 기하보정 | 세그먼트 중심 오프셋이 진행 방향을 고정으로 가정합니다 |
| 11 | Docker | GEE 키가 이미지에 들어갈 수 있음. 웹 백엔드는 인증 없이 CORS `*`로 열려 있으니 외부에 노출하지 마세요 |
| 12 | bin2png | 로그 파일이 계속 커집니다(5.9 GB). `run_band_dir.sh`에는 `elif` 문법 오류가 있습니다 |

---

## 12. 다운스트림 응용 (`06_Downstream_Applications`)

> 전처리(L1A/L1C)가 끝난 뒤에 쓰는 **응용·분석 코드**임. 대부분 연구 단계 코드라 경로 하드코딩과 미완성 부분이 있음.

### 12.1 AOD: 에어로졸 광학두께 (`AOD/BlueBON`, `AOD/S2`, `AOD/bb_aod`)

- **입력**: Telepix 배포 L1C 8밴드 tiff(uint16, EPSG:4326, nodata 0)
- **DN → 반사율** (`bb_aod_calval.py`)
  - `L = DN × radiance_scale`. 기본값 **0.3183**은 튜닝값이고, 공식 계수가 나오면 바꿔야 함.
  - `ρ = π·L·d² / (ESUN·cosθs)`. ESUN은 공칭 중심파장에서 Thuillier 값을 보간해 씀.
- **알고리즘** (`bb_aod_pipeline.py`)
  1. SWIR 밴드가 없으므로 DDV(어두운 식생)를 `NDVI ≥ 0.25`, `ρred ≤ 0.15`, `NIR ≥ 0.20`으로 고름.
  2. 지표 Blue 반사율을 `ρsurf,blue = 0.575 · ρsurf,red`로 가정합니다(v8부터는 NDVI 의존 계수).
  3. Py6S 490 nm LUT(continental 에어로졸, AOT 0.01–2.0)로 AOD를 역산함.
  4. 20 m로 다운샘플한 뒤 Gaussian으로 빈 곳을 채우고(σ 300/480 px), 배경은 MAIAC 평균이나 DDV 중앙값으로 둠.
- **실행**
  ```bash
  python bb_aod_pipeline.py --input 'bb_l1c_*_8band.tiff' [--auto-maiac | --maiac-aod-mean X] --save-raw --save-qa --out-dir D
  ```
  `run_bb_aod.sh`는 파일명 오타(`bb_aod_pipline.py`) 때문에 그대로는 실행되지 않음.
- **검증**
  - `validate_bb_aod.py`: MODIS MCD19A2(MAIAC)를 받아 Bias, RMSE, R²를 계산함. Earthdata 계정을 인자로 넘겨야 함.
  - `data/aot_compare_20260220.py`: MAIAC, BlueBON, S2를 0.01° 격자에서 비교함.
- `AOD/S2`는 Sentinel-2 AOD 비교 실험이고, `bb_aod`는 이전 버전 사본임.

### 12.2 연무 제거 (`Dehazing/`)

- **`src_dehaze/`**: 영상 기반 연무(haze) 제거임. BlueBON, MSI 10/20 m, SkySat, OLI, CAS를 지원함.
  - 실제 진입점은 `basematch_NEW.py`임. 장면별 haze 기저 스펙트럼(`baseu_NEW`)과 선형 haze 모델(`haze_spec_modeling`)로 `*_dehSpec`, `*_aeroSpec`을 만듦.
  - `main.py`(박스평균 + 20 퍼센타일로 ρa 추정)는 비활성 상태임.
- **`DehazingGUI/`**: PyQt5 Windows GUI 소스입니다(PyInstaller, `build_windows.bat`).
  - 지원 센서는 SkySat과 MSI뿐이고 **BlueBON은 지원하지 않습니다**(README 참고).
  - CuPy13/CUDA12와 Maxwell GPU 관련 이슈는 `HANDOFF.md`에 정리되어 있음.

### 12.3 해색과 적조 (`OceanColor_HAB/`)

- **적조 탐지** (`BB_hab.py`, `Bluebon&S2 적조 탐지 설명.txt`)
  - red-edge line height를 씁니다: `hRE = ρrc(704.8) − baseline(664.6, 739.2)`
  - S2는 664.9/703.8/779.7 nm를 씀.
  - 입력은 Rayleigh 보정 반사율 ρrc 6밴드와 마스크임.
- **IOP 역산** (`BBrhorc2iop.py`, `BBinvfit*.py`): PyCUDA 기반 비선형 역산임. 모델은 Rrs(p0..p3)·t·π에 에어로졸 3성분을 더한 형태이고, 상수는 SRF 가중 aw/aph/adg를 씀.
- `flagging_bb.py`: 육지·구름 플래그입니다(임계 0.13 / 0.2).

### 12.4 SR과 영상 향상 (`SR/`, `Enhancement/`)

- **`SR/sr_curl.sh`**: BlueBON L1C에서 잘라낸 PNG를 사내 SR 서버에 POST하고 `*_sr.png`를 받음.
  - 서버 주소는 내부망이라 외부에서는 접근할 수 없음.
  - 입출력 예시 3쌍이 함께 들어 있음.
- **`Enhancement/`**: 일반 JPG/PNG를 대상으로 함.
  - 고전 처리: BM3D → Wiener → 샤프닝 (`enhance_png.py`, `enhance_lotte.py`)
  - 딥러닝 SR: Real-ESRGAN, ResShift, Swin2-MoSE (`*_sr.py`). 가중치(`*.pth`)는 빠져 있으니 각 저장소에서 받으세요.

---

## 13. 영상 샘플 (`07_Sample_Data`)

전체 영상(1.2TB 이상)은 넣지 않았음. 대신 **각 처리 단계의 입출력을 직접 확인할 수 있는 대표 장면**만 넣었음.

| 폴더 | 장면 | 포함 레벨 | 용도 |
|---|---|---|---|
| `A_260928_103939_Drvenik_raw_to_L1A/` | 2026-09-28 Drvenik Veli, Croatia | `raw/`: `capture-*.bin00~0b`(분할 원본), `.tlm.tpx00`<br>`level-0/`: `*_{0..7}_gray.tiff`<br>`level-1A_prep/`: `MS*_DN_dark_rc_p_float32.tiff`(복사휘도), `MS*_DN_dark_rc_p.tiff`(12bit), RGB png, `rgb_statistics.xlsx` | 3장과 4장(구 운영 경로) 확인. raw는 암호화되어 있어 복호화 키가 있어야 디코딩할 수 있습니다 |
| `B_260708_074748_L0_to_L1C/` | 2026-07-08 (17.94N, 52.64E) | `level-0/`: `*_{0..7}_gray.tiff`<br>`level-1A_v5/`: `bb_l1a_*_8band_f32.tiff`(복사휘도), `_8band.tiff`(12bit), RGB png, `registration_shifts.csv`<br>`level-1C/`: 최종 모자이크 `bb_l1c_*_8band.tiff`, 세그먼트별 `*_{top,center,bottom}.tiff/.RPB`, 중심좌표 txt/xlsx | 5장(v5 복사보정)과 7장(기하보정) 전체 흐름 확인. 기하보정 로그와 GCP는 `03_Geometric_Correction/V3_sample_run_20260708/`에 있습니다 |
| `C_LaCrau_20260528_radcal/` | 2026-05-28 La Crau, France (RadCalNet LCFR) | `level-0/`, `level-1A_v5/`(radiance f32, TOA 반사율 `bb_l1a-ref_*`, RGB, shifts), `radcal_lcfr/`(검증 보고서) | 6장 절대보정 검증 재현. ROI는 rows 7341–7350, cols 1603–1612 |
| `D_Radiometric_Reference_Raw/` | dark 260606_190315, 260424_114919 / flat(Libya-4) 260607_094318 | `dark_ref/`, `flat_ref/` 원본 L0 tiff, `radcal/LCFR/` RadCalNet 2015~2026 전체 | 5.3절 참조 계수(`ref/master`)를 다시 만들 때 입력. `make_*.py`의 경로를 이 폴더로 바꿔 쓰세요 |

- 모든 L0/L1A tiff에는 **좌표계가 없습니다**. L1C만 UTM(EPSG:32639) 좌표를 가짐.
- 파일명 규칙: L0는 `YYMMDD_HHMMSS_<b>_gray.tiff`, L1A는 `bb_l1a_YYYYMMDD_HHMMSS_8band*.tiff`, L1C는 `bb_l1c_YYYYMMDD_HHMMSS_8band*.tiff`

---

## 14. 코드 최신판 검증 결과

패키지를 만든 뒤(2026-10-07), 넣은 코드가 **최종판인지** 다음 세 가지로 확인했음.

1. **패키지와 원본 일치**: 패키지의 모든 코드와 문서를 원본 작업 폴더와 **내용(checksum) 기준**으로 비교했음. 모두 같았음.
2. **다른 사본 중 최신 여부**: 핵심 파일 14개의 모든 사본을 `<WORK_ROOT>`, `/mnt/hdd`, `<WORK_ROOT>`에서 찾아 수정일을 비교했음. 패키지에 넣은 원본이 **모두 가장 최신**이었음.

   | 파일 | 패키지 판 (수정일) | 다른 사본 |
   |---|---|---|
   | 복사보정 `pipeline.py` | 2026-08-08 00:07 | 백업 tar.gz 안 판(08-04)이 더 오래됨 |
   | 기하보정 `Full_processing_v2.py` | 2026-07-30 18:55 | 260317판(05-08), test 사본(03-19) |
   | `geometric_correction.py` | 2026-06-24 | 260317판(03-24) |
   | `precision_correction.py` | 2026-05-28 | 260317판(03-17) |
   | `Matching_performance_v3.py` | 2026-07-07 | 260317판(03-24) |
   | `Strip_correction_3D.py` | 2026-05-29 | 260317판(03-17) |
   | prep `01_DN_to_L_band.py` | 2026-05-14 | `prep/tmp`(02-09), `prep_src.tar.gz`(04-15) |
   | prep `loop.sh` | 2026-09-29 | `prep/tmp`(03-10), tar.gz(03-31) |
   | `run_preprocess.sh` | 2026-08-06 | 없음 |
   | `bluebon_calibration.py` 등 연구 코드 | `myPy.zip`과 같음 | – |

   `BlueBON_Geometric_Correction_V3.tar.gz`(08-05)는 작업 폴더와 내용이 같은 백업임.
3. **운영 바이너리**: `prep/src/03_code/make_tiff/bin2png`는 **최신 소스 `telepix-bin2png-cpp-86038fbd7142`로 빌드한 것**임. 구버전 바이너리와 md5가 다르고, 구버전에만 있는 `"./"` 경로 접두사 문자열이 없음.

> 같은 폴더 안의 `*_old`, `*_backup`, `*_ori`, `pipeline_v5.py`, `pipeline_20260723.py`는 비교용으로 남긴 이전 버전임. **실제로 쓰는 진입점**은 다음과 같음.
> - L0/L1A(운영): `prep/src/loop.sh` → `run_band.sh` → `03_code/01_DN_to_L_band.py`
> - L1A 복사보정(v5): `02_Radiometric_Correction/src/pipeline.py`
> - L1C 기하보정: `03_Geometric_Correction/V3/Code/Full_processing_v2.py`
