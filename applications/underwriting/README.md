# applications/underwriting

공간정보 기반 중소 공장 인수심사 — 건물통합정보·업종 매칭.

## 처리 흐름

```mermaid
flowchart TD
    classDef data stroke-width:1.5px
    classDef proc stroke-width:1.5px
    classDef dec stroke-width:2px
    classDef out stroke-width:2.5px
    fac[("공장등록현황 (대구 11,744행)")]
    bld[("GIS건물통합정보 shapefile — 익명 필드 A0~A39")]
    ksic[("KSIC 11차 연계표")]
    prof["프로파일링 — 단지 차수 표기 2종 · 주원자재 44% 결측 확인"]
    rev["익명 필드 역판별 — 건폐율 A23/A22 · 용적률 A24/A22 · 주차 A36×11.5 로 검증"]
    link["주소 → PNU → 지번 → 업종명 → KSIC 대·중분류 연계"]
    norm["지번 꼬리표 · 외 N 종 · 공백 차이 정규화"]
    pnu{"주용도 = 공장(A29 17000) 을 PNU 로 묶어 연면적 합 vs 3,000㎡ — 폴리곤 겹침 선택 시 3~8배 과대"}
    src{"업종·위험물 정보원 후보 전수 확인 → 사용 가능 여부 판정"}
    out(["대상 공장 식별 · 규모 판정 · 활용 가능 정보원 목록"])
    fac --> prof
    bld --> rev
    prof --> link
    rev --> link
    ksic --> link
    link --> norm
    norm --> pnu
    pnu --> src
    src --> out
    class fac data
    class bld data
    class ksic data
    class prof proc
    class rev proc
    class link proc
    class norm proc
    class pnu dec
    class src dec
    class out out
```

> - 원통: 입력 자료 · 사각형: 처리 단계 · 마름모: 판정·검증 · 양끝 둥근 사각형: 산출물
> - GitHub 에서 자동 렌더링됨

---

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `factory_by_sgg.py` | GIS건물통합정보(대구)에서 시군구별 전체/주용도=공장 건물 수, 달서구 공장 상위 법정동 집계. | — | — |
| `fig_ksic_mix.py` | 성서산단 등록 공장의 KSIC 중분류 구성 막대그림 (ksic_link.py 의 매칭 결과 사용). | — | PNG 그림 |
| `fig_source_coverage.py` | 자료원별 커버리지(특건 공백률) 그림 | PNG | PNG 그림 |
| `fig_workflow.py` | 인수심사 워크플로 도식 | PNG | PNG 그림 |
| `ksic_link.py` | 주소(지번) → 공장등록현황 업종명 → 한국표준산업분류(KSIC 11차) 대·중분류 연결. | CSV | — |
| `profile_dbf.py` | GIS건물통합정보 shapefile 속성(A0~A33) 데이터기반 프로파일링. | — | — |
| `profile_phase0.py` | Phase 0 - 대구 산업단지 기업 등록현황 CSV 프로파일링. | CSV | — |
| `special_bld_gap.py` | 특수건물(특건) 공백 산출 — 성서산단 공장 중 연면적 3,000㎡ 미만 비율. | PNG | PNG 그림 |
| `verify_field_mapping.py` | 애매한 필드 정밀 검증: ID 유일성, A15 관계, A35 형식, 면적/율 관계식. | — | — |

## 주요 인자

- `ksic_link.py` — `--coverage`
- `special_bld_gap.py` — `--fig`
