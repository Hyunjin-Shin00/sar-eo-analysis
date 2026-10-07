# arctic-sea-ice — 북극 해빙과 항로 개방

해빙 농도(SIC) · 두께(SIT) · 표류(drift) · 실제 선박 통항을 모아
북극항로가 해마다 언제 열리는지를 수치로 만든다.

## 구성

| 디렉터리 | 내용 |
|---|---|
| `download/` | 원자료 자동 수집 |
| `convert/` | NetCDF → GeoTIFF 변환 (극지 투영 처리) |
| `analysis/` | 항로 개방 시기 산출 · 추세 분석 |
| `plot/` | 월별 지도, 표류 벡터장 |

## 자료원

| 변수 | 제품 | 해상도 | 비고 |
|---|---|---|---|
| SIC (농도) | EUMETSAT OSI-SAF | 25 km | 1978년 이후 연속 |
| SIT (두께) | NSIDC, SMOS | 25 km | 겨울철 신뢰도 높음 |
| Drift (표류) | OSI-SAF OSI-405 | 62.5 km | 48시간 이동량 |
| 선박 | Global Fishing Watch API | 포인트 | AIS 대체 자료 |

## 파일

```
download/
  osisaf_sic.py          OSI-SAF 해빙농도 FTP 수집
  smos_sit.py            SMOS 해빙두께 수집
  gfw_vessels.py         GFW API 선박 데이터 (날짜별)
convert/
  osisaf_nc2tif.py              SIC NetCDF → GeoTIFF
  nsidc_thickness_nc2tif.py     NSIDC 두께 변환
  smos_thickness_nc2tif.py      SMOS 두께 변환
  osisaf_drift_nc2tif.py        표류 벡터 변환
analysis/
  nsr_opening_2012_2026.py   2012–2026 월별 집계 → 연도별 개방 시기
  nsr_analysis.py            구간별(서·중·동) 개방 패턴 · 추세
plot/
  monthly_map.py       월별 SIC 지도 시리즈
  drift_quiver.py      표류 벡터 quiver 플롯
```

## 개방 판정 기준

항로 구간의 SIC가 **15% 미만**이면 통항 가능으로 본다.
이는 해빙 범위(sea ice extent)의 관례적 기준과 같다.
선박 등급과 빙질을 함께 고려하는 IMO **RIO(Risk Index Outcome)** 는 아직 반영하지 않았다.

## 실행

```bash
export GFW_API_TOKEN=...

python download/osisaf_sic.py --start 2012-01 --end 2026-09
python convert/osisaf_nc2tif.py
python analysis/nsr_opening_2012_2026.py
```

## 한계

현재는 **사후 분석**이다. 실시간 개방 예측 모델은 아직 없다.
여름 융빙기에는 PMW 기반 SIC 오차가 ±10~15%까지 커지므로,
개방 시작 시점 추정에 그만큼 불확실성이 실린다.
