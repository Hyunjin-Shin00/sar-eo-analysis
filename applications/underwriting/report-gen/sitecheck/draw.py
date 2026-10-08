"""그림 규칙 — **두 도구가 같은 방식으로 그린다.**

**그림을 만드는 곳은 이 파일 하나다.** `demo.py`·`hand_writting.py` 는 GT 로 값을 내고(`demo.json`),
`run.py` 는 모델로 값을 내며(`result.json`), 그림은 둘 다 여기 `result_images()` 가 낸다.
도구마다 각자 그리면 같은 물건이 도구마다 다른 색·다른 굵기로 나와서 어느 그림이 맞는지
사람이 판단할 수 없다. 이 파일은 그 **그림 규칙**이다 — 팔레트 · 선 굵기 · 라벨 · 창 ·
항목별 레이어.

이름과 판정어는 **「SatCHAT 화면 설계서 v38」 BR-13** 을 따른다 — 받는 쪽이 그 화면으로
결과를 보고 있어서 지도와 표가 같은 말을 써야 한다.

    판독한 건물   A동 · B동 · C동          건축면적 큰 순 (`dong_names`)
    외부 건물     ①②③ + 회색 점선         이 지번이 아닌 건물 (`ext_index`)
    이격거리      안전 · 주의 · 위험        「위반」·「심각」은 쓰지 않는다 (`sep_level3`)
    대장 정합     일치 · 불일치            대장에 없는 동도 불일치 (`led_match`)

바탕은 **원본 정사영상에서 창만 떠서 그 창의 분포로 다시 늘이고**(`_scene_raw` · `_stretch`)
**중간값을 목표에 앉힌다**(`_tone` · `TONE_MED`). `scene.png` 는 1만 픽셀 장면 전체를 한 벌의
눈금으로 8bit 에 눌러 둔 것이라 필지 하나만 떼면 대비가 죽는다 — 모델·VLM 입력은 그 PNG 를
그대로 쓰되(그 위에서 값을 냈다), **사람이 보는 그림은 무손실 원본(uint16·LZW)에서 뜬다.**
450 MB PNG 를 디코드하지 않으니 덤으로 빠르다. **밝기는 값에 닿지 않는다** — 이 파일은
사람이 보는 그림만 만들고, 판정은 이미 나 있다.

규칙
----
· **바탕이 보여야 한다.** 선은 1~3 px 이고 밑에 어두운 테(halo)를 깐다 — 굵게 하면 잰
  자리를 가리고, 얇게만 하면 밝은 지붕 위에서 사라진다.
· 채움은 알파 40 이하. 적재물 본래 색(컨테이너·목재)이 보여야 무엇인지 알 수 있다.
· **라벨은 맨 나중에** 그린다. PIL 은 같은 레이어에서 픽셀을 덮어쓰므로(알파 합성이 아니다)
  나중에 그린 반투명 채움이 먼저 그린 글자를 지운다.
· 판정색은 윤곽선·측정선·글자에만. 분류색(적재물)은 판정색·건물색·필지색과 겹치지 않게 골랐다.
· 항목마다 **그 판정에 필요한 것만** 얹는다(이격에 등록기하·법정선을 얹지 않는다).

항목별 레이어
-------------
    poly_draw    건물폴리곤 필지 · 대상 건물(A동) · 옆 지번 건물(점선) — **판정 없음**
    sep_draw     이격거리   필지 · 대상 건물(A동) · 외부 건물(① 점선) · 방향별 측정선
    yard_draw    야적물     필지 · 건물(A동) · 탐지된 적재 구역
    ledger_draw  대장 대조  필지 · 건물을 「일치 / 불일치」 두 색으로만

    v = View(site)                                   필지 주변 crop
    img = v.panel(sep_draw(site, blds, near, sep))   그림 한 장(PIL Image)
    legend = sep_legend(sep)                         그림에 실제로 칠한 색만
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from sitecheck import settings as config
from sitecheck import console as con
from sitecheck import rules
from sitecheck.steps import s2_yard, s3_separation

# 판정색은 채도를 낮춰 잡았다 — 위성 위에서 선만으로 읽혀야 한다.
BG = (17, 18, 21)
INK = (238, 240, 244)
DIM = (150, 158, 170)
PARCEL = (255, 208, 64)          # 연속지적도 필지
GTC = (96, 214, 255)             # GT 건물(이 지번)
NEAR = (198, 206, 216)           # GT 건물(옆 지번)
GIS = (118, 232, 148)            # GIS건물통합정보 footprint = 등록 기하
MEAS = (226, 232, 240)           # 측정선(판정 전)
COL = {"경고": (242, 88, 74), "해당": (242, 88, 74), "주의": (246, 160, 52),
       "참고": (226, 198, 66), "기록": (150, 158, 170),
       "이상없음": (86, 200, 120), "정보없음": (150, 155, 165)}
# **적재 구역은 한 색이다**(2026-08-23). 예전에는 분류마다 색을 달리했는데(목재 주황 · 합성수지
# 보라 · 폐기물 분홍 · 그 밖 마젠타), 그림이 말하는 것은 「여기에 무엇이 쌓여 있다」와 「건물에서
# 몇 m 인가」이고 **무엇이 쌓였는지는 겉모습으로 가른 값**이라 색을 넷으로 갈라 실을 만큼
# 단단하지 않다. 색이 넷이면 범례도 넷이고, 읽는 쪽은 판정색(빨강·주황·초록)과 분류색을 같은
# 화면에서 가려야 했다. 구역은 이제 **표의 구역 코드(Y0001…)로 되짚는다.**
#
# 판정색(빨강·주황·초록)과도, 건물 시안·필지 노랑과도 겹치지 않는 주황이다 — 넷 중 「목재·
# 팔레트」가 쓰던 그 색을 그대로 남겼다.
YARD_ZONE = (214, 152, 84)

PANEL_PX = 1000                  # 결과 그림 한 변의 목표 픽셀(화면으로 보는 결과 그림)
# 확대 한도. 영상은 0.5 m/px 가 천장이라 키운다고 지붕이 선명해지지는 않지만, **얹는 것
# (선·배지·글자)은 캔버스가 클수록 선명해진다.** 인쇄물에서 흐린 것은 그쪽이었다 — 보고서는
# 125 mm 폭에 300 dpi ≈ 1,500 px 가 필요한데 552 px 를 늘려 넣고 있었다.
MAX_UP = 8.0
WIN_PAD_M = 20.0                 # 창 여백 — 세 도구가 같은 범위를 봐야 나란히 비교된다
# **26 → 20 m**(2026-08-27, 사용자 결정). 여백은 필지 크기와 무관한 고정값이라 줄이면
# 물건마다 지붕이 그만큼 커진다. 판정에는 닿지 않는다 — 판정선인 도달거리는 11.3 m 라
# (`rules.SEP_REACH_M`) 20 m 창에 다 들어온다.
#
# 잃는 것은 **도달거리 밖 상대의 배지**다. 저장된 5물건에 재 보니 창을 아주 벗어나는 줄이
# 한 곳에서 둘인데(호산동 702-5 의 N0005 21.3 m · N0018 29.8 m — 둘 다 이상없음) 그중
# N0018 은 26 m 에서도 이미 번호가 없었다(`sep_hidden` 머리글의 실측 3줄에 든다). 늘어난
# 것은 N0005 한 줄이고, 번호를 못 받은 「안전」 줄은 **종이에서 빠진다**(값 파일
# `separation.geojson` 에는 그대로 남는다 · `sep_hidden`).
#
# 되살리려면 그 물건에 `win_pad` 를 주면 된다(손보정 · [[hand_writting.py]] — 호림동 3-10 과
# 신당동이 그렇게 40 m 를 쓴다).
# **물건 하나만 창을 넓히고 싶을 때가 있다.** 여백은 필지 크기와 무관한 고정값이라, 이격
# 상대가 여백보다 멀리 있으면 그 상대에게 그은 측정선이 종이 밖에서 끊기고 배지(①②③)도 놓을
# 자리가 없다(`ext_index` 가 창 밖 건물에 번호를 주지 않는다 — 표에는 있고 지도에는 없는
# 번호를 만들지 않으려고 그렇게 해 두었다). 여백을 전부 늘리면 모든 물건의 지붕이 작아지므로
# **그 상대를 넣기로 정한 물건만** 넓힌다.
#
# 그 「정한 물건」의 목록은 **여기 없다** — 손보정이므로 [[hand_writting.py]] 에 있고, 값은
# `site["win_pad_m"]` 로 실려 온다([[hand.py]] `win_pad`). 예전에는 이 파일에 주소를 키로 한
# 표가 있었고, 그래서 `run.py` 가 자기도 모르게 사람이 정한 창으로 그리고 있었다.
#
# **site 에 싣는 이유**는 보고서가 값 파일을 디스크에서 다시 읽기 때문이다
# ([[report/single.py]] `build`) — 인자로 넘기면 그 경로에서 끊긴다.
#
# `win_box` 와 `View` 가 같은 값을 쓴다 — 갈리면 그린 창과 번호를 매긴 창이 달라져 번호 없는
# 점선이 생긴다.


def win_pad(site, pad_m=None):
    """이 물건의 창 여백(m). 준 값 → site 에 실려 온 손보정 → 기본값 순."""
    if pad_m is not None:
        return float(pad_m)
    return float((site or {}).get("win_pad_m") or WIN_PAD_M)
DIRS = s3_separation.DIRS         # 방향 이름은 잰 곳이 정한다(steps/s3_separation)
DIRS8 = s3_separation.DIRS8       # 표·지도에 적는 8방위
REACH_M = rules.SEP_REACH_M       # 이 밖에서는 판정이 갈리지 않는다 — 근거는 [[rules.py]]

# ── 설계서 BR-13 판정어 · 배지색 ────────────────────────────────────────────
# 「SatCHAT 화면 설계서 v38」 3면(판정어·등급 총괄)이 화면·보고서 문구를 못 박아 두었다.
#
#     이격거리 판정   안전 · 주의 · 위험      「위반」·「심각」은 쓰지 않는다
#     대장 정합       일치 · 불일치           동 이름(A동·B동)을 맨 앞에 둔다
#     판정 불가       회색 배지               등급을 낼 수 없을 때
#
# `rules` 의 7단계(경고·해당·주의·참고·기록·이상없음·정보없음)는 **그대로 둔다** — 그쪽이
# 값과 근거 조문의 단일 출처다. 여기서 하는 일은 그 등급을 화면 문구로 옮기는 것뿐이다.
SEP3 = {"경고": "위험", "해당": "위험", "주의": "주의", "참고": "주의",
        "기록": "안전", "이상없음": "안전", "정보없음": "판정 불가"}
SEP3C = {"위험": (242, 88, 74), "주의": (247, 197, 66),      # 주의는 **노랑**(설계서)
         "안전": (86, 200, 120), "판정 불가": (150, 155, 165)}
MATCH3 = {"일치": (86, 200, 120), "불일치": (246, 160, 52),   # 일치 초록 · 불일치 주황
          "판정 불가": (150, 155, 165)}
EXT = (222, 228, 236)            # 외부 건물(이 지번 아님) — 회색 점선
PLATE = (16, 18, 22)             # 배지 밑판 — 위성 위에서 글자가 배경을 타지 않게


def sep_level3(level):
    """`rules` 7단계 → 설계서 3단계(안전·주의·위험). 모르면 「판정 불가」."""
    return SEP3.get(level, "판정 불가")


def led_match(props, parcel=None):
    """동별 대장 정합 → 「일치」/「불일치」/「판정 불가」.

    설계서 ⑤: **대장에 없는 동도 「불일치」**다 — 그래서 등급이 「이상없음·기록」이 아닌
    모든 경우를 불일치로 접는다(증축·미등록을 색으로 나누지 않는다).

    동별 판정이 없으면 **필지 총량 판정(`parcel`)으로 갈음한다.** 등록 기하
    (GIS건물통합정보)가 없어 어느 판독 건물이 대장 몇 동인지 못 정하는 필지가 흔한데, 그때
    「판정 불가」로 두면 **대장과 잘 맞는 물건이 통째로 회색**으로 나온다(실측 구미 공단동
    293-25: 대장 2동 1,659 ㎡ · 판독 2동 1,725 ㎡ 로 맞는데 전부 회색이었다). 짝을 못 지은
    것과 대조 결과가 나쁜 것은 다른 일이므로, 낼 수 있는 판정(총량)을 낸다.
    """
    p = props or parcel
    if not p or p.get("level") == "정보없음":
        # 「정보없음」은 **낼 수 없는 판정**이지 나쁜 판정이 아니다 — 이 분기가 없으면
        # 판독이 크게 모자란 동이 지도에서 주황 「불일치」로 칠해지는데, 표는 같은 동을
        # 「판정 불가」라고 적는다(실측 구미 공단동 150·282).
        return "판정 불가"
    return "일치" if p.get("level") in ("이상없음", "기록") else "불일치"


def led_parcel(led):
    """ledger 레이어의 **필지 총량 판정** — 동별 판정이 없을 때 갈음할 값."""
    return next((f["properties"] for f in (led.get("features") or [])
                 if f["properties"].get("scope") == "parcel"), None)


# ── 동 이름 · 외부 건물 번호 ────────────────────────────────────────────────
# `bld_id`(B0007 …)는 결과 파일 안의 일련번호라 사람이 부르는 이름이 아니다. 설계서는 판독한
# 건물을 **A동 · B동 · C동**, 이 지번이 아닌 건물을 **①②③** 으로 부른다. 그림과 표가 같은
# 이름을 쓰려면 이름을 정하는 자리가 하나여야 하므로 여기서 정한다.
_ABC = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"


def _dong(i):
    if i < len(_ABC):
        return f"{_ABC[i]}동"
    return f"{_ABC[i // len(_ABC) - 1]}{_ABC[i % len(_ABC)]}동"       # 27동째부터 AA동


def dong_names(blds):
    """bld_id → 「A동」. **값에 적힌 이름을 그대로 쓴다**(`properties.dong`).

    이름을 정하는 곳은 [[steps/s1_building.label_features]] 하나다 — 건축면적 큰 순(설계서
    목업이 A동 1,860 ㎡ · B동 1,200 ㎡ 로 큰 것부터 붙였다). 그림이 여기서 다시 계산하면
    같은 물건의 표와 그림이 갈릴 수 있으므로 읽기만 한다.

    `dong` 이 없는 옛 결과만 예전 방식으로 매긴다.
    """
    fs = list(blds.get("features") or [])
    if any((f.get("properties") or {}).get("dong") for f in fs):
        return {f["properties"].get("bld_id"): f["properties"].get("dong") for f in fs}
    fs = sorted(fs, key=lambda f: (-(f["properties"].get("arch_area_m2") or 0),
                                   str(f["properties"].get("bld_id"))))
    return {f["properties"].get("bld_id"): _dong(i) for i, f in enumerate(fs)}


def dist_text(m, *, res_m=None):
    """거리 글자 — **잰 값을 그대로 적고**, 영상 1 px 이하일 때만 눈금 자체를 적는다.

    눈금은 영상 픽셀이다(0.5 m/px). 1 px 를 넘는 값은 화면에서 실제로 벌어진 것이 보이므로
    숫자가 뜻을 가진다 — 뭉뚱그려 「1 m 미만」이라고 적으면 잰 것을 버리는 셈이다.

    1 px 이하는 **잰 값이 아니라 「0.5 m 이하」**로 적는다(등호를 포함한다 — 0.5 m 는 눈금
    그 자체라 그 아래와 가릴 수 없다). 두 지붕 폴리곤이 붙어 있다는 뜻일 뿐, 실제 외벽 사이가
    붙었는지 좁은 통로인지는 이 영상으로 가릴 수 없다 — 실측 호산동 704-1 의 B동↔C동은
    0.06 m 로 나오는데 원본 픽셀을 8배로 확대해 보면 그 자리에 3~4 px(약 1.5~2 m) 폭의 어두운
    띠가 있다. 사람이 지붕 두 장을 골짜기 가운데선까지 그렸기 때문이다. 그 값을 「0.1 m」로
    적으면 재지 않은 것을 잰 것처럼 말하게 된다.

    **「맞닿음」이라 적지 않는다**(2026-08-23). 붙었다는 것은 이 영상으로 확정할 수 없는
    사실인데 그 말은 확정한 것처럼 읽힌다 — 눈금을 그대로 적으면 「이 아래는 못 가른다」만
    말하게 된다.

    두 건물 사이의 **상대** 거리이므로 2차 정합 잔차(장면 전체를 통째로 옮기는 값)는 여기에
    섞이지 않는다 — 그것까지 오차로 잡아 1 m 로 뭉쳤던 것이 지나쳤다(2026-08-20 정정).
    """
    if m is None:
        return "—"
    thr = rules.SEP_TOUCH_M if res_m is None else res_m
    return f"{thr:.1f} m 이하" if m <= thr else f"{m:.1f} m"


def sep_touching(sep, *, skip=()):
    """눈금(0.5 m) 이하로 붙은 **우리 동끼리의 쌍** — 이격으로 세지 않고 따로 알린다.

    필지 밖 상대는 여기 들어오지 않는다(`_own_touch`) — 이유는 `sep_pairs` 에 적었다.
    """
    return [f for f in (sep.get("features") or []) if _own_touch(f["properties"], skip)]


def _own_touch(p, skip=()):
    """**눈금 이하라서 빼는 쌍인가.** 「우리 동끼리」일 때만 참이다.

    이격에서 빼는 근거는 `rules.SEP_TOUCH_M` 인데, 그 근거는 **한 공장동의 베이를 지붕
    폴리곤이 따로 그린다**는 것이다(호산동 704-1 B↔C 는 0.06 m 로 나오지만 원본 픽셀을
    8배로 확대하면 그 자리에 3~4 px 폭 어두운 띠가 있다). 그것은 **우리 건물이 쪼개져 그려진**
    이야기이므로 옆 지번 건물에는 해당하지 않는다.

    지번 경계를 넘어 지붕이 붙은 것은 쪼개짐이 아니라 **가장 나쁜 소견**이다 — 그것을 빼면
    표가 「둘레에 이 지번 밖 건물이 없음」이라고 말한다(실측 고잔동 690-5: 0.0 m 인 옆 지번
    건물이 둘인데 필지밖 표가 비었다). 그래서 필지 밖은 눈금 이하라도 낸다. 거리 칸은
    `dist_text` 가 「0.5 m 이하」로 적으므로 재지 못한 것을 잰 척하지도 않는다.

    눈금 자체(0.5 m)는 **가르는 쪽이 아니라 뭉치는 쪽**이다 — `dist_text` 와 같은 등호를
    쓴다. 둘이 갈리면 표에 「0.5 m 이하」라고 적힌 쌍이 이격으로도 한 번 더 세어진다.
    """
    if p.get("dir") in skip:
        return False
    if not p.get("same_parcel"):
        return False
    return (p.get("dist_m") or 0) <= rules.SEP_TOUCH_M


def sep_pairs(sep, *, skip=()):
    """이격 결과에서 **그릴·실을 쌍** — 둘을 뺀다.

        ① 도로면(`skip`)
        ② **우리 동끼리 눈금(0.5 m) 이하로 붙은 쌍** — 떨어진 거리가 아니라 한 덩어리다.
           옆 지번 건물은 눈금 이하라도 빼지 않는다(`_own_touch` 에 근거)

    **여기서 접는 일은 이제 없다.** 예전에는 「외부 건물 하나에 우리 동 하나」를 이 함수가
    골랐다 — 그때는 [[steps/s3_separation]] 이 건물마다 둘레 25 m 안 상대를 전부 내서, 안쪽에
    갇힌 동까지 바깥 건물마다 선이 이어졌기 때문이다. 지금은 필지 밖이 **대지경계선 구간마다
    한 줄**로 나오므로(`run_id`) 접을 것이 없고, 접으면 오히려 잃는다 — 같은 상대가 떨어진 두
    구간을 이길 수 있어서(L 자로 감싼 필지) 상대 id 로 접으면 구간 하나가 사라진다.

    옛 결과 파일(`run_id` 가 없는 것)은 그때 규칙으로 접어야 그림이 예전과 같으므로 그 길을
    남겨 둔다 — 세는 방식이 갈린 결과를 한 그림에 섞지 않는다.
    """
    ins, ext, runs = [], {}, []
    for f in sep.get("features") or []:
        p = f["properties"]
        d = p.get("dist_m")
        # 눈금 이하 제외는 **우리 동끼리에만** 적용한다 — 근거는 `_own_touch`.
        if p.get("dir") in skip or d is None or _own_touch(p, skip):
            continue
        pair = p.get("pair") or []
        if p.get("same_parcel") or len(pair) < 2:
            ins.append(f)
        elif p.get("run_id") is not None:
            runs.append(f)                      # 이미 구간마다 하나 — 그대로 낸다
        elif pair[1] not in ext or d < ext[pair[1]]["properties"]["dist_m"]:
            ext[pair[1]] = f                    # 옛 결과 — 그때 규칙으로 접는다
    return ins + runs + list(ext.values())


def sep_nearest(sep, *, skip=()):
    """건물마다 **필지 안 한 쌍 · 필지 밖 한 쌍**을 골라 낸다 — 1면 요약이 쓴다.

    `s3_separation` 은 건물마다 동서남북 네 방향을 각각 재서 방향마다 한 선을 낸다. 그 값은
    결과 파일에 그대로 남기되 **보고서에는 한 쌍만** 싣는다. 축마다 선을 그으면 한 필지에
    선이 넷씩 깔려(실측 호산동 704-1: 4동 × 4방향 = 16선) 정작 판정이 갈리는 쌍이 묻힌다.
    설계서 BR-13 도 축이 아니라 **인접 건물**을 센다.

    고르는 잣대는 **판정이 가장 나쁜 쪽**이고, 같으면 가까운 쪽이다. 「가장 가까운 쪽」으로
    고르면 안 된다 — 기준선이 상대의 층수에 따라 6 m / 10 m 로 갈리므로 **더 먼 쌍이 더
    나쁠 수 있다**(1층 옆 8 m = 안전, 2층 옆 9 m = 위험). 그러면 1면의 종합 판정과 2면의
    표가 서로 다른 말을 한다.

    **필지 안과 밖을 따로 남긴다**(건물당 최대 두 쌍). 둘은 읽는 뜻이 다르다 — 같은 대지 안
    두 동은 제17조가 직접 말하는 구조이고, 옆 지번 건물은 조문 밖이지만 연소는 경계를 넘는다.
    한쪽만 내면 붙어 있는 옆 동에 가려 옆 지번과의 관계가 보고서에서 사라진다.
    """
    best = {}
    for f in sep.get("features") or []:
        p = f["properties"]
        if p.get("dir") in skip or p.get("dist_m") is None:
            continue
        who = (p.get("pair") or [None])[0] or p.get("bld_id")
        k = (who, p.get("same_parcel"))
        rank = (rules.LEVEL_ORDER.get(p.get("level"), 99), p["dist_m"])
        cur = best.get(k)
        if cur is None or rank < cur[0]:
            best[k] = (rank, f)
    return [f for _r, f in best.values()]


def sep_ext_ids(sep, blds, *, skip=()):
    """이격 표에 **상대로 실리는 외부 건물**의 bld_id — 그림에 번호를 붙일 대상이다.

    창 안 외부 건물 전부에 번호를 달면 표에 없는 번호가 지도에 남는다. 표의 행과 지도의
    번호가 1:1 이어야 「①이 어느 건물인지」를 되짚을 수 있다.
    """
    own = {f["properties"].get("bld_id") for f in (blds.get("features") or [])}
    out = set()
    for f in sep_pairs(sep, skip=skip):
        pr = f["properties"].get("pair") or []
        if len(pr) > 1 and pr[1] not in own:
            out.add(pr[1])
    return out


def win_box(site, *, pad_m=None):
    """`View` 가 잡는 crop 과 같은 범위의 경위도 사각형(필지 bbox + 여백).

    **번호는 지도에 보이는 건물에만 붙이려고** 쓴다. 이격 탐색 반경(60 m)이 창 여백보다
    넓어서, 거리 순으로만 번호를 매기면 창 밖 건물이 ⑤ 를 가져가 표에는 ⑤ 가 있는데 지도에는
    없는 일이 생긴다(실측 호산동 704-1: 25 m 북쪽 건물). 창은 nodata 를 더 잘라 낼 수 있으니
    이 사각형은 창보다 조금 넓다 — 넉넉한 쪽이 맞다(잘못 빼는 것보다 낫다).
    """
    from shapely.geometry import box, shape
    from shapely.ops import transform
    if not site.get("parcel"):
        return None
    fwd, inv = s3_separation._to_utm()
    b = transform(fwd.transform, shape(site["parcel"])).bounds
    p = win_pad(site, pad_m)
    return transform(inv.transform, box(b[0] - p, b[1] - p, b[2] + p, b[3] + p))


LABEL_INSET_M = 4.0               # 번호를 주려면 창 안으로 이만큼은 들어와 있어야 한다


def label_box(site, *, pad_m=None):
    """**번호를 줄 수 있는 범위** — 창(`win_box`)에서 배지 하나 높이만큼 안쪽.

    창에 **스치기만 해도** 번호를 주면 지도에 없는 것을 가리키는 번호가 생긴다 — 실측 호산동
    702-5 의 남동 상대(N0018)는 지붕의 0.7 % 만 창 모서리에 걸쳐 있는데 ⑤ 를 가져갔고,
    그 배지는 세 픽셀짜리 조각 위에 얹혀 무엇을 가리키는지 알 수 없었다. 번호는 「지도에서
    되짚을 수 있다」는 약속이므로, 되짚을 것이 없으면 주지 않는 편이 맞다.

    빠진 줄은 **표에서 사라지지 않는다** — 번호 칸이 「—」가 될 뿐이고 거리·방위·판정은
    그대로 실린다([[report/single._sep_ext_rows]]). 그림에서도 점선은 그대로 그린다.

    안쪽으로 무는 폭은 **종이에 앉는 배지 한 개의 높이**다 — 실측 셋에서 배지는 지면
    기준 3.4 · 4.6 · 5.5 m 였다(창 크기가 달라도 글자 크기를 창에 비례시키므로
    `label_size` 그만큼 고른다). 그보다 얕게 걸친 건물에는 배지를 앉힐 자리가 없다.
    """
    from shapely.ops import transform
    b = win_box(site, pad_m=pad_m)
    if b is None:
        return None
    fwd, inv = s3_separation._to_utm()
    g = transform(fwd.transform, b).buffer(-LABEL_INSET_M)
    return b if g.is_empty else transform(inv.transform, g)


def sep_arc_order(sep, *, skip=(), blds=None):
    """외부 건물 bld_id → **둘레 위 자리**(m). 번호를 매기는 순서의 정본이다.

    번호를 「필지 중심에서 본 방위각」으로 매기면 각주가 약속한 「북쪽부터 시계방향」이
    깨진다 — 상대 건물의 중심이 그 건물이 마주하는 경계선 자리와 다른 쪽에 있을 수 있기
    때문이다(실측 23곳 중 9곳에서 표 순서가 둘레 순서와 어긋났다). [[steps/s3_separation]]
    의 경계선 걷기가 `arc_m` 으로 그 자리를 이미 적어 두었으므로 그것을 쓴다.

    한 건물이 떨어진 두 구간을 이기면 **먼저 만나는 자리**로 매긴다 — 배지는 건물에 하나만
    놓이므로 그 건물이 처음 나타나는 자리가 번호의 뜻이 된다.

    **우리 동으로 묶지 않는다**(2026-08-26). 한때 A동을 도는 상대부터 ① 을 주어 동별 표가
    ① 부터 시작하게 했는데, 그러면 지도의 번호가 둘레를 도는 순서와 어긋난다 — 종이가
    약속한 말은 「부지 북쪽부터 시계방향」 하나이고, 표는 그 번호를 그대로 옮기는 자리다
    (표가 ①·⑤·⑥·⑦ 로 뛰는 것은 그 동이 부지의 그쪽을 맡고 있다는 뜻이라 읽을 수 있다).

    `blds` 는 받기만 하고 쓰지 않는다 — 옛 호출부를 깨지 않으려는 자리다.
    """
    out = {}
    for f in sep_pairs(sep, skip=skip):
        p = f["properties"]
        pr = p.get("pair") or []
        if len(pr) < 2 or p.get("same_parcel") or p.get("arc_m") is None:
            continue
        a = float(p["arc_m"])
        if pr[1] not in out or a < out[pr[1]]:
            out[pr[1]] = a
    return out


def ext_index(near, blds, *, only=None, window=None, site=None, order=None, force=()):
    """외부 건물 → [(번호, 폴리곤, bld_id)]. **필지 북쪽부터 시계방향**으로 ①②③.

    **도는 순서로 번호를 매긴다** — 지도의 ①②③ 이 북쪽에서 시계방향으로 놓이므로 표를 위에서
    아래로 읽으면 부지를 한 바퀴 도는 순서가 된다(가까운 순으로 매기면 지도에서 번호가 튄다).
    번호를 받는 것은 아래 둘을 다 만족하는 건물이다 — 번호와 표의 행이 1:1 이어야 「①이 어느
    건물인가」를 되짚을 수 있다.

        only    이격 표에 나오는 bld_id 집합 (없으면 전부)
        window  지도 창(`win_box`) — 창 밖 건물은 배지를 놓을 자리가 아예 없다
        force   **창 밖이어도 번호를 주는** bld_id 집합. 비교분석이 쓴다 —
                두 날짜가 같은 상대에 같은 번호를 달아야 두 그림을 나란히 볼 수 있는데,
                지붕 시차 1~2 m 만으로 한쪽에서만 배지 자리를 잃는 일이 생긴다(실측
                신당동 1187-2 N0028: 창 안으로 1차 4.01 m · 2차 5.11 m 들어와 배지 한 개
                높이를 사이에 두고 갈렸다). `only` 는 여전히 지켜진다 — 이격 표에 없는
                건물에는 번호를 주지 않는다
        order   bld_id → 둘레 위 자리(`sep_arc_order`). 주면 그 순서로 매긴다 — 이것이
                정본이고, 없을 때만 필지 중심에서 본 방위각으로 대신한다(옛 결과·폴리곤만
                받은 호출부)

    번호를 못 받은 것은 `None` 이고 그림에서 번호 없이 회색 점선으로만 그린다. `near` 는
    Feature 목록(bld_id 있음)이든 폴리곤 목록(bld_id 없음)이든 받는다 — bld_id 가 하나도
    없으면 `only` 를 무시한다(옛 호출부는 폴리곤만 넘긴다).
    """
    import math
    from shapely.geometry import shape
    from shapely.ops import unary_union
    own = [shape(f["geometry"]) for f in (blds.get("features") or [])]
    # 도는 중심 — 필지가 있으면 필지 가운데, 없으면 우리 건물 무리의 가운데.
    hub = None
    if site and site.get("parcel"):
        hub = shape(site["parcel"]).centroid
    elif own:
        hub = unary_union(own).centroid
    items = []
    for g in near or []:
        bid = az = d = None
        if isinstance(g, dict):
            pr = g.get("properties") or {}
            bid = pr.get("bld_id")
            # **순서의 근거는 값에 적혀 있다**(`label_features`). 여기서 다시 재면 그림과
            # 값이 갈릴 수 있다 — 없을 때만(옛 결과·폴리곤만 받은 호출부) 직접 잰다.
            az, d = pr.get("az_deg"), pr.get("dist_m")
            g = shape(g["geometry"] if "geometry" in g else g)
        if d is None:
            d = min((g.distance(o) for o in own), default=0.0)
        if az is None:
            c = g.centroid
            az = (math.degrees(math.atan2(c.x - hub.x, c.y - hub.y)) % 360.0) if hub else 0.0
        # 둘레 위 자리가 있으면 그것이 순서다. 없는 건물은 방위각을 둘레 길이보다 큰 수로
        # 밀어 뒤에 세운다 — 순서를 아는 것과 모르는 것을 섞으면 둘 다 못 믿는다.
        key = az if not order else order.get(bid, 1e9 + az)
        # **둘레 자리가 같으면 방위각으로 가른다.** 손으로 더한 줄(`also`)은 구간을 이기지
        # 못해 `arc_m` 이 「그 상대에게 가장 가까운 경계선 위 자리」인데, 모서리를 낀 상대
        # 셋이 같은 자리를 가리킬 수 있다 — 실측 호산동 702-5 에서 동·남동·남 셋이 arc
        # 54.1 로 묶여 거리 순으로 갈리는 바람에 ③남 · ④동 · ⑤남동 이 되어 각주가 약속한
        # 「북쪽부터 시계방향」이 그 세 줄에서만 깨졌다. 방위각으로 가르면 ③동 · ④남동 ·
        # ⑤남 으로 다시 시계방향이 된다(북을 걸치는 동률이면 갈리지 않지만, 그런 동률은
        # 필지 북쪽 모서리 하나를 셋이 마주해야 나온다).
        items.append((key, az, d, str(bid), g, bid))
    items.sort(key=lambda t: t[:4])
    named = only is None or not any(t[4] for t in items)
    out, n = [], 0
    for _k, _az, _d, _s, g, bid in items:
        ok = (named or bid in only) and (
            window is None or bid in force or g.intersects(window))
        if ok:
            out.append((_CIRCLED[n] if n < len(_CIRCLED) else f"({n + 1})", g, bid))
            n += 1
        else:
            out.append((None, g, bid))
    return out


def dong_order(dong):
    """동 이름 차례 — A동 · B동 … Z동 · AA동. 표를 놓는 순서이자 번호를 매기는 차례다.

    **글자로 정렬하지 않는다** — 「AA동」이 「A동」보다 앞에 온다(A < 동). 27동째부터 그렇게
    되므로 눈에 띄지 않다가 큰 물건에서만 어긋난다(실측 공단동 150, 33동).
    """
    return sorted(set(dong.values()), key=lambda n: (len(n), n))


def sep_key(p):
    """이격 줄 하나를 가리키는 **열쇠** — 지도와 표가 같은 줄을 같은 이름으로 부른다.

        필지 밖    (우리 동, 상대, 구간 번호) — 같은 상대라도 구간이 다르면 다른 줄이다
        필지 안    **양쪽을 묶은 것 하나** — A→B 와 B→A 는 같은 선을 양쪽에서 적은 것이라
                   두 표에 한 줄씩 서지만 **잰 것은 하나**다(사용자 결정, 2026-08-27)
        대지경계선  (「lot」, 그 동)
    """
    pr = list(p.get("pair") or []) + [None, None]
    if p.get("kind") == "lot_line":
        return ("lot", p.get("bld_id"))
    if p.get("same_parcel"):
        return ("own", frozenset((pr[0], pr[1])))
    return ("ext", pr[0], pr[1], p.get("run_id"))


def sep_ids(sep, dong, *, skip=(), hide=(), ext=None):
    """이격 줄 → **고유 번호**(「1」「2」…). 열쇠는 `sep_key`.

    **①②③ 과 다른 것이다.** ①②③ 은 **상대 건물**의 이름이고(`ext_names`) 이 번호는
    **측정선 하나**의 이름이다. 한 상대를 우리 동 둘이 마주 서거나 한 상대가 떨어진 두
    구간을 이기면 줄은 둘인데 상대는 하나다 — 그래서 이름이 둘 필요하다. 지도의 거리 배지가
    이 번호를 달고, 표의 「이격 번호」 칸이 같은 번호를 적는다.

    **차례는 종이가 읽히는 차례다** — 동 이름 순(A동 → B동), 그 동의 표 안에서는

        ① 필지 밖   둘레 자리(`arc_m`) 순, 자리가 같으면 상대 번호 순
        ② 대지경계선
        ③ 필지 안   상대 동 이름 순

    이라 표를 위에서 아래로 읽으면 번호가 1, 2, 3 … 으로 오른다. **딱 한 군데 거꾸로 보이는
    자리가 있다** — 필지 안 쌍은 두 표에 한 줄씩 서는데 번호는 하나이므로, 뒤에 서는 표에서는
    앞에서 준 번호가 그대로 나온다(B동 표의 마지막 줄이 7 8 6 처럼 보인다). 그것이 「이 줄은
    앞 표에서 이미 센 그 선이다」라는 뜻이고, 그러라고 하나로 묶었다.

    `hide` 는 종이에서 뺀 상대(`sep_hidden`) — 번호도 주지 않는다. `ext` 를 주면 둘레 자리가
    같을 때 그 번호 순으로 가른다(표의 정렬과 같은 잣대 — `report/single._sep_ext_rows`).
    """
    dn = dong
    rank = {b: i for i, b in enumerate(ext or {})}
    rows = {}
    for f in sep_pairs(sep, skip=skip):
        p = f["properties"]
        pr = p.get("pair") or []
        if p.get("kind") == "lot_line":
            rows.setdefault(p.get("bld_id"), []).append(((1, 0.0, 0), p))
            continue
        if len(pr) < 2:
            continue
        if p.get("same_parcel"):
            rows.setdefault(pr[0], []).append(((2, 0.0, dn.get(pr[1]) or ""), p))
        elif pr[1] not in hide:
            rows.setdefault(pr[0], []).append(
                ((0, p["arc_m"] if p.get("arc_m") is not None else 1e9,
                  rank.get(pr[1], 999)), p))
    seat = {n: i for i, n in enumerate(dong_order(dn))}
    ids, n = {}, 0
    for bid in sorted(rows, key=lambda b: (seat.get(dn.get(b), 999), str(b))):
        for _k, p in sorted(rows[bid], key=lambda t: (t[0][0], t[0][1], str(t[0][2]))):
            k = sep_key(p)
            if k in ids:                       # 필지 안 쌍의 반대쪽 — 번호는 하나다
                continue
            ids[k] = _CIRCLED[n] if n < len(_CIRCLED) else f"({n + 1})"
            n += 1
    return ids


def sep_hidden(sep, ext, *, skip=()):
    """**종이에서 뺄 상대 건물**의 bld_id — 번호를 못 받았고, 그 상대로 가는 줄이 전부 「안전」.

    번호가 없으면 지도에서 그 줄을 되짚을 수 없다. 그런 줄을 거리만 적어 실으면 종이가
    「번호도 없는 값」을 들고 있게 되므로, **번호도 못 붙일 만큼 창 밖인 상대는 재지 않은
    것으로 하고 종이에서 뺀다**(사용자 결정, 2026-08-27).

    **그런 상대는 늘 먼 상대다.** 번호를 못 받으려면 창(필지 bbox + `WIN_PAD_M`) 가장자리에
    배지 하나 높이도 못 들어와 있어야 하는데, 위험·주의는 10 m(양쪽 1층이면 6 m) 미만이라
    그 상대는 필지 바로 옆에 붙어 창 한복판에 들어온다. 실측 21곳 **필지 밖 164줄 중 번호
    없는 줄은 3줄**이었고 **셋 다 「안전」**이었다(호산동 702-5 남동 29.8 m).

    **그래도 판정이 갈리는 줄은 빼지 않는다.** 위험·주의인데 번호가 없다면 그것은 창이 잘못
    잡혔다는 신호이고, 그때 종이에서 지우면 위험이 조용히 사라진다 — 번호 없이 방위와
    거리로라도 싣는 편이 맞다(`_meas_text` 가 「남동 4.2 m」로 적는다). 창을 넓히는 손보정이
    따로 있다([[hand.py]] `win_pad`).

    **값 파일은 건드리지 않는다** — `separation.geojson` 에는 그 줄이 그대로 남는다. 빼는
    것은 종이뿐이고, 무엇을 빼는지는 각주에 적혀 있다.
    """
    keep, drop = set(), set()
    for f in sep_pairs(sep, skip=skip):
        p = f["properties"]
        pr = p.get("pair") or []
        if len(pr) < 2 or p.get("same_parcel") or ext.get(pr[1]):
            continue
        (drop if sep_level3(p.get("level")) == "안전" else keep).add(pr[1])
    return drop - keep


def ext_names(near, blds, *, only=None, window=None, site=None, order=None, force=()):
    """bld_id → 「①」. **번호는 건물마다 하나다** — 지도·표가 같이 쓰는 그 건물의 이름이다.

    `dong_names` 가 이 지번 건물에 「A동」을 주는 것과 같은 층위다. 그래서 지도의 배지는
    「⑤외부」 하나이고, 한 건물을 우리 동 둘이 마주 서면 **표에 줄이 둘 서되 번호는 같다**
    — 「A동 표의 ⑤ 17.3 m」와 「B동 표의 ⑤ 17.5 m」는 **같은 건물을 두 동에서 잰 값**이라는
    뜻이고, 표가 동마다 갈려 있으므로(`sep_dong_rows`) 그렇게 읽힌다.

    한때 번호를 **줄마다** 매겼다(2026-08-26). 그러면 한 건물이 번호를 둘 가져 지도의 이름
    배지가 「⑤⑥외부」가 되는데, ①②③ 은 **건물의 이름**이라 한 건물이 두 이름을 가질 수 없다
    — 지도만 보면 거기 건물이 둘 있는 것처럼 읽힌다(실측 호림동 3-10 남쪽 · 고잔동 672-6).
    """
    return {bid: n for n, _g, bid
            in ext_index(near, blds, only=only, window=window, site=site, order=order,
                         force=force)
            if bid and n}


# ── 글꼴·그리기 ─────────────────────────────────────────────────────────────
_FONTS = {}


def font(size, bold=False):
    from PIL import ImageFont
    k = (size, bold)
    if k in _FONTS:
        return _FONTS[k]
    cands = ["/usr/share/fonts/opentype/noto/NotoSansCJK-%s.ttc" % ("Bold" if bold else "Regular"),
             "/usr/share/fonts/truetype/nanum/NanumGothic%s.ttf" % ("Bold" if bold else ""),
             "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"]
    for c in cands:
        if Path(c).exists():
            try:
                _FONTS[k] = ImageFont.truetype(c, size)
                return _FONTS[k]
            except Exception:                                # noqa: BLE001
                pass
    _FONTS[k] = ImageFont.load_default()
    return _FONTS[k]


def plate(d, xy, text, fg, *, size=12, right=False, bottom=False, bold=False):
    """글자 밑에 반투명 판을 깐다 — 위성 위 글자는 판이 없으면 배경을 타서 읽히지 않는다."""
    f = font(size, bold)
    x, y = xy
    w = d.textlength(text, font=f)
    h = size + 5
    if right:
        x -= w
    if bottom:
        y -= h
    d.rectangle([x - 3, y - 2, x + w + 3, y + h - 2], fill=(0, 0, 0, 165))
    d.text((x, y), text, font=f, fill=tuple(fg) + (255,))


def _chip_box(d, text, size, bold, pad):
    f = font(size, bold)
    return d.textlength(text, font=f) + pad * 2, size + pad + 2


def chip(d, xy, text, *, bg=None, fg=None, size=12, bold=True, pad=6,
         right=False, bottom=False, alpha=225, radius=5):
    """설계서 BR-13 의 **배지** — 둥근 판 위의 짧은 글자.

    `bg` 를 주면 그 색 판에 어두운 글자(판정색 배지: 「A동 불일치」), 안 주면 어두운 판에
    `fg` 색 글자(거리 배지: 「남 7.4 m」)다. 판정색을 판으로 칠하면 눈에 먼저 들어오고,
    거리처럼 여러 개 늘어서는 값은 어두운 판이 지도를 덜 가린다.

    반환값은 차지한 사각형 — `spot_on` 이 겹침을 피하는 데 쓴다.
    """
    f = font(size, bold)
    w, h = _chip_box(d, text, size, bold, pad)
    x, y = xy
    if right:
        x -= w
    if bottom:
        y -= h
    if bg is not None:
        d.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=tuple(bg) + (alpha,))
        col = PLATE
    else:
        d.rounded_rectangle([x, y, x + w, y + h], radius=radius, fill=PLATE + (208,))
        col = fg or INK
    try:
        d.text((x + pad, y + h / 2), text, font=f, fill=tuple(col) + (255,), anchor="lm")
    except (ValueError, AttributeError):          # 기본 비트맵 글꼴은 anchor 를 못 받는다
        d.text((x + pad, y + (h - size) / 2 - 1), text, font=f, fill=tuple(col) + (255,))
    return (x, y, x + w, y + h)


def _free(rects, r):
    return all(not (r[0] < q[2] and q[0] < r[2] and r[1] < q[3] and q[1] < r[3])
               for q in rects)


# ── 이름표 자리 잡기 ────────────────────────────────────────────────────────
# **이름표는 자기 도형 위에 앉아야 한다.** 「A동」이 옆 지번 건물 위에 있으면 그 건물이
# A동이고, 「⑤외부」가 창 구석에 있으면 ⑤ 가 어느 건물인지 지도에서 되짚을 수 없다.
#
# 예전에는 자리를 도형 **bbox 의 왼쪽 위 모서리 위쪽**으로 잡았다(`label_xy`). 그 점은
# 도형 안이라는 보장이 없다 — 저장소의 결과 21곳 185개 이름표를 다시 재 보면 **자기 도형
# 안에 앵커가 떨어진 것이 8 %**(14/185)뿐이었고, **다섯 중 하나(20 %)는 아예 캔버스 밖**
# 이라 창 안으로 당겨지며 구석으로 날아갔다(앵커에서 창 안 도형까지 최대 1,000 px).
#
#     기울어진 창고    bbox 모서리가 지붕 밖 · 남의 땅 위 — 고잔동 672-6 야적물의 「A동」이
#                      필지 밖 옆 건물 위에 앉았고, 「⑤⑥외부」는 우리 A동 지붕 위에 앉았다
#     창에 걸친 건물   모서리가 캔버스 밖(호산동 702-5 ① 은 y = −824 px)이라 자리를 창
#                      안으로 당기면서 배지가 왼쪽 위 **구석**으로 날아갔다
#     겹칠 때          겹치면 **세로로만** 밀어 배지가 한 줄로 쌓였다 — 호산동의
#                      「④외부 / ②외부」가 오른쪽 위에 포개져 둘 다 남의 건물 위에 섰다
#
# 지금은 세 단계다. 셋 다 **창으로 자른 도형** 위에서 한다 — 창 밖은 놓을 자리가 아니다.
#
#     ① 앵커    도형 안에서 **경계에서 가장 먼 점**(`label_anchor`). 오목하든 기울었든
#               늘 도형 안이고, 창으로 자른 뒤에 잡으므로 늘 창 안이다.
#     ② 후보    앵커에 얹은 자리부터 **열두 방향**으로 배지 높이의 배수만큼 나가 본다.
#               세로 한 줄이 아니라 사방이라 붐비는 자리에서 배지가 쌓이지 않는다.
#     ③ 점수    **남의 도형을 덮으면 큰 벌점**(그 건물의 이름표로 읽힌다) · 자기 도형에서
#               벗어나면 작은 벌점 · 앵커에서 멀면 거리만큼. 가장 싼 자리에 놓고, 그래도
#               멀어졌으면 **지시선**을 그어 짝을 못 박는다(`place_meas` 와 같은 규약).
#
# 자리를 못 얻으면 **놓지 않는다** — 이 파일의 다른 배지와 같은 규칙이다. 같은 21곳을 이
# 규칙으로 다시 그리면 299개 이름표가 **전부** 자기 도형 위에 앉고(덮은 넓이 중앙값 100 %),
# 290개는 앵커에서 한 픽셀도 움직이지 않으며, 자리를 못 얻어 빠진 것은 없다.
LABEL_REACH = 3.4                 # 앵커에서 배지 높이의 몇 배까지 나가 보나
# 앵커에서 나가 보는 거리(배지 높이의 배수) — 얹을 자리부터 지시선을 그을 만큼 먼 자리까지.
# 작은 도형은 곁으로 비켜 서야 하므로(`W_HIDE`) 빈 자리를 찾을 만큼 촘촘하고 넉넉해야 한다.
LABEL_RINGS = (0.0, 0.85, 1.2, 1.5, 1.9, 2.2, 2.6, 3.0, 3.4)
LABEL_DIRS = tuple(range(0, 360, 30))
LABEL_LEAD = 1.5                  # 이보다 멀어지면 지시선을 긋는다(배지 높이의 배수)
# **남의 도형을 덮는 것이 가장 나쁘다** — 그 건물의 이름표로 읽히기 때문이다. 그래서 가림
# 벌점(`W_HIDE`)보다 크게 둔다(2026-08-27): 자기 도형을 다 가리는 자리(2.0)를 피하려고 남의
# 도형을 4분의 1 덮는 자리로 달아나면 안 된다 — 내 것이 안 보이는 것과 남의 것을 잘못
# 가리키는 것은 무게가 다르다.
W_OTHER = 8.0                     # 남의 도형을 덮은 넓이 벌점
W_OFF = 0.55                      # 자기 도형에서 벗어난 넓이 벌점
W_HIDE = 2.0                      # **자기 도형을 가린 넓이** 벌점 — 작은 도형은 비켜 세운다


def px_poly(v, geom, *, clip=None):
    """geometry → **패널 좌표 폴리곤**. `clip` 에 창 크기를 주면 창으로 자른다.

    자른 뒤 조각이 여럿이면 **가장 넓은 조각**만 쓴다 — 이름표는 하나뿐이고, 창에 조금
    걸친 꼬리가 아니라 눈에 보이는 몸통 위에 있어야 한다. 창에 안 걸치면 `None` 이다
    (그것이 「이 도형에는 이름표를 놓지 않는다」의 판정이다).
    """
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union
    ps = []
    for r in v.xy(geom):
        if len(r) < 3:
            continue
        q = Polygon(r)
        if not q.is_valid:
            q = q.buffer(0)
        if not q.is_empty and q.area > 0:
            ps.append(q)
    if not ps:
        return None
    g = ps[0] if len(ps) == 1 else unary_union(ps)
    if clip is not None:
        g = g.intersection(box(0, 0, clip[0], clip[1]))
    if g.is_empty:
        return None
    if g.geom_type != "Polygon":
        ps = [q for q in getattr(g, "geoms", []) if q.geom_type == "Polygon" and q.area > 0]
        if not ps:
            return None
        g = max(ps, key=lambda q: q.area)
    return g if g.area > 0 else None


def label_anchor(poly):
    """폴리곤 안의 **경계에서 가장 먼 점** — `(x, y)`. 도형이 없으면 `None`.

    중심(centroid)은 ㄷ 자 건물에서 마당 위로 나가고 bbox 모서리는 기울어진 창고에서 지붕
    밖으로 나간다. `polylabel` 은 어떤 모양이든 **안쪽** 점을 준다 — 그래서 이 점은 「이
    도형을 가리키는 한 점」으로도 쓸 수 있다(거리 배지를 상대 쪽으로 비켜 놓을 때).
    """
    from shapely.ops import polylabel
    if poly is None or poly.is_empty:
        return None
    try:
        p = polylabel(poly, tolerance=max(0.5, math.sqrt(poly.area) / 40.0))
    except Exception:                                    # noqa: BLE001 — 퇴화 도형
        p = poly.representative_point()
    return (p.x, p.y)


def _spot_cost(r, ax, ay, own, avoid, h):
    """자리의 값 — **작을수록 좋다.** 네 가지를 더한다.

        남의 도형을 덮은 비율 × 4.0      그 건물의 이름표로 읽힌다 — 가장 나쁜 실패다
        **자기 도형을 가린 비율** × 2.0  가려 버리면 이름은 있는데 가리킬 것이 없다
        자기 도형에서 벗어난 비율 × 0.55  지붕 위에 얹힐수록 좋다
        앵커에서 떨어진 거리 ÷ 배지 높이  가까울수록 좋다

    작은 건물은 배지가 지붕보다 넓어 어디에 놓아도 벗어난 비율이 크다 — 그래서 벗어남은
    **거리보다 싸게** 매긴다(0.55 < 0.85). 그러지 않으면 작은 이웃의 배지가 지붕을 떠나
    빈 아스팔트로 달아난다.

    **덮음과 벗어남은 다른 것이다**(2026-08-27). 벗어남은 「배지의 몇 %가 도형 밖인가」라
    큰 지붕에서만 작아지고, 덮음은 「도형의 몇 %가 배지 밑에 깔렸는가」다. 라벨보다 작은
    도형은 어디에 얹어도 100 % 가려진다 — 실측 구미 공단동 293-15 의 적재 구역(10.8 × 4.9 m ·
    화면 55 × 25 px)이 라벨 판(85 × 35 px) 밑에 통째로 사라져, 종이에 「Y0001」만 있고 그
    구역이 어디인지 보이지 않았다. 가림에 벌점을 매기면 그런 도형은 **곁으로 비켜 서고
    지시선이 붙는다**(`place_on`·`place_zone` 이 그때 선을 긋는다). 큰 지붕은 가리는 비율이
    몇 %라 벌점이 사실상 0 이므로 지금까지의 자리가 그대로 남는다.
    """
    from shapely.geometry import box
    b = box(*r)
    area = b.area or 1.0
    cost = math.hypot((r[0] + r[2]) / 2 - ax, (r[1] + r[3]) / 2 - ay) / h
    on = b.intersection(own).area
    cost += W_OFF * (1.0 - on / area)
    cost += W_HIDE * (on / max(own.area, 1e-9))
    for q in avoid:
        f = b.intersection(q).area / area
        if f > 0.02:
            cost += W_OTHER * f
    return cost


def spot_on(rects, poly, wh, *, bounds, avoid=(), reach=LABEL_REACH, anchor=None):
    """도형 위에 크기 `wh` 짜리 이름표를 놓을 자리 — `(x, y, ax, ay)` 또는 `None`.

    `rects` 는 이미 놓인 이름표들(겹치면 탈락) · `avoid` 는 **남의 도형**(덮으면 벌점) ·
    `bounds` 는 창 크기(밖으로 나가면 탈락)다. 자리를 못 찾으면 `None` 이고, 부른 쪽은
    그 이름표를 **놓지 않는다.**

    `anchor` 를 주면 **거기서부터** 자리를 찾는다(기본은 도형 안의 `label_anchor`). 적재
    구역처럼 **도형 위에 얹지 않기로 한 라벨**이 쓴다 — 그 라벨은 도형 바로 위가 제자리다.
    """
    a = anchor or label_anchor(poly)
    if a is None:
        return None
    ax, ay = a[0], a[1]
    w, h = wh
    W, H = bounds
    # 앵커 언저리에 없는 도형은 후보를 하나도 못 덮는다 — 미리 걸러 낸다(배지마다 남의
    # 도형 전부와 교차를 재면 큰 필지에서 그리기가 눈에 띄게 느려진다).
    span = reach * h + max(w, h)
    avoid = [q for q in avoid
             if q is not poly and not (q.bounds[2] < ax - span or q.bounds[0] > ax + span
                                       or q.bounds[3] < ay - span or q.bounds[1] > ay + span)]
    best = None
    for k in LABEL_RINGS:
        if k > reach:
            break
        rad = k * h
        for ang in (LABEL_DIRS if rad else (0,)):
            t = math.radians(ang)
            x = ax + math.sin(t) * rad - w / 2
            y = ay - math.cos(t) * rad - h / 2
            if x < 1 or y < 1 or x + w > W - 1 or y + h > H - 1:
                continue
            r = (x, y, x + w, y + h)
            if not _free(rects, r):
                continue
            c = _spot_cost(r, ax, ay, poly, avoid, h)
            if best is None or c < best[0]:
                best = (c, x, y)
    if best is None:
        return None
    return (best[1], best[2], ax, ay)


def place_on(d, rects, poly, text, *, bounds, avoid=(), size=12, lead=True,
             reach=LABEL_REACH, **kw):
    """도형 위에 **배지**를 놓는다(`spot_on` + `chip`). 놓은 사각형 또는 `None`.

    자리가 앵커에서 `LABEL_LEAD` 배지 높이보다 멀어지면 **지시선**을 긋는다 — 안 그으면
    옮긴 배지가 어느 도형의 것인지 알 수 없는 떠 있는 글자가 된다.
    """
    w, h = _chip_box(d, text, size, kw.get("bold", True), kw.get("pad", 6))
    s = spot_on(rects, poly, (w, h), bounds=bounds, avoid=avoid, reach=reach)
    if s is None:
        return None
    x, y, ax, ay = s
    if lead and math.hypot(x + w / 2 - ax, y + h / 2 - ay) > LABEL_LEAD * h:
        _stroke(d, [(min(max(ax, x), x + w), min(max(ay, y), y + h)), (ax, ay)],
                kw.get("bg") or kw.get("fg") or INK, w=1, alpha=200)
    chip(d, (x, y), text, size=size, **kw)
    rects.append((x, y, x + w, y + h))
    return (x, y, x + w, y + h)


ZONE_GAP = 5                      # 적재 구역 라벨과 상자 사이 틈(px)


def place_zone(d, rects, poly, text, col, *, bounds, avoid=(), size=12,
               reach=LABEL_REACH):
    """적재 구역 라벨(`plate`) — **상자 위, 상자 밖**에 놓는다(사용자 결정, 2026-08-27).

    건물 이름표는 지붕 한가운데가 제자리지만(`place_on`) 적재 구역은 다르다 — 상자가 라벨과
    비슷한 크기라 얹으면 **상자가 라벨 밑으로 사라지고**, 이 면에서 읽을 것은 「무엇이
    어디에 얼마나 쌓였나」라 상자 자체가 정보다. 그래서 앵커를 도형 안이 아니라 **상자 위쪽
    변에서 한 틈 떨어진 자리**로 잡는다. 그 뒤는 `place_on` 과 같다 — 붐비면 사방으로 비켜
    서고, 멀어지면 지시선을 긋는다.
    """
    f = font(size)
    w, h = d.textlength(text, font=f) + 6, size + 7
    b = poly.bounds                                  # (minx, miny, maxx, maxy) — miny 가 위
    anchor = ((b[0] + b[2]) / 2, b[1] - ZONE_GAP - h / 2)
    s = spot_on(rects, poly, (w, h), bounds=bounds, avoid=avoid, reach=reach,
                anchor=anchor)
    if s is None:
        return None
    x, y, ax, ay = s
    if math.hypot(x + w / 2 - ax, y + h / 2 - ay) > LABEL_LEAD * h:
        _stroke(d, [(min(max(ax, x), x + w), min(max(ay, y), y + h)), (ax, ay)],
                col, w=1, alpha=200)
    plate(d, (x + 3, y + 2), text, col, size=size)
    rects.append((x, y, x + w, y + h))
    return (x, y, x + w, y + h)

def place_meas(d, rects, a, b, text, *, toward=None, size=12, bounds=None,
               nudges=1, **kw):
    """**측정선 배지 — 자기 선의 것으로 읽히는 자리에만 놓는다.**

    예전에는 선 가운데의 **오른쪽 한 자리**만 잡고, 겹치면 배지가 세로로만 20 px 씩
    밀었다. 짧은 측정선이 붐비는 모서리에 있으면 그 배지가 수십 px 밖까지 밀려 **다른 건물의
    배지 옆에 붙는다** — 실측 호림동 3-10 의 남동 모서리: ③(남동 건물)과 ④(남 건물)의 측정선
    두 개가 6 px 안에 겹쳐 서는데, ④의 3.2 m 가 ③외부 배지 바로 위로 밀려 세로로
    「3.2 m / ③외부 / 1.8 m」가 되어 3.2 m 가 ③의 거리로 읽혔다.

    두 단계로 놓는다.

        ① **선 곁 네 방향** — 선을 비켜선 쪽부터(세로선은 좌우, 가로선은 위아래가 선을
           가리지 않는다). ±`MEAS_NUDGE` 까지만 민다. 여기 들어가면 배지가 선에 붙어 있어
           지시선이 필요 없다.
        ② `toward`(**그 거리를 잰 상대 건물** 쪽)로 더 나가 본다. 상대 쪽으로 비켜 놓으면
           「이 값은 저 건물까지의 거리」가 방향으로 읽히고, 남의 배지 옆에 붙을 일도 없다.
           멀어진 만큼 **지시선을 그어** 어느 선의 값인지 못 박는다 — 안 그으면 옮긴 배지가
           떠 있는 숫자가 된다.

    그래도 자리가 없으면 배지를 뺀다. 거리는 표에 방위와 함께 다시 적히므로 잃는 것이 적고,
    이 파일의 다른 배지와 같은 규칙이다(「자리를 못 얻어 빠지는 것은 거리 쪽이어야 한다」).

    `nudges` — ①에서 밀어 볼 칸 수(±`MEAS_NUDGE` × 1…n). 기본은 한 칸이다. **배지가 스스로
    번호를 달고 있으면 더 밀어도 된다** — 위 실패는 「3.2 m」가 남의 배지 옆에 붙어 **어느
    줄의 값인지 알 수 없다**는 것이었고, 「④ 3.2 m」라 적혀 있으면 멀어져도 짝이 읽힌다.
    한 칸으로 묶어 두면 **우리 건물의 한 꼭짓점에서 여러 상대로 선이 뻗는 자리에서 배지가
    아예 사라진다** — 실측 고잔동 672-6: ①②③ 이 A동 동쪽 꼭짓점 한 점에서 나가고 세 선의
    중점이 20 px 안에 모여, 여덟 중 둘(②③)이 자리를 못 얻어 빠졌다(지시선 fallback 으로도
    못 살렸다 — 세 상대가 다 동쪽이라 `toward` 방향까지 겹친다).
    """
    w, h = _chip_box(d, text, size, kw.get("bold", True), kw.get("pad", 6))
    mx, my = mid(a, b)
    gap = 6
    right = (mx + gap, my - h / 2)
    left = (mx - gap - w, my - h / 2)
    above = (mx - w / 2, my - gap - h)
    below = (mx - w / 2, my + gap)
    # **네 방향의 순서를 상대가 있는 쪽으로 정한다.** 「이 값은 저 건물까지의 거리」가
    # 자리만으로 읽히게 하는 것이 요령이다 — 실측 호림동 3-10 남동 모서리에서 ③(남동)과
    # ④(남)의 측정선이 6 px 안에 겹쳐 서는데, 상대 쪽으로 갈라 놓으면 ③은 남동, ④는 남서로
    # 나뉘어 어느 값이 어느 건물의 것인지 헷갈리지 않는다. 상대를 모르면(옛 결과) 선을
    # 비켜선 쪽부터 본다 — 세로선은 좌우, 가로선은 위아래가 선을 가리지 않는다.
    vert = abs(b[1] - a[1]) >= abs(b[0] - a[0])
    sides = [right, left, above, below] if vert else [above, below, right, left]
    if toward is not None:
        tx, ty = toward[0] - mx, toward[1] - my
        tn = math.hypot(tx, ty)
        if tn > 1e-6:
            tx, ty = tx / tn, ty / tn
            def aim(xy):
                vx, vy = xy[0] + w / 2 - mx, xy[1] + h / 2 - my
                vn = math.hypot(vx, vy) or 1.0
                return -(vx / vn * tx + vy / vn * ty)      # 상대 쪽에 가까운 순
            sides = sorted(sides, key=aim)

    def put(x, y, lead=False):
        """자리가 비었으면 놓고 True. `lead` 면 지시선을 먼저 긋는다(배지가 끝을 덮는다)."""
        if bounds:
            W, H = bounds
            x = min(max(x, 2), max(2, W - w - 2))
            y = min(max(y, 2), max(2, H - h - 2))
            if not (0 <= y and y + h <= H):
                return False
        if not _free(rects, (x, y, x + w, y + h)):
            return False
        if lead:
            _stroke(d, [(min(max(mx, x), x + w), min(max(my, y), y + h)), (mx, my)],
                    kw.get("fg") or MEAS, w=1, alpha=255)
        chip(d, (x, y), text, size=size, **kw)
        rects.append((x, y, x + w, y + h))
        return True

    steps = [0]
    for i in range(1, max(1, int(nudges)) + 1):
        steps += [i * MEAS_NUDGE, -i * MEAS_NUDGE]
    for nudge in steps:
        for x, y in sides:
            if put(x, y + nudge):
                return True
    # ② 상대 쪽으로 — 방향은 상대 건물, 거리는 배지가 확실히 떨어질 만큼부터 키운다.
    if toward is not None:
        ux, uy = toward[0] - mx, toward[1] - my
        n = math.hypot(ux, uy)
        if n > 1e-6:
            ux, uy = ux / n, uy / n
            for step in (2.2, 3.4, 4.6, 6.0):
                r = step * MEAS_NUDGE
                if put(mx + ux * r - w / 2, my + uy * r - h / 2, lead=True):
                    return True
    return False


MEAS_NUDGE = 12          # 측정선 배지를 밀어 보는 폭 — 이보다 멀면 자기 선의 것으로 안 읽힌다

HALO = (0, 0, 0, 115)     # 선 밑에 까는 어두운 테. 밝은 지붕 위에서는 1 px 선이 사라진다


def _stroke(d, pts, col, *, w=1, alpha=235, halo=True):
    """1 px 선 + 어두운 테. **굵게 하는 대신 테를 깐다** — 굵은 선은 잰 자리를 가린다.

    실측: 노란 필지선 1 px 를 밝은 크림색 지붕 위에 그으면 흰 선처럼 보여 필지인지
    아닌지 구분되지 않았다.
    """
    if len(pts) < 2:
        return
    if halo:
        d.line(pts, fill=HALO, width=w + 2)
    d.line(pts, fill=tuple(col) + (alpha,), width=w)


def ring(d, pts, col, *, w=1, fill=0, close=True, alpha=235, halo=True):
    if len(pts) < 2:
        return
    if fill:
        d.polygon(list(pts), fill=tuple(col) + (fill,))
    _stroke(d, list(pts) + ([pts[0]] if close else []), col, w=w, alpha=alpha, halo=halo)


def dash(d, pts, col, *, w=1, on=7, off=6, alpha=230, close=False, halo=True):
    p = list(pts) + ([pts[0]] if close and len(pts) > 2 else [])
    segs = []
    for (x0, y0), (x1, y1) in zip(p, p[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        if seg < 1e-6:
            continue
        t = 0.0
        while t < seg:
            a, b = t, min(seg, t + on)
            segs.append([(x0 + (x1 - x0) * a / seg, y0 + (y1 - y0) * a / seg),
                         (x0 + (x1 - x0) * b / seg, y0 + (y1 - y0) * b / seg)])
            t += on + off
    for q in segs:
        _stroke(d, q, col, w=w, alpha=alpha, halo=halo)


def measure(d, p0, p1, col, *, w=1, cap=5, dashed=False):
    """측정선 — 양 끝에 수직 캡을 달아 '어디서 어디까지 잰 것'을 분명히 한다.

    선의 길이가 곧 거리값이므로 도형과 숫자가 어긋날 수 없다.

    `dashed` 는 설계서 BR-13 목업을 따른 것이다 — 안전은 실선, 주의·위험은 점선으로 그어
    색을 못 읽는 인쇄물에서도 눈에 걸리는 선이 어느 것인지 구분된다.
    """
    (x0, y0), (x1, y1) = p0, p1
    if math.hypot(x1 - x0, y1 - y0) < 1.5:               # 붙어 있음(0 m)
        d.ellipse([x0 - 4, y0 - 4, x0 + 4, y0 + 4], outline=HALO, width=w + 2)
        d.ellipse([x0 - 4, y0 - 4, x0 + 4, y0 + 4], outline=tuple(col) + (255,), width=w)
        return
    if dashed:
        dash(d, [p0, p1], col, w=w, on=6, off=5, alpha=255)
    else:
        _stroke(d, [p0, p1], col, w=w, alpha=255)
    a = math.atan2(y1 - y0, x1 - x0) + math.pi / 2
    dx, dy = math.cos(a) * cap, math.sin(a) * cap
    for x, y in (p0, p1):
        _stroke(d, [(x - dx, y - dy), (x + dx, y + dy)], col, w=w, alpha=255)


def mid(p0, p1):
    return ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)


def stroke_w(v, *, ref=1000.0, base=2.0):
    """선 굵기 — 창 픽셀에 비례. 2 px 로 고정하면 1,500 px 캔버스에서 실오라기가 된다."""
    return max(1, round(base * max(v.base.size) / ref))


def label_size(v, *, ref=1000.0, base=28):
    """배지·라벨 글자 크기 — **창의 픽셀 크기에 비례**해 정한다.

    패널은 필지 크기에 따라 500~1200 px 로 달라지는데(`View.k` 의 확대 한도 때문이다) 종이에
    앉는 폭은 한 값이다. 그래서 px 로 고정하면 큰 필지에서 글자가 절반으로 줄어 읽히지 않는다
    — 실측 호산동 707-2(1,200 px 패널)에서 17 px 배지가 인쇄물에서 5 pt 였다.
    """
    return max(12, round(base * max(v.base.size) / ref))


# ── 창 ──────────────────────────────────────────────────────────────────────
_PNG = {"key": None, "img": None}
STRETCH_PCT = (1.0, 99.0)        # crop 안에서 다시 늘일 때 자르는 양쪽 꼬리

# ── 밝기 ────────────────────────────────────────────────────────────────────
# 꼬리를 자르는 늘이기(`_stretch`)는 **양끝**을 맞추므로 가운데가 어디에 앉을지는 정하지
# 않는다. 우리 장면은 공장 지붕(밝음)과 아스팔트·그림자(어두움)가 섞여 히스토그램이 아래로
# 몰려 있어서, 양끝을 맞춰도 중간값이 43~87 로 물건마다 흩어진다(실측 데모 17건). 그래서
# 어떤 물건은 지붕 골이 안 보이고, 두 물건을 나란히 놓으면 밝기가 달라 같은 재질도 다르게
# 읽힌다 — 비교분석 보고서는 두 날짜를 한 면에 붙이므로 특히 그렇다.
#
# **중간값을 목표에 앉히는 감마**로 맞춘다. 감마는 0 과 255 를 그대로 두고 가운데만 올리므로
# 늘이기가 잡아 둔 양끝(nodata 검정 · 밝은 지붕)이 흐트러지지 않는다. 밝기를 더하거나 대비를
# 곱하는 방식은 밝은 지붕을 흰색으로 밀어 지붕 무늬를 지운다.
TONE_MED = 105.0                 # 목표 중간값(8bit) — 인쇄해도 지붕 골이 남는 자리
TONE_MAX = 2.2                   # 감마 상한 — 이보다 세게 올리면 그림자에 잡음이 뜬다
TONE_LUMA = (0.299, 0.587, 0.114)


def _scene_png(scene_dir):
    """장면 PNG — **원본 tif 를 못 읽을 때의 대비책.** 한 장만 메모리에 둔다(구미 450 MB).

    이 PNG 는 장면 전체를 한 벌의 눈금으로 8bit 로 눌러 둔 것이라 필지 하나만 떼면 흐리다
    (아래 `_scene_raw` 참고). 모델·VLM 입력은 이 PNG 를 그대로 쓰지만(그 위에서 값을 냈다),
    **사람이 보는 그림은 원본에서 뜬다.**
    """
    key = str(scene_dir)
    if _PNG["key"] != key:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        _PNG.update(key=key, img=Image.open(Path(scene_dir) / "scene.png").convert("RGB"))
    return _PNG["img"]


def _scene_raw(scene_dir, win):
    """원본 tif 에서 **창만** 읽는다 → (3,h,w) uint16. 못 읽으면 None.

    `scene.png` 는 1만 픽셀 장면 전체의 2–98 % 를 한 벌의 눈금으로 8bit 에 눌러 놓은 것이다.
    그래서 필지 하나만 떼어 보면 그 창의 화소값이 눈금의 좁은 구간에만 몰려 대비가 죽는다 —
    실측 호산동 704-1 창의 원본값은 126~486 인데 16bit 전 구간을 기준으로 눌린 값이라
    지붕 골·차량·나무결이 다 뭉갰다. 원본은 무손실(LZW·uint16)이므로 **창만 읽어 그 창의
    분포로 다시 늘이면** 같은 화소에서 훨씬 또렷한 그림이 나온다.

    덤이 둘이다 — 450 MB PNG 를 통째로 디코드하지 않아 빠르고(보고서 한 건 1~2분 → 수 초),
    8bit 를 두 번 거치지 않아 계조가 남는다.

    밴드 순서는 `meta.json` 의 `rgb_from_bands` 다(SSC pansharpened 는 B,G,R,NIR 라 3,2,1).
    """
    d = Path(scene_dir)
    tifs = sorted(d.glob("*.tif"))
    if not tifs:
        return None
    try:
        import json as _json
        import rasterio
        from rasterio.windows import Window
        bands = [3, 2, 1]
        m = d / "meta.json"
        if m.exists():
            bands = (_json.loads(m.read_text("utf-8")).get("rgb_from_bands") or bands)
        x0, y0, x1, y1 = win
        # tif 를 반복해 열면 간헐적으로 TIFFReadDirectory 오류가 난다(`georef.raw_xform` 과 같은
        # 증상) — 몇 번 다시 해 본다.
        for _ in range(3):
            try:
                with rasterio.open(tifs[0]) as ds:
                    return ds.read(bands, window=Window(x0, y0, x1 - x0, y1 - y0))
            except Exception:                            # noqa: BLE001
                continue
    except Exception:                                    # noqa: BLE001
        return None
    return None


def _tone(rgb, valid, *, med=TONE_MED, gmax=TONE_MAX):
    """8bit RGB 를 **중간값이 `med` 에 앉도록** 감마로 올린다 → (arr, 쓴 감마).

    감마 하나를 세 채널에 똑같이 물린다 — 채널마다 따로 맞추면 색이 돌아간다(늘이기가 이미
    채널별 양끝을 맞춰 백색을 잡아 두었으므로 여기서 또 만지면 그 백색을 버린다).

    **어둡게는 하지 않는다**(감마 ≥ 1). 목표보다 밝게 나온 물건을 눌러 맞추면 밝은 쪽이
    이미 잘 보이는 그림을 일부러 흐리게 만드는 셈이다 — 목표는 「아래를 끌어올려 고르게」다.

    유효 화소가 없거나 중간값이 0/255 에 붙어 감마를 낼 수 없으면 손대지 않는다.
    """
    if not valid.any():
        return rgb, 1.0
    lum = rgb.astype(np.float32) @ np.asarray(TONE_LUMA, np.float32)
    m = float(np.median(lum[valid]))
    if not (1.0 <= m <= 254.0) or m >= med:
        return rgb, 1.0
    # med = 255·(m/255)^(1/g) 를 g 로 푼다. m < med 이므로 g > 1 이다.
    g = float(np.log(m / 255.0) / np.log(med / 255.0))
    g = min(max(g, 1.0), gmax)
    if g <= 1.0 + 1e-6:
        return rgb, 1.0
    lut = np.clip((np.arange(256, dtype=np.float32) / 255.0) ** (1.0 / g) * 255.0,
                  0, 255).astype(np.uint8)
    out = lut[rgb]
    out[~valid] = 0                     # 감마는 0 을 0 으로 두지만 명시해 둔다
    return out, g


def _stretch(raw, valid, pct=STRETCH_PCT):
    """(3,h,w) uint16 + 유효 마스크 → PIL RGB. **nodata 는 검정으로 남긴다** — 창을 다듬는
    코드도 야적 판독도 검정으로 걸러 낸다.

    양끝을 맞춘 뒤 `_tone` 이 **가운데를 목표에 앉힌다** — 물건마다 다른 밝기로 나오면 같은
    재질이 다르게 읽힌다.
    """
    from PIL import Image
    out = np.zeros(raw.shape[1:] + (3,), np.uint8)
    for c in range(3):
        v = raw[c][valid]
        lo, hi = (np.percentile(v, pct) if v.size else (0.0, 1.0))
        hi = hi + (hi <= lo)
        out[..., c] = np.clip((raw[c].astype(np.float32) - lo) / (hi - lo) * 255.0,
                              0, 255).astype(np.uint8)
    out[~valid] = 0
    out, _g = _tone(out, valid)
    return Image.fromarray(out, "RGB")


class View:
    """필지 주변 crop 하나. 세 항목이 같은 창을 써서 나란히 놓고 비교할 수 있다."""

    def __init__(self, site, *, pad_m=None, target_px=PANEL_PX, max_up=MAX_UP):
        from PIL import Image
        from shapely.geometry import shape
        self.ok = False
        sc = site.get("scene")
        if not sc or not site.get("parcel"):
            return
        self.dir = config.SCENES[sc["key"]]["dir"].resolve()
        # 보정된 지오트랜스폼 — 지도 좌표로 담긴 기하를 영상 픽셀에 얹는다([[steps/georef.py]]).
        from sitecheck.steps import georef
        self.T, self.crs, W, H = georef.xform(site)
        self.res_m = float(sc.get("res_m") or 0.5)
        par = s2_yard._lonlat_to_px(self.T, self.crs, shape(site["parcel"]))
        pad = win_pad(site, pad_m) / self.res_m
        x0, y0, x1, y1 = par.bounds
        x0 = max(0, int(x0 - pad)); y0 = max(0, int(y0 - pad))
        x1 = min(W, int(x1 + pad) + 1); y1 = min(H, int(y1 + pad) + 1)
        if x1 - x0 < 16 or y1 - y0 < 16:
            return
        # **원본 tif 에서 창만 뜬다**(`_scene_raw`) — scene.png 는 장면 전체를 한 벌의 눈금
        # 으로 눌러 둔 것이라 필지 하나만 떼면 흐리다. 못 읽으면 PNG 로 물러선다.
        raw, png, crop = _scene_raw(self.dir, (x0, y0, x1, y1)), None, None
        if raw is not None:
            va = raw.sum(0) > 0
        else:
            png = _scene_png(self.dir)
            crop = png.crop((x0, y0, x1, y1))
            va = np.asarray(crop.convert("L")) > 6
        # **검은 nodata 는 창에 넣지 않는다** — 절반이 까맣게 나오면 무엇을 보는 그림인지
        # 알 수 없다. 값(JSON)은 건드리지 않는다.
        if va.any():
            rr = np.where(va.any(axis=1))[0]
            cc = np.where(va.any(axis=0))[0]
            ny0, ny1 = y0 + int(rr[0]), y0 + int(rr[-1]) + 1
            nx0, nx1 = x0 + int(cc[0]), x0 + int(cc[-1]) + 1
            if (nx1 - nx0) >= 16 and (ny1 - ny0) >= 16 and (nx1 - nx0, ny1 - ny0) != (x1 - x0, y1 - y0):
                if raw is not None:
                    # 늘이기 전에 자른다 — nodata 를 끼고 늘이면 눈금이 검정 쪽으로 끌린다.
                    raw = raw[:, int(rr[0]):int(rr[-1]) + 1, int(cc[0]):int(cc[-1]) + 1]
                    va = raw.sum(0) > 0
                x0, y0, x1, y1 = nx0, ny0, nx1, ny1
                if raw is None:
                    crop = png.crop((x0, y0, x1, y1))
        if raw is not None:
            crop = _stretch(raw, va)
        else:
            # PNG 로 물러선 길도 **같은 밝기**로 맞춘다 — 원본을 못 읽은 물건만 어둡게
            # 나오면 그 차이를 영상 차이로 읽는다. 유효 마스크는 crop 에서 다시 낸다 —
            # 위의 `va` 는 다듬기 전 창의 것이라 모양이 다를 수 있다.
            a = np.asarray(crop.convert("RGB"), np.uint8)
            a, _g = _tone(a, np.asarray(crop.convert("L")) > 6)
            crop = Image.fromarray(a, "RGB")
        self.win = (x0, y0, x1, y1)
        w, h = x1 - x0, y1 - y0
        # 소형 필지(40×40 m = 80 px)를 목표 폭까지 늘리면 5~8배가 되어 지붕 무늬가 죽는다.
        # 그림이 작아지는 것보다 뭉개지는 것이 나쁘다 — 정합을 눈으로 봐야 하기 때문이다.
        self.k = min(float(target_px) / max(w, h), max_up)
        self.base = crop.resize((max(1, round(w * self.k)), max(1, round(h * self.k))),
                                Image.LANCZOS)
        self.ok = True

    # 좌표
    def pt(self, px, py):
        return ((px - self.win[0]) * self.k, (py - self.win[1]) * self.k)

    def xy(self, geom):
        """경위도 geometry → 패널 좌표 목록(Polygon 은 외곽선, LineString 은 그대로)."""
        if hasattr(geom, "__geo_interface__") is False and isinstance(geom, dict):
            from shapely.geometry import shape
            geom = shape(geom)
        g = s2_yard._lonlat_to_px(self.T, self.crs, geom)
        out = []
        for q in (g.geoms if g.geom_type.startswith("Multi") else [g]):
            if q.is_empty:
                continue
            if q.geom_type == "Polygon":
                co = list(q.exterior.coords)
            elif q.geom_type in ("LineString", "LinearRing"):
                co = list(q.coords)
            elif q.geom_type == "Point":
                co = [(q.x, q.y)]
            else:
                continue
            out.append([self.pt(px, py) for px, py in co])
        return out

    def one(self, geom):
        """가장 큰 조각 하나의 좌표 — 라벨 위치를 잡을 때 쓴다."""
        rs = self.xy(geom)
        return max(rs, key=len) if rs else []

    # 패널 — **한 장.** 제목은 시트가 이미 달고 있으므로 그림에는 각주 한 줄만 붙인다.
    def panel(self, draw_fn, foot=None):
        from PIL import Image, ImageDraw
        ov = Image.new("RGBA", self.base.size, (0, 0, 0, 0))
        draw_fn(ImageDraw.Draw(ov), self)
        img = Image.alpha_composite(self.base.convert("RGBA"), ov).convert("RGB")
        if not foot:
            return img
        full = Image.new("RGB", (img.width, img.height + 22), BG)
        d = ImageDraw.Draw(full)
        full.paste(img, (0, 0))
        d.text((6, img.height + 4), _fit(d, foot, font(12), img.width - 12),
               font=font(12), fill=DIM)
        return full


def _fit(d, text, f, maxpx):
    if d.textlength(text, font=f) <= maxpx:
        return text
    while text and d.textlength(text + "…", font=f) > maxpx:
        text = text[:-1]
    return text + "…"


# ── 공통 그리기 조각 ────────────────────────────────────────────────────────
def _parcel(d, v, site, *, w=1, alpha=235):
    for r in v.xy(site["parcel"]):
        ring(d, r, PARCEL, w=w, alpha=alpha)


def _zone_px_area(v):
    """패널에서 차지하는 크기 — 라벨을 어느 것부터 놓을지 정하는 순서다."""
    def key(f):
        r = v.one(f["geometry"])
        if not r:
            return 0.0
        xs = [p[0] for p in r]
        ys = [p[1] for p in r]
        return (max(xs) - min(xs)) * (max(ys) - min(ys))
    return key


def _buffer_ll(polys, dist_m, *, clip=None, clip_m=12.0):
    """경위도 폴리곤을 미터로 부풀린다 — 법정선을 그림에 얹기 위해서만 쓴다.

    `clip` 을 주면 그 도형 주변으로 잘라 낸다. 창 안 건물 전부에 6 m 띠를 두르면 빨간 파선이
    화면을 덮어 정작 판정선이 어디인지 안 보인다 — 야적물이 있는 **이 필지 주변만** 보인다.
    """
    if not polys:
        return []
    from shapely.ops import transform, unary_union
    fwd, inv = s3_separation._to_utm()
    u = unary_union([transform(fwd.transform, p) for p in polys]).buffer(dist_m)
    if clip is not None:
        u = u.intersection(transform(fwd.transform, clip).buffer(clip_m))
    if u.is_empty:
        return []
    u = transform(inv.transform, u)
    return list(u.geoms) if u.geom_type.startswith("Multi") else [u]


def _nearest_line(zone, blds):
    """적재 구역 → 가장 가까운 건물까지의 최근접선(경위도). 없으면 None."""
    from shapely.geometry import LineString
    from shapely.ops import nearest_points, transform
    if not blds:
        return None
    fwd, inv = s3_separation._to_utm()
    z = transform(fwd.transform, zone)
    best = None
    for b in blds:
        g = transform(fwd.transform, b)
        d = z.distance(g)
        if best is None or d < best[0]:
            best = (d, g)
    pa, pb = nearest_points(z, best[1])
    return transform(inv.transform, LineString([pa, pb]) if best[0] > 0 else LineString([pa, pa]))



def _geoms(near):
    """주변 건물 — shapely 목록이든 GeoJSON Feature 목록이든 같이 받는다.

    GT 경로는 Feature 로, 모델 경로는 shapely 로 들고 있다. 호출부마다 변환을 쓰면
    한쪽을 고칠 때 다른 쪽이 조용히 빈 목록이 된다.
    """
    from shapely.geometry import shape
    out = []
    for g in near or []:
        if isinstance(g, dict):
            g = shape(g["geometry"] if "geometry" in g else g)
        out.append(g)
    return out


# ── 항목별 레이어 ───────────────────────────────────────────────────────────
def _meas_text(p, res_m, no=None):
    """거리 배지 글자 — **이격 번호 + 거리**(「1  2.8 m」).

    번호는 **그 측정선 하나**의 것이다(`sep_ids`) — 상대 건물의 이름(①②③)이 아니다. 그래서
    지도에 같은 숫자가 두 번 뜨지 않고, 표의 「이격 번호」 칸과 1:1 이다. 어느 상대까지의
    거리인지는 선이 닿는 곳의 회색 배지(「①외부」)가 말하고, 표는 두 번호를 한 줄에 나란히
    적는다.

    번호를 못 받은 줄에는 방위를 적는다(「남동 29.8 m」) — 창 밖 상대라 종이에서 뺀 줄이
    아니면서 번호도 없는 경우다(`sep_hidden` 이 안전한 줄만 빼므로 여기 오는 것은 위험·주의
    뿐이고, 그때는 지우기보다 방위로라도 싣는 편이 맞다).

    필지 **안** 우리 동끼리의 줄에도 번호가 붙는다 — 두 표에 한 줄씩 서지만 잰 것은 하나라
    번호도 하나다. 방위는 안 적는다(보는 쪽에 따라 뒤집힌다 — A 의 남 = B 의 북).
    """
    d = dist_text(p.get("dist_m"), res_m=res_m)
    if no:
        # 번호는 **글머리 숫자**(①)이고 색은 **그 줄의 판정색** — 곁의 거리 숫자와 같은 색이다
        # (사용자 결정, 2026-08-27). 한 배지 안에서 색이 갈리면 번호와 거리가 다른 것을
        # 말하는 것처럼 읽힌다. 글머리 숫자라 갈라 놓을 점도 필요 없다(「1 10.1 m」는
        # 「110.1 m」로 읽혔지만 「① 10.1 m」는 안 그렇다).
        return f"{no} {d}"
    if not p.get("same_parcel"):
        w = p.get("dir8") or p.get("dir")
        if w:
            return f"{w} {d}"
    return d


def sep_draw(site, blds, near, sep, *, skip=(), size=None, force=()):
    """이격거리 — **설계서 BR-13 방식**.

        이 지번 건물   실선(시안) + 「A동」 배지
        외부 건물      **회색 점선** + 「①외부」 배지 — **한 건물에 번호 하나**
        측정선         판정색(위험 빨강 · 주의 노랑 · 안전 초록) · 주의·위험은 점선
        거리 배지      **상대 번호 + 거리**(「① 2.8 m」) — 번호는 그 상대 건물의 이름이다

    `near` 는 이 지번이 아닌 건물 — Feature 목록이면 `bld_id` 로 표의 ①②③ 과 맞춰지고,
    폴리곤 목록이면 가까운 순으로 번호만 붙는다. `sep` 은 separation FeatureCollection 이다.
    """
    from shapely.geometry import shape

    exts = ext_index(near, blds, only=sep_ext_ids(sep, blds, skip=skip),
                     window=label_box(site), site=site,
                     order=sep_arc_order(sep, skip=skip), force=force)
    # 번호는 **건물마다 하나**이고 `ext_index` 가 매긴 그 번호를 지도와 표가 같이 쓴다
    # (`ext_names`) — 여기서 따로 세면 두 종이가 조용히 갈린다.
    num = {b: n for n, _g, b in exts if b and n}
    # 번호를 못 붙일 만큼 창 밖인 「안전」 상대는 **재지 않은 것으로 한다** — 선도 배지도
    # 그리지 않는다(`sep_hidden`). 표도 같은 함수로 같은 줄을 뺀다.
    hide = sep_hidden(sep, num, skip=skip)
    dong = dong_names(blds)
    # **거리 배지가 다는 것은 줄의 번호다**(`sep_ids`) — 표의 「이격 번호」 칸과 1:1.
    sid = sep_ids(sep, dong, skip=skip, hide=hide, ext=num)
    res_m = float((site.get("scene") or {}).get("res_m") or 0.5)

    def draw(d, v):
        sz = size or label_size(v)
        lw = stroke_w(v)
        for n, g, _b in exts:                  # 번호 없는 것은 옅게 — 배경으로 읽히게 둔다
            for r in v.xy(g):
                dash(d, r, EXT, w=(lw if n else max(1, lw - 1)),
                     on=4 * lw, off=3 * lw, alpha=(225 if n else 150), close=True)
        _parcel(d, v, site, w=lw, alpha=180)
        for f in blds.get("features") or []:
            for r in v.xy(f["geometry"]):
                ring(d, r, GTC, w=lw, fill=26)
        # 서로가 서로의 최단 상대이면 같은 선이 두 번 온다(A→B, B→A) — 선은 한 번만 긋고
        # 배지도 하나만 단다. 배지에 방위를 적지 않는 것은 **보는 쪽에 따라 뒤집히기**
        # 때문이다(A 의 남 = B 의 북). 방위는 「어느 건물의 줄인가」가 분명한 표에 적는다.
        groups = {}
        for f in sep_pairs(sep, skip=skip):
            if (f["properties"].get("pair") or [None, None])[1] in hide:
                continue
            co = list(shape(f["geometry"]).coords)
            key = frozenset(((round(x, 7), round(y, 7)) for x, y in (co[0], co[-1])))
            groups.setdefault(key, []).append(f)
        pend = []
        for fs in sorted(groups.values(),
                         key=lambda g: rules.LEVEL_ORDER.get(g[0]["properties"]["level"], 99)):
            r = v.xy(fs[0]["geometry"])
            if not r or len(r[0]) < 2:
                continue
            a, b = r[0][0], r[0][-1]
            top = min(fs, key=lambda f: rules.LEVEL_ORDER.get(f["properties"]["level"], 99))
            p = top["properties"]
            j = sep_level3(p["level"])
            c = SEP3C.get(j, MEAS)
            measure(d, a, b, c, w=lw, cap=3 * lw, dashed=(j != "안전"))
            # 거리 배지에 **그 줄의 번호**를 적는다. 자리는 `place_meas` 가 **그 거리를 잰
            # 상대 쪽으로** 비켜 놓아(아래 `toward`) 번호와 선이 같이 읽히게 한다.
            other = (p.get("pair") or [None, None])[1]
            pend.append((a, b, _meas_text(p, res_m, sid.get(sep_key(p))), c, other))
        # 배지는 **맨 나중에, 동 이름부터.** 표가 「A동」으로 부르는데 지도에 그 이름이 없으면
        # 어느 건물의 값인지 되짚을 수 없다 — 자리를 못 얻어 빠지는 것은 거리 쪽이 낫다.
        rects, win = [], v.base.size
        # **창으로 자른 폴리곤 한 벌**을 먼저 만든다. 이름표 자리도(`place_on`) 거리 배지의
        # 「상대 쪽」도(`toward`) 이 도형에서 나온다 — 두 곳에서 따로 재면 배지가 가리키는
        # 곳과 그리는 곳이 갈린다. 창 밖 도형은 여기서 이미 빠진다(`px_poly` 가 None).
        shp = {}
        for f in (blds.get("features") or []):
            q = px_poly(v, f["geometry"], clip=win)
            if q is not None:
                shp[f["properties"].get("bld_id")] = q
        for _n, g, bid in exts:
            q = px_poly(v, g, clip=win)
            if q is not None and bid:
                shp[bid] = q
        # 이름표는 **남의 지붕을 피한다**(`avoid`) — 「A동」이 옆 지번 건물 위에 앉으면 그
        # 건물이 A동이 된다(실측 고잔동 672-6). 우리 동과 번호 받은 외부 건물이 서로 피한다.
        keep = set(shp)
        avoid = list(shp.values())
        centers = {b: label_anchor(q) for b, q in shp.items()}
        for f in sorted(blds.get("features") or [],
                        key=lambda x: -(x["properties"].get("arch_area_m2") or 0)):
            bid = f["properties"].get("bld_id")
            if bid in keep:
                place_on(d, rects, shp[bid], dong.get(bid, "동"),
                         bg=GTC, size=sz, bounds=win, avoid=avoid)
        # 외부 배지가 거리보다 먼저다 — 「이 점선은 남의 건물」이라는 사실은 지도에만 있고,
        # 거리는 표에 방위와 함께 다시 적힌다. 자리를 못 얻어 빠지는 것은 거리 쪽이어야 한다.
        #
        for n, g, bid in exts:
            if n and bid in keep:
                place_on(d, rects, shp[bid], f"{n}외부",
                         fg=EXT, size=sz, bounds=win, avoid=avoid)
        # 거리 배지는 **자기 선 곁**, 안 되면 **그 거리를 잰 상대 쪽**으로 놓는다
        # (`place_meas`). 세로로만 밀면 붐비는 모서리에서 남의 배지 옆에 붙어 그 건물의
        # 거리로 읽힌다 — 실측 호림동 3-10 남동 모서리가 그랬다.
        for a, b, t, c, other in pend:
            place_meas(d, rects, a, b, t, toward=centers.get(other), fg=c, size=sz,
                       nudges=6,      # 붐비는 모서리에서도 자리를 넉넉히 찾아 준다
                       bounds=win)
    return draw


def yard_draw(site, blds, near, yd, *, size=None, label=None):
    """야적물 — 필지 · 건물(「A동」 배지) · **탐지된 적재 구역만**. 테두리는 한 색이다.

    라벨은 **구역 코드(`Y0001`)** 다. 예전에는 분류 이름과 건물까지 거리를 라벨에 적었는데,
    구역이 셋만 넘어도 긴 글이 서로 포개져 자리를 못 얻은 구역이 라벨 없이 남았다(`place` 가
    겹치면 놓지 않는다). 코드로 적으면 짧아 다 앉고, 종류·거리·판정은 표에서 **그 코드로**
    되짚는다 — 건물을 「A동」·「①외부」로 부르고 값은 표에 두는 것과 같은 규약이다.

    `label` 을 주면 구역 라벨 문구를 그 함수가 만든다.
    """
    def text(p):
        return str(p.get("yard_id") or "적재")

    exts = ext_index(near, blds, only=set())        # 야적 판정에는 외부 건물 번호가 없다
    dong = dong_names(blds)

    def draw(d, v):
        sz = size or label_size(v)
        lw = stroke_w(v)
        for _n, g, _b in exts:
            for r in v.xy(g):
                dash(d, r, EXT, w=max(1, lw - 1), on=4 * lw, off=3 * lw,
                     alpha=150, close=True)
        _parcel(d, v, site, w=lw)
        for f in blds.get("features") or []:
            for r in v.xy(f["geometry"]):
                ring(d, r, GTC, w=lw, fill=22)
        feats = list(yd.get("features") or [])
        for f in feats:
            p = f["properties"]
            for r in v.xy(f["geometry"]):
                ring(d, r, YARD_ZONE, w=lw + 1, fill=34)
        # 라벨은 **자기 구역 · 자기 지붕 위**에 놓는다(`place_on`) — 창으로 자른 폴리곤을
        # 한 벌 만들어 두고 서로 피하게 한다. 구역 라벨이 건물 위에 앉으면 그 건물이
        # 적재 구역으로 읽히고, 「A동」이 옆 지번 건물 위에 앉으면 그 건물이 A동이 된다.
        win, rects = v.base.size, []
        zone = {id(f): px_poly(v, f["geometry"], clip=win) for f in feats}
        dpol = {}
        for f in (blds.get("features") or []):
            q = px_poly(v, f["geometry"], clip=win)
            if q is not None:
                dpol[f["properties"].get("bld_id")] = q
        avoid = [q for q in list(zone.values()) + list(dpol.values()) if q is not None]
        for f in sorted(feats, key=_zone_px_area(v), reverse=True):
            p, q = f["properties"], zone.get(id(f))
            if q is not None:
                place_zone(d, rects, q, (label or text)(p), YARD_ZONE,
                           size=sz, bounds=win, avoid=avoid)
        for f in sorted(blds.get("features") or [],
                        key=lambda x: -(x["properties"].get("arch_area_m2") or 0)):
            bid = f["properties"].get("bld_id")
            if bid in dpol:
                place_on(d, rects, dpol[bid], dong.get(bid, "동"),
                         bg=GTC, size=sz, bounds=win, avoid=avoid)
        if not feats:
            plate(d, (v.base.width / 2 - 6 * sz, v.base.height / 2),
                  "탐지된 적재 구역 없음", DIM, size=sz)
    return draw


def ledger_draw(site, blds, led, *, size=None, label=None, by=None):
    """대장 대조 — 필지 · 건물을 **일치 / 불일치 두 색**으로만 칠한다(설계서 BR-13).

    등록기하 도형은 없다. 배지는 설계서대로 **동 이름을 맨 앞**에 두고(「A동 불일치」),
    불일치일 때는 왜 그런지 붙인다 — 증축과 미등록을 **색으로는 나누지 않는다**.
    """
    # `by` 를 주면 그것을 쓴다 — 등록 기하가 없어 보고서가 **면적으로 맞춘 추정 대응**을
    # 세운 경우다(`report/single._pair_by_area`). 묶음 판정이 그 묶음의 건물 전부에 칠해져
    # 지도와 표가 같은 색을 말한다.
    if by is None:
        by = {f["properties"].get("bld_id"): f["properties"]
              for f in (led.get("features") or [])
              if f["properties"].get("scope") == "building"}
    par = led_parcel(led)
    dong = dong_names(blds)

    def text(f, p):
        """배지 글자 — **표·범례와 같은 말**을 쓴다(일치 · 불일치 · 판정 불가).

        동별 판정이 없어 총량으로 갈음한 동은 4면 표의 「판독 면적」 칸이 비므로, 위성이 이
        건물에서 읽은 면적을 배지에 적어 둔다 — 그 값이 남는 자리가 지도뿐이다.
        """
        name = dong.get(f["properties"].get("bld_id"), "동")
        m = led_match(p, par)
        if p is None:
            m2 = f["properties"].get("arch_area_m2") or 0
            return f"{name} {m}" + (f" · {m2:,.0f}㎡" if m2 else "")
        if m == "판정 불가" and p.get("ledger_m2") is not None:
            d = (p.get("measured_m2") or 0) - (p.get("ledger_m2") or 0)
            return f"{name} 판정 불가 · {d:+,.0f}㎡"
        if m != "불일치":
            return f"{name} {m}"
        if p.get("ledger_m2") is None:                     # 대장에 없는 동 — 설계서 ⑤
            return f"{name} 불일치 · 대장에 없음"
        diff = (p.get("measured_m2") or 0) - (p.get("ledger_m2") or 0)
        return f"{name} 불일치 · {diff:+,.0f}㎡"

    def draw(d, v):
        sz = size or label_size(v)
        lw = stroke_w(v)
        _parcel(d, v, site, w=lw)
        for f in blds.get("features") or []:
            p = by.get(f["properties"]["bld_id"])
            c = MATCH3.get(led_match(p, par), GTC)
            for r in v.xy(f["geometry"]):
                ring(d, r, c, w=lw, fill=30)
        win, rects = v.base.size, []
        pol = {}
        for f in (blds.get("features") or []):
            q = px_poly(v, f["geometry"], clip=win)
            if q is not None:
                pol[f["properties"]["bld_id"]] = q
        avoid = list(pol.values())
        for f in sorted(blds.get("features") or [],
                        key=lambda x: -(x["properties"].get("arch_area_m2") or 0)):
            bid = f["properties"]["bld_id"]
            p = by.get(bid)
            if bid in pol:
                place_on(d, rects, pol[bid], (label or text)(f, p),
                         bg=MATCH3.get(led_match(p, par), GTC), size=sz,
                         bounds=win, avoid=avoid)
    return draw


def poly_draw(site, blds, near, *, size=None):
    """건물 폴리곤 그 자체 — 필지 · 이 지번 건물(「A동」 배지) · 옆 지번 건물(회색 점선).

    **판정을 얹지 않는다.** 이격·야적·대장 세 그림이 전부 이 폴리곤 위에 서 있으므로, 얹은
    것이 없는 판이 따로 있어야 두 가지를 눈으로 확인할 수 있다 — 폴리곤이 영상과 맞는지
    (정합)와 어느 동이 빠졌는지. 판정색을 쓰면 그 확인이 판정 해석과 섞인다.

    폴리곤이 GT 에서 왔는지 모델에서 왔는지는 **파일 이름이 말한다**(`poly_name`) —
    `result.json`/`demo.json` 을 갈라 둔 것과 같은 이유다. 그리는 규칙은 둘이 같아야
    나란히 견줄 수 있으므로 여기서는 가르지 않는다.

    옆 지번 건물에 ①②③ 을 달지 않는다 — 번호는 이격 표의 행과 1:1 이어야 뜻이 있는데
    이 그림에는 표가 없고, 공단 필지 주변은 수십 동이라 번호가 화면을 덮는다.
    """
    exts = ext_index(near, blds, only=set())
    dong = dong_names(blds)

    def draw(d, v):
        sz = size or label_size(v)
        lw = stroke_w(v)
        for _n, g, _b in exts:
            for r in v.xy(g):
                dash(d, r, NEAR, w=max(1, lw - 1), on=4 * lw, off=3 * lw,
                     alpha=150, close=True)
        _parcel(d, v, site, w=lw)
        for f in blds.get("features") or []:
            for r in v.xy(f["geometry"]):
                ring(d, r, GTC, w=lw, fill=26)
        win, rects = v.base.size, []
        pol = {}
        for f in (blds.get("features") or []):
            q = px_poly(v, f["geometry"], clip=win)
            if q is not None:
                pol[f["properties"].get("bld_id")] = q
        avoid = list(pol.values())
        for f in sorted(blds.get("features") or [],
                        key=lambda x: -(x["properties"].get("arch_area_m2") or 0)):
            bid = f["properties"].get("bld_id")
            if bid not in pol:
                continue
            # 면적을 배지에 함께 적는다 — 이 그림에는 표가 없어서 「A동」만으로는 그 동이
            # 얼마로 잡힌 것인지 되짚을 곳이 없다(대장 그림은 판정과 함께 적는다).
            m2 = f["properties"].get("arch_area_m2") or 0
            place_on(d, rects, pol[bid],
                     dong.get(bid, "동") + (f" · {m2:,.0f}㎡" if m2 else ""),
                     bg=GTC, size=sz, bounds=win, avoid=avoid)
    return draw


# ── 결과 → 그림 세 장 ───────────────────────────────────────────────────────
BASE_NAME = "0_위성영상"          # 아무것도 얹지 않은 바탕 — 세 그림과 같은 창이다


def result_images(result, out_dir, *, near=(), verbose=False):
    """`result.json`/`demo.json` → 그림 네 장. 만든 경로 목록을 돌려준다.

    `run.py`(모델)와 `demo.py`·`hand_writting.py`(GT)가 **이 함수 하나**를 쓴다 — 그림을 만드는 자리가 둘이면
    같은 물건이 경로마다 다르게 나온다. PDF·HTML 로 묶는 것은 저장소 밖의 도구가 한다.

    **바탕도 한 장 남긴다**(`0_위성영상`). 세 그림은 선·배지를 얹은 것이라, 얹은 것이 무엇을
    가렸는지 따지려면 같은 창의 원본이 있어야 한다 — 없으면 다시 잘라 보는 수밖에 없다.
    """
    site, L = result["site"], result["layers"]
    v = View(site)
    if not v.ok:
        return []
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    base = out / f"{BASE_NAME}.png"
    v.base.save(base)
    made = [base]
    for name, layer in (("1_이격거리", sep_draw(site, L["buildings"], near, L["separation"])),
                        ("2_야적물", yard_draw(site, L["buildings"], near, L["yard"])),
                        ("3_미등록증축", ledger_draw(site, L["buildings"], L["ledger"]))):
        q = out / f"{name}.png"
        v.panel(layer).save(q)
        made.append(q)
    for q in made:
        (con.detail if verbose else con.SILENT.detail)(f"그림 {q.name}")
    return made


def poly_name(result):
    """건물 폴리곤 그림의 이름 — **GT 로 낸 것과 모델로 낸 것을 이름에서 가른다.**

    `result.json`/`demo.json` 을 갈라 둔 것과 같은 이유다(폴더만 보고 어느 길로 나온
    산출물인지 알아야 한다 — [[pipeline.py]]). 판단 근거는 `provenance.model.building`
    하나뿐이고, 그 값은 GT 경로에서 `"GT <파일>"` 로 적힌다.
    """
    src = str((((result.get("provenance") or {}).get("model") or {}).get("building")) or "")
    return "0_GT건물" if src.startswith("GT") else "0_모델건물"


def input_images(result, out_dir, *, near=(), verbose=False):
    """**판정 전 재료 두 장** — 영상 바탕(`0_위성영상`)과 건물 폴리곤(`0_GT건물`/`0_모델건물`).

    `result_images` 가 내는 세 장은 판정을 얹은 것이라, 판정이 아니라 **입력**을 보고 싶을 때
    쓸 판이 없었다 — 비교분석([[report/compare.py]])의 `demo_cmp/t1`·`t2` 는 값만 남고 그림은
    보고서 쪽 폴더로 나가므로, 두 시기를 견줄 때 제일 먼저 보고 싶은 것(얹은 것 없는 영상과
    폴리곤: 정합이 맞나 · 어느 동이 빠졌나)이 폴더에 없었다.

    두 장이 `View` **하나**에서 나오므로 창과 픽셀이 같다 — 겹쳐 놓고 넘겨 볼 수 있다.
    바탕은 `result_images` 와 **같은 이름·같은 내용**이다(한 이름이 두 물건을 뜻하면 안 된다).
    """
    site, L = result["site"], result["layers"]
    v = View(site)
    if not v.ok:
        return []
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    base = out / f"{BASE_NAME}.png"
    v.base.save(base)
    poly = out / f"{poly_name(result)}.png"
    v.panel(poly_draw(site, L["buildings"], near)).save(poly)
    made = [base, poly]
    for q in made:
        (con.detail if verbose else con.SILENT.detail)(f"재료 그림 {q.name}")
    return made


def own_centroids(blds):
    """이 지번 건물의 중심 집합 — 주변 건물을 가려낼 때 쓴다."""
    from shapely.geometry import shape
    return {(round(shape(f["geometry"]).centroid.x, 7),
             round(shape(f["geometry"]).centroid.y, 7))
            for f in (blds.get("features") or [])}


def others(polys, blds):
    """폴리곤 목록에서 **이 지번이 아닌 것**만 — 그림의 주변 건물."""
    own = own_centroids(blds)
    return [g for g in polys
            if (round(g.centroid.x, 7), round(g.centroid.y, 7)) not in own]


# ── 범례 — **그림에 실제로 칠한 것만** ──────────────────────────────────────
def hexc(t):
    """(r,g,b) → "#rrggbb". 이미 문자열이면 그대로 — 세 도구가 색 표기를 섞어 쓴다."""
    return t if isinstance(t, str) else "#%02x%02x%02x" % tuple(t[:3])


def _col(c):
    """PIL 에 넣을 색. 튜플이면 튜플, 문자열이면 문자열(ImageColor 가 받는다)."""
    return c if isinstance(c, str) else tuple(c)


def sep_legend(sep, *, skip=(), name=None):
    """이격 그림의 범례 — 설계서 3단계(안전·주의·위험) 이름으로 낸다.

    7단계 중 둘이 같은 3단계로 접히므로(경고·해당 → 위험) **접은 뒤에 중복을 없앤다** —
    안 그러면 같은 색 「위험」이 두 번 나온다.
    """
    out = [("대상 건물", hexc(GTC)), ("외부 건물(점선)", hexc(EXT)),
           ("대지 경계", hexc(PARCEL))]
    seen = []
    for f in sorted(sep_pairs(sep, skip=skip),
                    key=lambda f: rules.LEVEL_ORDER.get(f["properties"]["level"], 99)):
        j = sep_level3(f["properties"]["level"])
        if j not in seen:
            seen.append(j)
    for j in seen:
        out.append(((name or (lambda x: x))(j), hexc(SEP3C.get(j, MEAS))))
    return out


def yard_legend(yd):
    """색이 하나이므로 범례도 한 줄이다 — 분류 이름은 범례가 아니라 표에서 읽는다."""
    return ([("적재 구역", hexc(YARD_ZONE))] if (yd.get("features") or []) else []) \
        + [("건물", hexc(GTC)), ("대지 경계", hexc(PARCEL))]


def ledger_legend(blds, led, by=None):
    """대장 대조 그림의 범례 — 설계서 BR-13 은 **일치 / 불일치 둘**만 쓴다."""
    if by is None:
        by = {f["properties"].get("bld_id"): f["properties"]
              for f in (led.get("features") or [])
              if f["properties"].get("scope") == "building"}
    par = led_parcel(led)
    ms = [led_match(by.get(f["properties"]["bld_id"]), par)
          for f in (blds.get("features") or [])]
    out = [(m, hexc(MATCH3[m])) for m in ("일치", "불일치", "판정 불가") if m in ms]
    return out + [("대지 경계", hexc(PARCEL))]
