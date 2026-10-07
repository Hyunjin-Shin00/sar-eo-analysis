# sar/umbra

**Umbra (25 cm 상용 SAR).** SICD 복소 데이터를 직접 파싱함.

## 처리 흐름

```mermaid
flowchart LR
    classDef data stroke-width:1.5px
    classDef proc stroke-width:1.5px
    classDef dec stroke-width:2px
    classDef out stroke-width:2.5px
    sicd[("Umbra SICD (NITF) 복소 SAR")]
    gec[("GEC 지오코딩 산출물")]
    s1[("Sentinel-1 10 m")]
    parse["SICD 직접 파싱 — 복소수 데이터 판독"]
    cmp{"GEC vs SICD 비교 · 해상도 10 m vs 25 cm 직접 대조"}
    geom["스트립맵 · 스캔 모드 관측 기하 정리"]
    ifg["간섭도 생성 · SAR 영상 위 중첩"]
    out(["화산체 고해상도 변화·변위 가시화"])
    sicd --> parse
    gec --> cmp
    parse --> cmp
    s1 --> cmp
    cmp --> geom
    geom --> ifg
    ifg --> out
    class sicd data
    class gec data
    class s1 data
    class parse proc
    class cmp dec
    class geom proc
    class ifg proc
    class out out
```

> - 원통: 입력 자료 · 사각형: 처리 단계 · 마름모: 판정·검증 · 양끝 둥근 사각형: 산출물
> - GitHub 에서 자동 렌더링됨

---

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`sigma0/`](sigma0/) | 복소 진폭 → σ⁰ 변환. |

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `view_umbra_sicd.py` | 아나콘다 프롬프트에서 conda activate sarpy python 12_umbra\view_umbra_sicd.py | — | — |
