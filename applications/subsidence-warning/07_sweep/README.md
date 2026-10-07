# 07_sweep

SBAS 처리 파라미터(coh · tcoh · 범위)를 **스윕**하며 지반침하 발생/미발생 판별력을 최적화하는 단계임.

| 코드 | 입력 | 출력 |
|---|---|---|
| `sweep_config.py` | — (단일 진실원) | 스윕 대상 7개 AOI, 경로·파라미터 조합 정의 |
| `swept_loader.py` | 스윕 산출 SBAS CSV | 평가용 bank 구조. `loaders` 의 파싱·`_deunwrap` 재사용, npz 캐시는 건드리지 않음 |
| `featx_cache.py` | 지역·coh·tcoh·kind 별 SBAS/PS_SBAS 결과 | 확장 피처 npz — 버퍼 집계 5종(max·p90·top3·med·초과비율) × 베이스 12종 = 64피처. 존재 파일 스킵으로 재개 가능 |
| `discrim_eval.py` | `featx_cache` npz, 사고 목록, 랜덤 비사고 배경 | 조합별 판별력 표 — 지표 × α × 버퍼(200/300 m) × 범위 × 12조합. in-sample + LOO + 부트스트랩 CI + 순열 null(576설정 선택보정) |

- 송도는 ASC+DSC 결합(`SBAS_AD` · `PS_SBAS_AD`)을 추가로 평가함
- 과적합 통제가 핵심 — 설정 수가 576개라 선택보정 없이는 최적값이 과대평가됨
