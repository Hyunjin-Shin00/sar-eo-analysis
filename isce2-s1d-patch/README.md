# isce2-s1d-patch — ISCE2 2.6.x 에 Sentinel-1D 지원 추가

ISCE2 2.6.3 의 TOPS 리더(`components/isceobj/Sensor/TOPS/Sentinel1.py`)는 미션 ID 를 S1A/S1B/S1C 만
하드코딩해, Sentinel-1D SAFE 를 만나면 `ValueError: Encountered unknown mission id S1D` 로 거부한다.
절대궤도 → 상대궤도 변환식 `(orbit − offset) % 175 + 1` 에 S1D 분기를 하나 추가하면 된다(하드코딩 지점은 이 한 곳뿐).

| 파일 | 내용 |
|---|---|
| `sentinel1_s1d.patch` | 원본 대비 unified diff (4줄 추가) |
| `apply_s1d_patch.py` | 활성 env 의 isce 패키지를 찾아 멱등 적용. 원본은 `.bak_pre_s1d` 로 백업. `--check` 로 적용 여부만 확인 |
| `verify_offset.py` | offset 후보 0~174 전수 대입으로 해를 찾고, 다른 지역 S1D 영상(홀드아웃)으로 검증 |

## offset 42 의 근거

- 문헌값을 찾지 못해 CDSE 메타데이터의 (절대궤도, 상대궤도) 실측쌍으로 역산했다.
  3976·4326 → 85, 4085·4260 → 19, 4012·4187 → 121. 175개 후보 중 **42 만 전부 만족(유일해)**.
- 홀드아웃: 별도 조사에서 받은 S1D GRD 3장(절대궤도 3762·3937·4112, 하강 상대궤도 46)에 대입해 **모두 46** 으로 일치.
- 기존값 참고: S1A 73, S1B 27, S1C 172.

## 사용

```bash
conda activate <isce2 env>
python apply_s1d_patch.py --check
python apply_s1d_patch.py
python verify_offset.py
```

## 한계

- ISCE2 상류(upstream)에 같은 수정이 반영되면 불필요해진다. 다른 ISCE2 버전에서는 앵커 문자열이 달라 스크립트가 멈추며, 그때는 patch 파일을 수동 적용한다.
- 2026-08-30 작업 당시 ASF 에서 S1D IW SLC 풀 SAFE 를 찾지 못해 SLC-BURST + `burst2safe` 재조립으로 우회했다. 2026-09 별도 조사에서는 ASF 에서 S1D GRD 를 받았으므로 제품 가용성은 시점에 따라 다르다 — 사용 전 재확인할 것.
