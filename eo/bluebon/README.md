# eo/bluebon

**BlueBON — 자사 초소형 위성.** L0 원시 패킷부터 L1C 까지의 전처리 전 과정과, 그 위에 올린 응용. 센서를 직접 다루는 유일한 모듈이라 복사보정·기하보정·MTF 가 모두 들어 있음.

## 처리 흐름

```mermaid
flowchart TD
    classDef data stroke-width:1.5px
    classDef proc stroke-width:1.5px
    classDef dec stroke-width:2px
    classDef out stroke-width:2.5px
    raw[("다운링크 원본 — 64 MiB 조각 · AES 암호화")]
    l0["L0 — 밴드별 12 bit DN, 4096 × 16000 uint16"]
    rad["(raw − dark_ref) · flat_PRNU − δ"]
    reg["서브픽셀 밴드정합 · jitter / 회전 보정"]
    l1a["L1A — TOA 복사휘도 float32 (좌표계 없음)"]
    toar["TOA 반사도 — 태양천정각 · 일-지 거리 · Thuillier F0"]
    vic{"대리보정 — La Crau RadCalNet 지상 TOA 를 SRF 로 적분해 대조"}
    x{"Sentinel-2 MSI 교차보정 — 이득·오프셋 독립 확인"}
    geo["기하보정 V3 — 특징점 정합 → 이상점 제거 → RPC 적합 → 스트립 정렬"]
    l1c(["L1C — 정사보정 UTM 4.8 m 격자"])
    mtf["MTF 에지법 측정 → 추정 커널로 디블러링"]
    pt{"포인팅 오차 — Pearson · Spearman · Kendall 3계수 동시 확인"}
    raw --> l0
    l0 --> rad
    rad --> reg
    reg --> l1a
    l1a --> toar
    toar --> vic
    vic --> x
    l1a --> geo
    geo --> l1c
    l1a --> mtf
    l1c --> pt
    class raw data
    class l0 proc
    class rad proc
    class reg proc
    class l1a proc
    class toar proc
    class vic dec
    class x dec
    class geo proc
    class l1c out
    class mtf proc
    class pt dec
```

> - 원통: 입력 자료 · 사각형: 처리 단계 · 마름모: 판정·검증 · 양끝 둥근 사각형: 산출물
> - GitHub 에서 자동 렌더링됨

---

## 먼저 볼 문서

| 문서 | 내용 |
|---|---|
| [`SPEC.md`](SPEC.md) | **센서 사양** — 밴드 구성·SRF 가중 중심·TDI별 포화 DN·검출기·처리 레벨·정량 분석 시 주의 |
| [`OVERVIEW.md`](OVERVIEW.md) | 전체 처리 흐름과 코드별 상세, **알려진 문제 12건** |
| [`THIRD_PARTY.md`](THIRD_PARTY.md) | 포함하지 않은 제3자 라이브러리와 업스트림 |
| [`../../docs/reports/bluebon-pointing-error.md`](../../docs/reports/bluebon-pointing-error.md) | 포인팅 오차 상관분석 보고서 |

## 하위

| 디렉터리 | 내용 |
|---|---|
| [`deblur-mtf/`](deblur-mtf/) | **MTF 와 디블러링.** 에지법으로 MTF 를 재고, 추정한 커널로 흐림을 되돌림. |
| [`downstream/`](downstream/) | **응용.** L1C 영상을 받아 대기·해양·화질 쪽으로 확장한 작업들. |
| [`geometric/`](geometric/) | **기하보정 V3.** 특징점 정합으로 RPC 를 맞추고 스트립을 정렬함. 웹 UI 와 도커 구성 포함. |
| [`l0-to-l1a/`](l0-to-l1a/) | **L0 → L1A.** 원시 바이너리 패킷을 읽어 영상으로 만듦. FEE/CEM 텔레메트리 점검과 촬영 시험 스크립트 포함. |
| [`pointing/`](pointing/) | 포인팅 오차와 궤도·자세 메타데이터의 상관분석. |
| [`preprocessing-legacy/`](preprocessing-legacy/) | 로컬 PC 에 있던 구 전처리 스크립트 — 위 `l0-to-l1a/` 로 대체됐지만 배치 쉘 흐름 참고용으로 남겨 둠. |
| [`radiometric/`](radiometric/) | **복사보정.** DN 을 물리량(복사휘도·반사도)으로 바꾸고, 밴드 간 정합과 정확도를 검증함. |
| [`research/`](research/) | L0→L1 처리 연구 코드 — LUT 생성, 기하 시뮬레이션, 검출기 시험. |
