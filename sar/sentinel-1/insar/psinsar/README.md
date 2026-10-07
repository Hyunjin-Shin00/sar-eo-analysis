# sar/sentinel-1/insar/psinsar

**PS-InSAR** — 시간에 걸쳐 안정한 점(영구산란체)만 골라 변위를 잼. 도심·구조물에 유리.

## 처리 흐름

```mermaid
flowchart TD
    classDef data stroke-width:1.5px
    classDef proc stroke-width:1.5px
    classDef dec stroke-width:2px
    classDef out stroke-width:2.5px
    subgraph g0["PS 경로"]
    direction TB
    ps["StaMPS 포팅판 — 진폭분산 0.4 · 결맞음 0.4"]
    psmem["ps_select 를 fork 공유 + 워커 재생성으로 90 GB → 6.4 GB"]
    ref["기준점 2안 — 전역평균 차감 / 반경 150 m 안정영역 자동선정"]
    end
    subgraph g1["SBAS 경로"]
    direction TB
    net["연결 4개 · 72일 이내 쌍 · 9×3 멀티룩"]
    unw["snaphu 언랩 — 최대결맞음 픽셀 기준"]
    inv["결맞음 가중 역산 · 에폭별 평면 제거 · 시간결맞음 ≥ 0.7"]
    tile["광역: 타일 분할 → 채택률 낮으면 2×2 재분할 → 중첩부 평면 정합 병합"]
    end
    slc[("Sentinel-1 SLC — 상승 + 하강")]
    stack["ISCE2 topsStack 코레지 (씬별 병렬 8프로세스)"]
    dec["상승·하강 LOS 2×2 연립 → 수직 · 동서 분리"]
    cmp{"PS–SBAS 300 m 공통격자 상관 r · 잔차 RMS"}
    out(["연 변위속도도 · 지점별 시계열 · 수직/동서 성분"])
    slc --> stack
    stack --> ps
    ps --> psmem
    psmem --> ref
    stack --> net
    net --> unw
    unw --> inv
    inv --> tile
    ref --> cmp
    tile --> cmp
    tile --> dec
    dec --> out
    cmp --> out
    class slc data
    class stack proc
    class ps proc
    class psmem proc
    class ref proc
    class net proc
    class unw proc
    class inv proc
    class tile proc
    class dec proc
    class cmp dec
    class out out
```

> - 원통: 입력 자료 · 사각형: 처리 단계 · 마름모: 판정·검증 · 양끝 둥근 사각형: 산출물
> - GitHub 에서 자동 렌더링됨

---

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`ascending/`](ascending/) | 상승궤도 PS 처리 체인. |
| [`descending/`](descending/) | 하강궤도 PS 처리 체인. |
| [`stamps_patches/`](stamps_patches/) | StaMPS 파이썬 포팅본에 적용한 패치 — 업스트림 원본은 포함하지 않음. |

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `env.sh` | PS-InSAR 세션 환경 (일반화본). ISCE2 + StaMPS Python 포팅(psi_python) 경로는 설치 환경에 맞게 지정. 사용: source env_seoul.sh | — | — |
| `process_region.sh` | 일반화 지역 처리: PS(차감전/후/raw + 클릭맵2) + SBAS(차감전/후 + 클릭맵2) → CLAB/{REGION}/{PS,SBAS} usage: process_region.sh REGION | shp/GeoJSON · JSON | — |
| `ps_extract.py` | PS 후보 추출 → LOS 속도·시계열 산출 | shp/GeoJSON | CSV |
| `stamps_mp_patch.py` | 런처용 monkeypatch: ps_select(step3)의 OOM 폭증을 막는 '스마트 Pool'. | — | — |
