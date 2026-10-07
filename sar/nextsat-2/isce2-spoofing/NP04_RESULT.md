# NP04(태안) InSAR 결과 — 20260515 / 20260614

NEXTSat-2 X-band SAR(λ=3.107 cm)를 ISCE2 `stripmapApp`(COSMO-SkyMed 위장) 파이프라인으로
처리한 InSAR 결과. 처리 실행일 2026-07-25.

## 1. 페어 선정

`N2/nextsat2_pairs.xlsx`의 NP04 후보 55개 중 **InSAR 판정을 받은 유일한 페어**:

| 항목 | master | slave |
|---|---|---|
| 날짜 | 20260515 | 20260614 |
| 궤도/룩 | A/L (상행·좌측) | A/L (상행·좌측) |
| 제품 | SSC (SLC) | SSC (SLC) |
| 크기(L×C) | 60817×5193 | 61529×5193 |

- 수직베이스라인 **Bperp = −1419 m** (Bcrit 3606 m, ratio 0.39 → 기하 우수)
- 입사각차 **dInc = 0.09°**, 오버랩 **91%**, 시간차 **30일**
- `nextsat2_pairs.xlsx` 판정: `class=INSAR, insar_ok=o`
- 나머지 54개는 OFFSET-ONLY 또는 INCOMPATIBLE(궤도방향/룩사이드 불일치).

입력 원본(읽기 전용):
- `N2/Taean_recent/20260515/.../N2_SAR_20260515_063509_ST_BB_VV_A_L_SSC_B_NP04.h5`
- `N2/Taean_recent/20260614/.../N2_SAR_20260614_063801_ST_BB_VV_A_L_SSC_B_NP04.h5`

두 파일 모두 `S01/SBI`가 이미 `(L,C,2)` int16 레이아웃이라 `fix_sbi_layout.py` 재작성 불필요.

## 2. 처리 요약

- ISCE2 2.6.3, `stripmapApp`, `sensor=COSMO_SKYMED_SLC`, `do unwrap=False`.
- CSK 위장 패치로 N2 메타데이터 주입 — 매핑 정상(X-band 9.65 GHz, λ=3.107 cm, PRF 6380.8 Hz,
  도플러/레인지타임/처프/방위시각 전부 정상, `None` 필드 없음). `Mapping_Report_*.txt` 참조.
- DEM: `demLat_N36_N37_Lon_E126_E127` (지오이드→타원체고 보정 완료). 커버 범위
  W126.219 / E126.51 / S36.164 / N36.783.
- 멀티룩 25(az)×10(rng) → 멀티룩 격자 2432×519.
- **코레지스트레이션 refinement(`runRefineSecondaryTiming`) 정상 수행**: 391개 오프셋 검출·적용,
  `misreg/misreg.dat`(1.27 MB) 기록. 조용한 skip 없음.

### ⚠️ 실행 환경 주의 (중요)
work_dir를 `/mnt/c`(Windows DrvFs 마운트)에 두면 `misreg/misreg.dat` 쓰기가 `Operation not
permitted`(EPERM)로 실패하고, 위장 패치가 이를 "유효 오프셋 없음"으로 **오인해 refine을 조용히
skip**한다(→ 코레지가 궤도+DEM 기하만으로 대체, CLAUDE.md 경고 함정). 그래서 이 결과는 work_dir를
**리눅스 네이티브 FS(`<WORK_ROOT>/n2_np04_work`)**에서 실행해 refine을 실제로 수행한 뒤 산출물만
여기로 복사한 것임. (입력 h5는 /mnt/c에서 읽기만 하므로 무관.)

검증: `/mnt/c` 실행(refine skip)과 Linux 실행(refine 적용)의 코히런스가 **동일(0.281)** →
저코히런스는 코레지 오차가 아니라 시간적 탈상관 때문임이 입증됨.

## 3. 결과 — 위상 완전 탈상관

| 지표 | topophase.cor | phsig.cor |
|---|---|---|
| 평균 코히런스 | 0.281 | 0.290 |
| 중앙값 | 0.281 | 0.286 |
| 0.3 초과 비율 | 27.6% | 37.6% |
| **0.5 초과 비율** | **0.0%** | **0.1%** |

- 코히런스 평균 ~0.28은 사실상 추정기의 **노이즈 바닥**이며 0.5 초과 픽셀이 전무.
- 필터링 후 wrapped phase도 코히런트 프린지 없는 **완전한 노이즈**(`export/png/rdr/filt_topophase.flat.gray.png`,
  `coherence_summary.png`).
- 결론: **30일 X-band 페어는 위상이 완전히 탈상관 → 간섭 위상/지표변위 추출 불가.**
  진폭 상관(코레지)은 성립하나(도심·나지 특징 생존) 위상은 소멸. 언래핑 무의미(그래서 미수행).
- 태안 인접·동일 지역의 기존 결과(N2 X-band 30~35일 위상 탈상관)와 일치.

## 4. 파일 구성

- `coherence_summary.png` — 진폭/코히런스/wrapped phase/코히런스 히스토그램 요약 (**먼저 볼 것**)
- `Mapping_Report_*.txt` — 두 씬의 메타데이터 매핑 리포트
- `run.log`, `pipeline_stdout.log`, `isce.log` — 실행 로그
- `stripmapApp.xml`, `stripmapProc.xml` — 처리 설정/상태
- `interferogram/` — `topophase.flat`(간섭도), `filt_topophase.flat`(필터), `topophase.cor`/`phsig.cor`(코히런스),
  `topophase.amp`(진폭) + 각 `.geo`(지오코딩) + vrt/xml. (전해상도 `*.full` 중간산물은 용량상 제외)
- `geometry/los.rdr.geo` — 시선벡터(지오코딩)
- `export/png/{geo,rdr}/` — 위상·코히런스·진폭 PNG
- `misreg/` — 코레지 refinement 결과(refine 실제 수행 증거)

## 5. 재현

```bash
conda activate isce2_snaphu
export N2_ROOT="<WORK_ROOT>/n2_np04_work"          # 반드시 Linux 네이티브 FS (DrvFs 금지)
export N2_XML="/mnt/c/N2_InSAR/국립공원 code/result/input_np04.xml"
python /path/to/run_np04.py                      # = n2_main_portable.py, 단 shutil.copyfile 사용
```
`input_np04.xml`은 이 result 폴더에 함께 있음. (표준 `n2_main_portable.py`는 /mnt/c에서
`shutil.copy`의 chmod 때문에 실패하므로 `shutil.copyfile`로 바꾼 러너를 사용.)
