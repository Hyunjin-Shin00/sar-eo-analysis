# sar/sentinel-1/change-detection

**변화탐지.** 위상이 아니라 코히런스·진폭의 변화를 본다 — 탈상관이 심한 곳에서도 동작함.

## 처리 흐름

```mermaid
flowchart TD
    classDef data stroke-width:1.5px
    classDef proc stroke-width:1.5px
    classDef dec stroke-width:2px
    classDef out stroke-width:2.5px
    slc[("Sentinel-1A/1C/1D IW SLC 7장 51 GB")]
    opt[("SkySat 0.5 m 전·후 광학")]
    gis[("EMSR884 · OSM 건물 30,558동 · GEM 단층")]
    chain["SNAP: Split → 궤도 → Back-Geocoding → 간섭도 → Deburst → Goldstein → TC"]
    unw["SNAPHU 2.0.4 DEFO · MCF · 10×10 타일 언랩"]
    los["d_LOS = −φλ / 4π"]
    ccd["ΔCoh = γ_pre − γ_co"]
    mask{"γ_pre 저코히런스 마스크 · ΔCoh 0 미만 제외"}
    grade{"EMS 탐지율 보며 2등급 재설정 (RISK 0.1~0.4 / HIGH ≥ 0.4)"}
    clf["건물 피해 분류기 LR + GB (v7)"]
    out(["변위장 · 피해 위험도 등급도 · 건물 단위 판정"])
    slc --> chain
    chain --> unw
    unw --> los
    chain --> ccd
    ccd --> mask
    mask --> grade
    opt --> clf
    gis --> grade
    gis --> clf
    los --> out
    grade --> out
    clf --> out
    class slc data
    class opt data
    class gis data
    class chain proc
    class unw proc
    class los proc
    class ccd proc
    class mask dec
    class grade dec
    class clf proc
    class out out
```

> - 원통: 입력 자료 · 사각형: 처리 단계 · 마름모: 판정·검증 · 양끝 둥근 사각형: 산출물
> - GitHub 에서 자동 렌더링됨

---

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`amplitude/`](amplitude/) | **ACD** — 진폭 로그비로 변화를 봄. 코히런스가 아예 없을 때의 대안. |
| [`coherence/`](coherence/) | **CCD** — 사건 전후 코히런스 저하로 피해를 가림. 건물 붕괴·침수처럼 산란 구조가 바뀌는 변화에 민감. |

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `coh_amp_change.py` | 사구 변화 — 코히런스 변화탐지 + 진폭 다중시점 (N2 A_L). OT와 다른 기법 → taean_CCD. | GeoTIFF | GeoTIFF · PNG 그림 · 텍스트/로그 |
