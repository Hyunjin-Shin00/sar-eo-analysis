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
