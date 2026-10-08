# eo/bluebon/radiometric/src/radcal

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `band_integrate.py` | BlueBON SRF 파싱 + RadCalNet TOA 스펙트럼의 밴드 적분. | Excel | — |
| `dn_to_radiance.py` | 하이브리드 절대복사보정: v5 상대보정 DN → 분광복사휘도(spectral radiance) → TOA 반사율. | GeoTIFF · CSV | GeoTIFF · 텍스트/로그 |
| `extract_roi_dn.py` | BlueBON 8밴드 보정 DN(TIFF)에서 La Crau ROI 통계 추출 + 위치확인용 퀵룩 생성. | GeoTIFF | PNG 그림 |
| `parse_radcalnet.py` | RadCalNet 산출물(.output) 파서. | — | — |
| `run_lcfr_calib.py` | BlueBON La Crau 대리복사보정 오케스트레이션 (RadCalNet LCFR 기반). | CSV · PNG | 텍스트/로그 |
| `scene_report.py` | 단일 장면 절대복사보정 검증 보고서 생성 (TOA radiance/reflectance vs RadCalNet). | GeoTIFF | PNG 그림 · 텍스트/로그 |
| `vicarious_calib.py` | 대리복사보정(vicarious calibration) 계수 산출 + 플롯 + 리포트. | — | PNG 그림 |

## 주요 인자

- `band_integrate.py` — `--radcal` `--srf` `--utc`
- `dn_to_radiance.py` — `--convert` `--doy` `--lp` `--out-radiance` `--out-toar` `--srf` `--sza` `--tdi`
- `extract_roi_dn.py` — `--decim` `--quicklook` `--roi`
- `parse_radcalnet.py` — `--utc`
- `run_lcfr_calib.py` — `--out` `--overview` `--radcal` `--radcal-adj` `--roi` `--srf` `--tiff` `--utc`
- `scene_report.py` — `--label` `--out` `--rad` `--radcal` `--ref` `--roi` `--srf` `--utc`

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../../../environment/)

### 진입점

```bash
python band_integrate.py 
```
BlueBON SRF 파싱 + RadCalNet TOA 스펙트럼의 밴드 적분. SRF 소스: ref/SpectralResponseFunction.xlsx (시트 BlueBON) - 파장 400~1000nm @ 1nm (내림차순 저장, 601행) - 우측 블록 "Tota

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--srf` |  | `ref/SpectralResponseFunction.xlsx` |  |
| `--radcal` |  | `ref/radcal/LCFR/LCFR01_2026_184_v04.06.output` |  |
| `--utc` |  | `11:08:33` |  |

```bash
python dn_to_radiance.py 
```
하이브리드 절대복사보정: v5 상대보정 DN → 분광복사휘도(spectral radiance) → TOA 반사율. 권장 방식(기존 pipeline.py 보존, 후처리로 절대 스케일만 부여): DN_corr = v5 산출물 (raw−dark)·flat−δ, 정합·flip

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--srf` |  | `<WORK_ROOT>/working/radiometric_correction/ref/SpectralResponseFunction.xlsx` |  |
| `--lp` |  |  |  |
| `--convert` |  |  | v5 8밴드 DN TIFF 경로 (지정 시 8밴드 radiance/TOAR 산출) |
| `--out-radiance` |  |  | 8밴드 radiance float32 출력 경로 |
| `--out-toar` |  |  | 8밴드 TOAR float32 출력 경로(선택) |
| `--sza` |  |  | 태양천정각(deg) |
| `--doy` |  |  | scene day-of-year |
| `--tdi` |  |  | band0..7 TDI 콤마구분 (기본 La Crau 2,4,8,8,16,16,16,4) |

```bash
python extract_roi_dn.py 
```
BlueBON 8밴드 보정 DN(TIFF)에서 La Crau ROI 통계 추출 + 위치확인용 퀵룩 생성. - 8밴드 TIFF는 지리참조가 없으므로(L1A 센서기하) ROI는 픽셀 bbox(row0 row1 col0 col1)로 지정. - 퀵룩: 다운샘플 RGB(Red/

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `tiff` |  |  |  |
| `--quicklook` |  |  | 퀵룩 PNG 출력 경로 생성 |
| `--decim` |  | `20` |  |
| `--roi` |  |  |  |

```bash
python parse_radcalnet.py 
```
RadCalNet 산출물(.output) 파서. RadCalNet `.output` (product level v04) = nadir TOA 반사율 스펙트럼. 포맷(La Crau LCFR01 기준, 탭 구분): - 헤더: Site/Lat/Lon/Alt, Year/DOY

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `path` |  |  |  |
| `--utc` |  | `11:08:33` |  |

```bash
python run_lcfr_calib.py --tiff <값> --srf <값> --radcal <값> --roi <값> --out <값>
```
BlueBON La Crau 대리복사보정 오케스트레이션 (RadCalNet LCFR 기반). 흐름: RadCalNet .output 파싱 -> SRF 밴드적분 -> ROI DN 통계 -> gain 산출 -> CSV/플롯/report.md 생성. 예: python3 ru

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--tiff` | ● |  |  |
| `--srf` | ● |  |  |
| `--radcal` | ● |  | RadCalNet .output (기본 DOY184) |
| `--radcal-adj` |  |  | 인접일 .output (민감도용, 예 DOY183) |
| `--utc` |  | `11:08:33` |  |
| `--roi` | ● |  |  |
| `--out` | ● |  |  |
| `--overview` |  |  | 전체 overview 퀵룩도 생성 |

```bash
python scene_report.py --ref <값> --rad <값> --radcal <값> --utc <값> --roi <값> --out <값>
```
단일 장면 절대복사보정 검증 보고서 생성 (TOA radiance/reflectance vs RadCalNet). 입력: 파이프라인 산출 TOA reflectance/radiance 8밴드 f32 + RadCalNet .output + ROI. 산출: report.md

| 인자 | 필수 | 기본값 | 설명 |
|---|---|---|---|
| `--label` |  | `La Crau 20260528` |  |
| `--ref` | ● |  | TOA reflectance 8밴드 f32 |
| `--rad` | ● |  | TOA radiance 8밴드 f32 |
| `--radcal` | ● |  |  |
| `--srf` |  | `<WORK_ROOT>/working/radiometric_correction/ref/SpectralResponseFunction.xlsx` |  |
| `--utc` | ● |  |  |
| `--roi` | ● |  |  |
| `--out` | ● |  |  |
