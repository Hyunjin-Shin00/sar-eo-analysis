"""데모 결과 → **보고서 한 부** (PDF + HTML, 같은 판짜기).

`demo.py`·`hand_writting.py` 가 내는 시트는 **검증용**이다 — 정합·등록기하·법정선까지 다 얹어 눈으로 따질 수
있게 만든 그림이라 보고서에 그대로 넣으면 번잡하다. 그래서 보고서는 **같은 값으로 그림을
다시 그린다**. 항목마다 그 판정에 필요한 것만 남긴다.

    ① 이격거리     필지 · 우리 건물 · 외부 건물 · 측정선          (등록기하·법정선 없음)
    ② 야외 적재물   필지 · 건물 · 탐지된 적재 구역                 (탐지영역 채움·6 m 파선 없음)
    ③ 미등록·증축   필지 · 건물을 **대장과 맞나 아닌가**로 색만    (등록기하 도형 없음)

내용도 줄인다. 받는 쪽이 먼저 알아야 하는 것은 (1) 이 물건은 어떻게 나왔는가 (2) 무슨
형태로 받는가 둘이고, 법 조문·임계값·모델 이야기는 넣지 않는다(값이 필요하면 demo.json).

    python -m sitecheck.report.single "<주소>"            → 그 결과 폴더에 「보고서.pdf/html」
    python -m sitecheck.report.single "..." --skip-dir 북  그 방향은 도로라 이격 대상이 아니다
    python -m sitecheck.report.single "..." --no-html      PDF 만

보통은 직접 부르지 않는다 — 진입점 셋이 `pipeline.finish` 를 거쳐 이 파일을 부른다. 여기를
직접 돌리는 것은 **이미 있는 결과 폴더로 종이만 다시 뽑을 때**다.

서식은 화재보험협회 「특수건물 요약정보」를 따랐다(A4 세로 · ■ 절 제목 · 라벨-값 표) —
받는 쪽이 이미 그 모양으로 읽고 있어서 어디를 봐야 하는지 설명할 필요가 없다.

    1면  개요 · 진행 방식 · 이 물건의 결과
    2면  건물 간 이격거리
    3면  야외 적재물
    4면  미등록·증축 건물

**부르는 이름과 판정어는 「SatCHAT 화면 설계서 v38」 BR-13 을 따른다** — 건물은 A동·B동,
이 지번이 아닌 건물은 ①②③, 이격은 안전·주의·위험, 대장은 일치·불일치다. 화면과 보고서가
다른 말을 쓰면 같은 물건을 두 번 배워야 한다. 옮기는 표는 [[draw.py]] 에 한 벌 있다
(`dong_names` · `ext_names` · `sep_level3` · `led_match`) — 그림도 그것을 쓴다.

머리(고객사 로고 · 남색 띠)와 판 크기는 「지반침하 위험 보고서 샘플」을 재서 맞췄다.
**mm 를 원본으로 둔다** — PDF 는 figure 비율, HTML 은 CSS mm 로 같은 값을 나눠 쓴다.

한 벌의 내용(`build_doc`)을 PDF 와 HTML 두 렌더러가 나눠 쓴다. 두 벌로 쓰면 숫자가 갈린다.
HTML 은 A4 그대로(210×297 mm)이고 글자도 pt 라 인쇄하면 PDF 와 같은 크기로 앉는다.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt                                   # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages              # noqa: E402
from matplotlib.patches import Rectangle                          # noqa: E402

from sitecheck import console as con
from sitecheck import draw as DR                                                 # noqa: E402
from sitecheck import ext as EX                                 # noqa: E402
from sitecheck import rules as RL                              # noqa: E402
from sitecheck import gt as GT                                                        # noqa: E402
from sitecheck import settings as config                          # noqa: E402
from sitecheck.steps import s3_separation as S3                   # noqa: E402
from sitecheck.naming import slug                                 # noqa: E402

A4 = (8.27, 11.69)               # matplotlib figsize(inch)
A4MM = (210.0, 297.0)            # 판짜기의 단위 — 여기서 비율과 CSS 를 둘 다 낸다
FONT = "Noto Sans CJK JP"        # Noto CJK 는 한 파일에 한글이 다 들어 있다(JP 로 등록된다)
INK = "#1a1a1a"
# **보고서에 회색 글자를 두지 않는다**(2026-08-23). 각주와 면 부제는 아예 안 싣고
# (`SHOW_NOTES` · `SHOW_SUB`), **남는 회색은 검정으로 올린다** — 범례 이름 · 쪽 밑 글줄 ·
# 표 안의 「판정 불가」·「기준값」 따위다. 회색으로 적힌 것은 「덜 중요하다」로 읽히는데,
# 그 칸들은 판정이 실리는 자리라 덜 중요하지 않다.
#
# **이름을 지우지 않고 값만 잉크로 둔다.** 부르는 곳이 스물이 넘고 [[compare.py]]
# 도 `FR.DIM` 으로 들여다본다 — 이름을 없애면 그 파일까지 같이 고쳐야 하고, 회색을 되살릴
# 일이 생겼을 때 되돌릴 자리도 사라진다. 지금은 이 한 줄이 그 스위치다.
DIM = INK                        # 회색을 되살리려면 "#6b7280"
LINE = "#c9cdd4"
HEAD_BG = "#eceef1"
BAND = "#f7f8fa"
# 로고 밑줄 — 「지반침하 위험 보고서 샘플(주의·누적구역)」의 색을 재서 쓴다.
# **예전에는 전폭 남색 띠(#1f3864)였다.** 그것은 같은 보고서의 **구판**(`지반침하_보고서샘플.pdf`)
# 형식이고, 지금 따르는 신판은 **로고 폭만큼의 얇은 밝은 파란 밑줄**이다(실측 2026-08-25:
# 구판 = 도련까지 3.4 pt 띠 · 신판 = x 493.9~555.6 · 두께 1.2 pt · fill (0, 0.235, 0.863)).
RULE = "#003cdc"

# ── 판짜기 ──────────────────────────────────────────────────────────────────
# 「지반침하 위험 보고서 샘플」 1면을 100 dpi 로 재서 옮긴 값이다(A4 위에서부터, mm):
#
#     로고     위 2.79 · 높이 4.83 · 오른쪽 끝 195.3      (= 좌우 여백 14.7)
#     남색 띠   위 9.90 · 높이 1.27 · 좌우 끝까지(도련)
#     제목     글자 위 18.78
#     본문     위 28.68  ← 샘플에는 부제가 없다. 이 보고서는 부제 한 줄이 더 들어간다
#
# 값을 figure 비율(PDF)과 mm(CSS)로 각각 손으로 적으면 두 판이 조용히 갈린다. **mm 만
# 적고** 비율은 `_fy`·`_fx` 가 낸다.
MARGIN_MM = 14.7
LOGO_TOP_MM, LOGO_H_MM = 4.37, 6.21      # 샘플 실측 12.4 pt · 17.6 pt
RULE_TOP_MM, RULE_H_MM = 15.20, 0.42     # 샘플 실측 43.1 pt · 1.2 pt
# 밑줄 **폭은 여기 없다** — 로고 그림의 폭을 그대로 쓴다(가로세로비가 정한다). 숫자로 적어
# 두면 로고를 바꿀 때 밑줄만 옛 폭으로 남는다.
TITLE_TOP_MM = 18.6
SUB_TOP_MM = 26.4
BODY_TOP_MM = 32.6
FOOT_BOT_MM = 8.9                # 쪽 밑 글줄
LOGO = config.ASSETS / "brand" / "client_logo.png"


def _fy(mm):
    """위에서 mm → figure 세로 비율(matplotlib 은 아래에서 잰다)."""
    return 1.0 - mm / A4MM[1]


FLOOR_Y = 1.0 - (A4MM[1] - FOOT_BOT_MM - 4.0) / A4MM[1]   # 본문이 넘어서면 안 되는 바닥


def _fx(mm):
    return mm / A4MM[0]


MARGIN = _fx(MARGIN_MM)                  # 0.07 — 좌우 여백(폭 비율)
BODY_W = 1.0 - 2 * MARGIN                # 0.86 — 본문 폭

# 2·3·4면은 그림 한 장 + 표 하나다. **표가 길면 그림을 줄이고, 그래도 넘치면 표를 자른다** —
# 쪽 밑으로 흘러 글줄을 덮는 것이 가장 나쁘다(실측 공단동 150: 4면 대장 31동이 표 31행이
# 되어 23행이 종이 밖으로 사라졌다). 자른 줄은 「외 N동」으로 알린다 — 값은 결과 파일에 다
# 있으므로 잃는 것은 없지만, 잘렸다는 사실은 종이에 남아야 한다.
BODY_ROOM = 0.838                # 본문에 쓸 수 있는 세로(figure 비율) — 쪽 밑 글줄 위까지
ROW_H = 0.0215                   # 표 한 줄
IMG_MAX, IMG_MIN = 0.52, 0.30


NOTE_H = 0.0152                  # 각주 한 줄
NOTE_GAP = 0.002                 # 각주 사이


# **회색 글자(각주 · 면 부제)를 내지 않는다**(2026-08-23). 읽는 법을 적은 글이라 내용은
# 맞지만, 물건 하나에 스무 줄 가까이 붙어 종이의 절반을 회색으로 덮었다. 문구는 지우지 않고
# 스위치 하나로 껐다 — 근거·출처를 다시 종이에 실어야 하면 True 로 되돌리면 되고, 그때
# 판짜기도 저절로 자리를 다시 뗀다(`_note_cost` 가 0 을 돌려주므로 지금은 그 자리가 그림과
# 표로 간다). **끄는 것은 렌더러가 아니라 내용 한 벌(`build_doc`)이다** — 자리 계산과 실제로
# 찍히는 것이 갈리면 면이 넘치거나 밑이 휑해진다.
SHOW_NOTES = False               # 표 아래 「· …」 각주
SHOW_SUB = False                 # 면 제목 아래 회색 한 줄

def _note_cost(notes):
    """각주가 먹는 세로. **렌더러와 같은 폭(58자)으로 접어 센다** — 어림하면 넘친다."""
    if not SHOW_NOTES:
        return 0.0
    import textwrap
    lines = sum(max(1, len(textwrap.wrap(t, width=58))) for t in notes)
    return lines * NOTE_H + len(notes) * NOTE_GAP


SEC_H = 0.0165                   # ■ 절 제목
TBL_GAP = 0.017                  # 표 아래 여백
LEGEND_H = 0.026
SEP_SUB = "부지를 한 바퀴 돌며 옆 건물까지의 최단거리를 잰다. 선 길이가 곧 거리다."

# 그림 밑 각주는 **물건마다 달라지지 않는다.** 읽는 법을 적은 글이라 늘 같아야 하고, 물건마다
# 늘었다 줄었다 하면 회색 글이 뭉텅이로 붙었다 사라져 판이 흔들린다. 그래서 여기 고정해 두고,
# 이 물건에만 해당하는 값(합계·제외 방향 따위)은 **표와 1면 개요**에 넣는다 — 그쪽이 원래
# 물건마다 달라지는 자리다.
SEP_NOTES = [
    "지붕 외곽선 사이의 최단거리. 기준선은 양쪽 1층 6 m, 한쪽이라도 2층이면 10 m.",
    "표는 대상 동마다 하나다 — 방위는 그 동에서 본 방향이라 A 의 남이 B 의 북이 된다."
    " 필지 밖은 대지경계선을 북쪽부터 시계방향으로 돌며 자리마다 가장 가까운 건물을 적는다.",
    "기준선보다 멀어도 잰 값을 적는다 — 「재지 않았다」와 「재서 이상 없다」는 다른 말이다."
    " 줄이 없는 방향은 60 m 안에 건물이 없다는 뜻이다. 다만 **지도 창 밖이라 번호를 붙일 수"
    " 없는 먼 상대는 그 줄이 「안전」일 때 표에서 뺀다** — 지도에서 되짚을 수 없는 값이기"
    " 때문이고, 값 파일에는 그대로 남는다. 위험·주의인 줄은 번호가 없어도 빼지 않는다.",
    "번호 ①②③ 은 부지 북쪽부터 시계방향으로 **외부 건물마다** 하나 — 한 건물을 두 동이"
    " 마주 서면 A동 표와 B동 표에 같은 번호가 한 줄씩 서고, 그것이 「같은 건물을 두 동에서"
    " 쟀다」는 뜻이다. 지도 창 밖이라 번호를 못 붙인 줄은 번호 칸이 「—」이고, 지도에서는"
    " 방위와 거리로 적는다(「남동 29.8 m」). 우리 동끼리 지붕이 0.5 m 이하로 붙은 쌍은 한"
    " 덩어리로 보아 뺀다 — 옆 지번 건물은 빼지 않고 「0.5 m 이하」로 적는다. 0.5 m 는 영상"
    " 한 픽셀이라 그 이하는 잰 값을 적지 않는다.",
]
YARD_NOTES = [
    "종류는 겉모습으로 가른 값. 쌓인 양은 재지 않는다.",
]
LED_NOTES = [
    "면적은 지붕을 위에서 본 넓이 — 대장의 건축면적과 같은 기준. 차이율은 (판독 − 대장) ÷ 대장.",
    "대장에 없는 동은 「불일치」, 판독이 대장보다 크게 모자라면 「판정 불가」 — 이 판정은 "
    "대장을 넘는 분만 본다.",
    "대장에는 위치가 없다. 등록 기하가 없으면 면적이 가장 잘 맞는 대응을 세워 대조하고"
    "(제목에 「추정」), 한 대장 동에 판독 동 여럿이 묶일 수 있다. 정본은 맨 아랫줄의 총량.",
]
def _tbl_h(n):
    """머리행 + n줄 + 아래 여백."""
    return ROW_H * 1.15 + n * ROW_H + TBL_GAP


def _img_h(path, want):
    """그림이 **실제로** 차지할 세로. 정사각에 가까운 창은 폭(본문 86 %)이 먼저 걸려
    `want` 만큼 높아지지 않는다 — 그걸 모르고 자리를 잡으면 밑이 휑하거나 넘친다."""
    from PIL import Image
    iw, ih = Image.open(path).size
    return round(min(want, BODY_W * A4[0] * ih / iw / A4[1]), 4)


SEP_TITLE = "① 건물 이격거리"
# 이격 표 열 — **이격 번호 · 외부건물 번호 · 방위 · 이격거리 · 판정**(2026-08-27).
#
#     이격 번호     그 **측정선** 하나의 고유 번호(`draw.sep_ids`) — 지도의 거리 배지와 1:1
#     외부건물 번호  그 줄이 가리키는 **상대**(「①」) — 지도의 회색 배지와 1:1.
#                   필지 안 상대는 번호가 아니라 상대 동 이름(「B동」)이 온다
#
# 번호를 둘로 가른 것은 **재는 것과 상대가 다른 것**이기 때문이다. 한 상대를 우리 동 둘이
# 마주 서거나 한 상대가 떨어진 두 구간을 이기면 줄은 둘인데 상대는 하나다 — 한 칸에 두 뜻을
# 담으면 그때 반드시 어느 한쪽이 거짓이 된다(그래서 한때 「⑤⑥외부」가 나왔다).
#
# **「마주한 폭」 열은 없다**(2026-08-26) — 표가 대상 동마다 갈려 있어 방위 칸이 그 구실을
# 한다. **이격거리는 가운데 정렬**이다(2026-08-27) — 오른쪽에 붙여 두면 넓어진 칸 왼쪽이
# 비어 옆 칸과 멀어진다.
SEP_COLW = [0.13, 0.17, 0.15, 0.28, 0.27]
SEP_OPT = {"colw": SEP_COLW, "head": True}
SEP_HEAD = ["이격 번호", "외부건물 번호", "방위", "이격거리", "판정"]


def _sep_pages(img, legend, tables, notes):
    """이격 면(들). 표가 길면 **지도를 줄이는 대신 면을 늘린다.**

    이 그림은 크게 봐야 하는 그림이다 — 선 길이가 곧 거리이고, 어느 배지가 어느 선의 것인지
    눈으로 따라가야 한다. 표에 자리를 내주느라 지도를 0.3 면까지 줄였더니 선과 글자가 뭉개져
    「명확하지 않다」는 말이 나왔다(2026-08-20). 그래서 한 면에 다 들어가면 한 면으로,
    아니면 **지도 한 면 + 표 한 면**으로 낸다.

    `tables` 는 `[(절 제목, 표), …]` 다 — 대상 동마다 하나(`sep_dong_rows`).
    """
    blocks = []
    for name, t in tables:
        blocks += [("sec", name), ("tbl", t, SEP_OPT)]
    body = sum(_tbl_h(len(t) - 1) + SEC_H for _n, t in tables)
    room = BODY_ROOM - (0.010 + LEGEND_H + body + _note_cost(notes))
    if room >= IMG_MIN + 0.06:                      # 지도가 옹색하지 않게 들어가면 한 면
        return [{"kind": "sep", "title": SEP_TITLE, "sub": SEP_SUB, "blocks":
                 [("img", img, {"h": _img_h(img, min(IMG_MAX, room))}), ("legend", legend)]
                 + blocks + [("note", n) for n in notes]}]
    # 지도 한 면 + 표 한 면. **각주는 지도 쪽에 둔다** — 지도를 읽는 법을 적은 글이고, 정사각
    # 창은 폭에 먼저 걸려 밑이 남기 때문이다. 다만 **각주 자리를 먼저 떼고** 지도 높이를
    # 정한다 — 세로로 긴 창은 폭이 아니라 높이가 먼저 차서, 안 떼면 각주가 종이 밖으로 나간다
    # (실측 호림동 5-2: 1,359×1,600 창 + 각주 6줄 = 300 mm).
    guide = "번호(①②③)와 거리는 다음 면의 표에 있다."
    ncost = _note_cost([guide] + notes)
    h = _img_h(img, BODY_ROOM - (0.010 + LEGEND_H + ncost))
    if h >= IMG_MIN:
        return [
            {"kind": "sep", "title": SEP_TITLE, "sub": SEP_SUB, "blocks":
             [("img", img, {"h": h}), ("legend", legend)]
             + [("note", n) for n in [guide] + notes]},
            {"kind": "sep", "title": f"{SEP_TITLE} (이어서)",
             "sub": "앞 면 지도에 그린 쌍을 표로 옮긴 것.", "blocks": blocks}]
    # 각주까지 떼면 지도가 옹색해지는 창 — 각주를 표 면으로 넘긴다.
    return [
        {"kind": "sep", "title": SEP_TITLE, "sub": SEP_SUB, "blocks":
         [("img", img, {"h": _img_h(img, BODY_ROOM - (0.010 + LEGEND_H + _note_cost([guide])))}),
          ("legend", legend), ("note", guide)]},
        {"kind": "sep", "title": f"{SEP_TITLE} (이어서)",
         "sub": "앞 면 지도에 그린 쌍을 표로 옮긴 것.", "blocks":
         blocks + [("note", n) for n in notes]}]


def _rows_fit(room, *counts):
    """한 면(`room`)에 표 여럿을 넣을 때 각 표에 줄 수 있는 줄 수 — 큰 표부터 깎는다."""
    n = list(counts)
    while sum(_tbl_h(x) + SEC_H for x in n) > room and max(n) > 1:
        n[n.index(max(n))] -= 1
    return n


def _fig_page(units, notes):
    """(그림 높이, 실을 수 있는 줄 수). `units` 는 표가 요구하는 줄 수(여러 줄 셀은 1보다 큼).

    고정비는 그림 아래 여백 · 범례 · 절 제목 · 머리행 · 표 아래 여백 · 각주다. **각주까지
    실제로 세는** 이유는 4면 각주가 다섯 줄까지 늘어나기 때문이다(동별 짝 · 부속 제외 ·
    차이율 · 대장에 없는 동) — 넉넉히 어림하면 그림이 늘 작아지고, 짜게 잡으면 넘친다.
    """
    fixed = 0.010 + 0.026 + 0.0165 + ROW_H * 1.15 + 0.017 + _note_cost(notes)
    room = BODY_ROOM - fixed
    h = max(IMG_MIN, min(IMG_MAX, room - units * ROW_H))
    return round(h, 3), max(1, int((room - h) / ROW_H))
# 4면 열 폭 — 용도·구조가 길어 「대장 동」 열을 가장 넓게 잡는다(`_clip` 이 이 값을 본다).
LED_COLW = [0.09, 0.28, 0.06, 0.13, 0.14, 0.16, 0.14]

# **`rules` 의 일곱 등급을 종이에 그대로 적지 않는다.** 종이가 쓰는 판정어는 1면 「판정
# 기준」 표가 못 박은 것뿐이다 — 이격은 안전·주의·위험, 대장은 일치·불일치, 야적은 현장
# 확인 필요, 낼 수 없으면 판정 불가. 옮기는 곳은 `sep_lv`·`led_lv`·`_yard_lv` 셋이고
# 3단계 표는 [[draw.py]] `sep_level3`·`led_match` 하나씩이다.
#
# 예전에는 일곱 등급을 「확인 필요·주의·참고·이상 없음·판단 보류」로 옮기는 표(`LEVEL`)가
# 여기 하나 더 있었다(2026-08-27 걷어 냄). 그 다섯 말은 **판정 기준 표에 없는 말**이라
# 종이 안에서 어휘가 둘이 되었다 — 비교분석 1면의 대장 줄만 「이상 없음」이라고 적고 같은
# 문서 4면은 같은 값을 「일치」라고 적고 있었다. 지금 그 줄은 `led_lv` 를 쓴다.
ORDER = ["경고", "해당", "주의", "참고", "기록", "이상없음", "정보없음"]

# 설계서 BR-13 판정어. **색은 문서용 잉크**다 — 지도 팔레트(`draw.SEP3C`)는 위성 위에서
# 읽히게 밝혀 놓은 색이라 흰 종이의 글자로 쓰면 흐리다. 범례의 색칸은 그림에서 그대로
# 가져오고(칠한 것과 같아야 한다), 표의 글자는 여기 색을 쓴다.
SEP_DOC = {"위험": "#c0392b", "주의": "#c07a1a", "안전": "#1f7a4d", "판정 불가": DIM}
MATCH_DOC = {"일치": "#1f7a4d", "불일치": "#c07a1a", "판정 불가": DIM}
# **종이에 나올 수 있는 판정어는 이 일곱뿐이다.** 1면 「판정 기준」 표가 못 박은 말이고,
# 「이상 없음」·「확인 필요」·「참고」·「판단 보류」처럼 그 표에 없는 말은 쓰지 않는다
# (사용자 결정, 2026-08-27). 판정어를 새로 만들려면 먼저 그 표에 칸이 있어야 한다.
WORDS = ("위험", "주의", "안전", "일치", "불일치", "현장 확인 필요", "판정 불가")
RISK3 = ["위험", "주의", "안전"]                  # 나쁜 것부터 — 종합 위험도를 고를 순서
# **적재물 위험등급은 더 내지 않는다**(2026-08-23). 종류를 겉모습으로 가른 값에 등급을 매겨
# 종이에 적으면 확정한 것처럼 읽힌다 — 3면은 구역 코드와 건물까지의 거리만 싣고, 등급을
# 매기던 표(`_risk_table`)와 함수(`_risk` · `RISK`)는 가리킬 칸이 없어져 걷어 냈다.
# 분류 자체는 값 파일(`layers.yard[*].cls` · `cls_ko`)에 그대로 남는다 — 탐지가 그것으로
# 대상외(고철·토사·차량)를 걸러 내므로 지울 수 없고, 지울 이유도 없다(값은 값이다).
DIRS = DR.DIRS

# 도로 쪽 방향 제외(`--skip-dir`)는 **주소별 손보정**이라 여기에 표를 두지 않는다
# ([[hand_writting.py]] `road_side`). 파이프라인에서 낼 때는 `pipeline.finish` 가 그 값을
# 넘겨 주고, 이 파일을 직접 돌릴 때는 사람이 `--skip-dir` 로 준다.

DEFAULT = "대구광역시 달서구 호산동 707-2"


def _rgb(t):
    return "#%02x%02x%02x" % tuple(t[:3])


def sep_lv(level):
    """이격 판정 → (설계서 문구, 문서 색). 「위반」·「심각」은 쓰지 않는다."""
    j = DR.sep_level3(level)
    return j, SEP_DOC.get(j, DIM)


def led_lv(props, parcel=None):
    """대장 정합 → (「일치」/「불일치」/「판정 불가」, 문서 색). 대장에 없는 동도 불일치다."""
    m = DR.led_match(props, parcel)
    return m, MATCH_DOC.get(m, DIM)


def short_of(measured, ledger):
    """판독이 대장보다 **크게 모자란가.**

    A3 는 대장을 **넘는** 분만 보므로(`rules.ledger_verdict`) 모자란 쪽은 전부 「이상없음」이
    된다 — 그것을 그대로 「일치」로 적으면 위성이 대장의 16 % 밖에 못 읽은 필지가 초록으로
    나온다(실측 구미 공단동 282: 대장 26,842 ㎡ · 판독 4,331 ㎡). 초과 쪽과 **같은 눈금**으로
    재서 크게 모자라면 판정을 접는다 — 합계 줄과 동별 줄이 같은 잣대를 써야 한 면에서 두 말이
    나오지 않는다.
    """
    from sitecheck import rules
    short = (ledger or 0) - (measured or 0)
    return bool(ledger and short > rules.LEDGER_PERMIT_M2
                and short / ledger >= rules.LEDGER_EXT_RATIO - 1)


def row_match(m):
    """동별 줄의 정합 — 초과는 규칙대로, **크게 모자라면 판정 불가**."""
    if m and short_of(m.get("measured_m2"), m.get("ledger_m2")):
        return ("판정 불가", DIM)
    return led_lv(m)


def parcel_match(lvw):
    """필지 총량 정합 → ((문구, 색), 부족분 ㎡).

    A3 는 **대장을 넘는 분만** 본다(판정 대상이 증축·미등록이다). 그래서 위성이 대장의 84 %
    를 못 잡아도 규칙은 「이상없음」이고, 그것을 그대로 「일치」로 적으면 「대장대로 다 있다」로
    읽힌다(실측 구미 공단동 282: 대장 26,842 ㎡ · 판독 4,331 ㎡ → 이상없음). 크게 부족하면
    **판정을 보류**하고 왜 그런지 각주로 남긴다 — 규칙(`rules`)은 건드리지 않는다.
    """
    short = (lvw["led_sum"] or 0) - (lvw["mdl_sum"] or 0)
    if short_of(lvw["mdl_sum"], lvw["led_sum"]):
        return ("판정 불가", DIM), short
    return led_lv(lvw["verdict"]), 0.0


def overall(*levels):
    """종합 위험도 — 항목별 등급 중 **가장 나쁜 것**을 3단계로. 설계서: 안전·주의·위험."""
    js = [DR.sep_level3(l) for l in levels if l]
    for j in RISK3:
        if j in js:
            return j, SEP_DOC[j]
    return "판정 불가", DIM


def _rank(level):
    """등급의 나쁜 순서. **모르는 등급에 터지지 않는다** — 규칙이 등급을 늘리면 보고서가
    죽는 것이 아니라 그 등급을 「제일 덜 나쁜 것」으로 두고 넘어가야 한다."""
    return ORDER.index(level) if level in ORDER else len(ORDER)


def worst(fc, *, skip=()):
    w = None
    for f in fc.get("features") or []:
        p = f.get("properties") or {}
        if p.get("dir") in skip:
            continue
        l = p.get("level")
        if l and (w is None or _rank(l) < _rank(w)):
            w = l
    return w


def scene_date(site):
    """영상 촬영일 — 장면 tif 이름이 유일한 출처다(YYYYMMDD_HHMMSS_…)."""
    key = (site.get("scene") or {}).get("key")
    if not key or key not in config.SCENES:
        return "—"
    for t in sorted(config.SCENES[key]["dir"].glob("*.tif")):
        m = re.match(r"(\d{4})(\d{2})(\d{2})_", t.name)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return "—"


# ── 보고서용 그림 — 값은 그대로, 얹는 것만 줄인다 ───────────────────────────
def _neighbors(r):
    """이 창 안의 건물 중 **이 지번이 아닌 것**(외부 건물) — Feature 목록.

    **결과에 담겨 있으므로 그대로 읽는다**(`context.buildings_near`). 이격 결과의 `pair[1]`
    이 가리키는 상대가 바로 이 목록이고, id·방향·거리까지 값에 적혀 있어 지도의 ①②③ 과
    표의 행이 저절로 맞는다.

    아래는 **옛 결과(1.0)만을 위한 되찾기**다. 그때는 이 목록을 저장하지 않아서, 귀속을 가른
    함수를 다시 불러(추론은 캐시를 쓴다) 목록을 만들고 중심점으로 걸러 내야 했다 — 그렇게
    되찾은 목록은 저장된 결과와 어긋날 수 있다(그래서 담는 쪽으로 바꿨다).
    """
    near = ((r.get("context") or {}).get("buildings_near") or {}).get("features")
    if near is not None:
        return list(near)
    site, blds = r["site"], r["layers"]["buildings"]
    src = str(((r.get("provenance") or {}).get("model") or {}).get("building") or "")
    nbs = []
    try:
        if src.startswith("GT"):
            nbs = GT.buildings(site, GT.polygons(site))[1]
        else:
            from sitecheck.steps import s1_building
            tag = (r.get("provenance") or {}).get("tag") or f"sitecheck_{site.get('pnu')}"
            raw, note = s1_building.predict(site, tag=tag, reuse=True)
            nbs = s1_building.attribute(site, raw, note)[1]
    except Exception:                                        # noqa: BLE001
        return []
    # 다시 부른 귀속이 저장된 것과 어긋나면(정합값이 달라졌거나) 이 지번 건물이 외부로
    # 섞여 나온다 — 같은 자리에 두 번 그리지 않게 중심점으로 한 번 걸러 낸다.
    own = DR.own_centroids(blds)
    from shapely.geometry import shape
    return [f for f in nbs
            if (lambda c: (round(c.x, 7), round(c.y, 7)) not in own)(
                shape(f["geometry"]).centroid)]


# 보고서 그림의 목표 픽셀. 종이에서 한 변이 약 125 mm 로 앉으므로 300 dpi ≈ 1,500 px 다.
# 영상 자체는 0.5 m/px 가 천장이라 늘려도 지붕이 선명해지지는 않지만, **얹는 선·배지·글자가
# 그만큼 선명해진다** — 인쇄물에서 흐렸던 것은 그쪽이다(552 px 를 늘려 넣고 있었다).
REPORT_PX = 1600


def _view(site, pad_m=None):
    # 창 여백은 [[draw.py]] 가 정한다(`win_pad` — 기본값과 주소별 예외를 그 한 곳이 안다) —
    # 세 도구가 다른 범위를 보면 같은 물건의 그림을 나란히 놓고 비교할 수 없고, ①②③ 을
    # 가리는 창 판정도 갈린다.
    v = DR.View(site, pad_m=pad_m, target_px=REPORT_PX)
    if not v.ok:
        raise RuntimeError("정사영상 crop 을 만들 수 없다")
    return v


def _save(v, draw, out_png):
    from PIL import Image, ImageDraw
    ov = Image.new("RGBA", v.base.size, (0, 0, 0, 0))
    draw(ImageDraw.Draw(ov), v)
    img = Image.alpha_composite(v.base.convert("RGBA"), ov).convert("RGB")
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_png)
    return Path(out_png)


def img_base(v, out_png):
    """아무것도 얹지 않은 바탕 — 세 그림과 **같은 창**이다. 얹은 것이 무엇을 가렸는지
    따지려면 원본이 옆에 있어야 한다."""
    Path(out_png).parent.mkdir(parents=True, exist_ok=True)
    v.base.save(out_png)
    return Path(out_png)


def img_separation(site, blds, sep, near, out_png, *, skip=(), v=None, force=()):
    """이격거리 그림 — 규칙은 [[draw.py]] 의 `sep_draw` 다(세 도구가 같은 방식으로 그린다).

    `force` 는 **창 밖이어도 번호를 줄 상대**다([[draw.py]] `ext_index`) — 비교분석이 두
    날짜의 그림을 맞추려고 준다. 단일시점은 안 준다(맞출 상대가 없다).
    """
    v = v or _view(site)
    return _save(v, DR.sep_draw(site, blds, near, sep, skip=skip, force=force), out_png)


def img_yard(site, blds, yd, near, out_png, *, v=None):
    """야적물 그림 — `draw.yard_draw` 그대로.

    **라벨을 갈아 끼우지 않는다**(2026-08-23). 여기서 분류 이름과 거리를 다시 붙이고 있었는데,
    지금 라벨은 **구역 코드** 하나이고 그 문구를 정하는 곳은 [[draw.py]] 다 — 두 곳에서 만들면
    데모 시트와 보고서의 같은 구역이 다른 이름으로 불린다.
    """
    v = v or _view(site)
    return _save(v, DR.yard_draw(site, blds, near, yd), out_png)


def img_ledger(site, blds, led, out_png, *, by=None, v=None):
    """대장 대조 그림 — `draw.ledger_draw` 그대로.

    라벨을 여기서 갈아 끼우지 않는다 — 설계서가 「A동 불일치」 꼴을 못 박아 두었고 그
    문구는 [[draw.py]] 가 만든다. 여기서 다시 쓰면 보고서와 다른 두 도구의 그림이 갈린다.
    """
    v = v or _view(site)
    return _save(v, DR.ledger_draw(site, blds, led, by=by), out_png)


# ── 5·6면 — 외부 공공데이터 ─────────────────────────────────────────────────
# 이 두 면은 **영상에서 나오지 않는 값**이다. 특건자료의 「일반사항 › 인근소방서」와
# 「자연재해위험」 절에 대응한다(소형 물건은 현장조사가 없어 그 칸을 아무도 채우지 않는다).
#
# 지금 열린 자료는 둘뿐이다 — 소방청 전국소방서 좌표(15138232) · 화재발생 정보(15044003).
# 나머지 칸은 **지우지 않고** 「받지 못한 값」 표로 남긴다. 지우면 그 항목을 안 본 것과
# 구별되지 않는다. 무엇을 신청해야 열리는지까지 같은 표에 적어 두면, 이 종이가 받는 쪽에는
# 커버리지 고지가 되고 우리에게는 취득 잔여 목록이 된다(등록부는 [[ext.py]] `MISSING`).
def _km(m):
    """거리 문구. 1 km 아래는 m 로 적는다 — 「0.9 km」는 읽는 사람이 다시 곱해야 한다."""
    if m is None:
        return "—"
    return f"{m:,.0f} m" if m < 1000 else f"{m / 1000:,.1f} km"


def _won(k):
    """천원 단위 → 사람이 읽는 금액. 원본(`재산피해소계`)이 천원이다."""
    if not k:
        return "0"
    won = k * 1000
    if won >= 1e8:
        return f"{won / 1e8:,.1f}억 원"
    return f"{won / 1e4:,.0f}만 원"


def _stn_name(name, kind):
    """소방관서 이름을 표에 앉을 길이로 줄인다.

    원본 표기가 고르지 않다 — 「강서소방서_대구-성서-119 안전센터」·「수성소방서-수성-119
    안전센터」처럼 소속 소방서와 지역이 앞에 붙어 온다. 119안전센터는 「센터이름 + 소속」으로
    다시 쓰고, 소방서는 그대로 둔다. **못 알아보는 형식은 원본 그대로 낸다** — 이름을 억지로
    자르면 다른 관서가 되어 버린다.
    """
    if kind != "119안전센터":
        return name
    parts = [x.strip() for x in re.split(r"[-_]", name or "") if x.strip()]
    hit = next((i for i, x in enumerate(parts) if "119" in x), None)
    if not hit or hit < 1:
        return name
    return f"{parts[hit - 1]}119안전센터({parts[0]})"


def _v(level):
    """3단계 판정 → (문구, 색). 이격·야적 표와 같은 어휘·같은 잉크를 쓴다 — 한 문서에서
    같은 색이 다른 뜻이면 색이 정보를 잃는다."""
    return (level, SEP_DOC.get(level, DIM))


def page_fire(ctx, site):
    """5면 — 소방 접근성."""
    fire = (ctx or {}).get("fire") or {}
    meta = fire.get("meta") or {}
    st, cs = fire.get("station"), list(fire.get("centers") or [])
    rows = [["구분", "기관명", "직선거리", "방위", "전화"]]
    if st:
        rows.append(["소방서", _clip(_stn_name(st["name"], "소방서"), 0.34),
                     _km(st["dist_m"]), st["dir"], st["tel"]])
    for i, q in enumerate(cs):
        # 같은 구분이 이어지는 줄은 칸을 비운다(2면 이격 표와 같은 규칙).
        rows.append(["119안전센터" if i == 0 else "",
                     _clip(_stn_name(q["name"], "119안전센터"), 0.34),
                     _km(q["dist_m"]), q["dir"], q["tel"]])
    if not st and not cs:
        rows.append([("자료에서 찾지 못함", DIM), "—", "—", "—", "—"])
    within = fire.get("within") or {}
    dens = [[f"반경 {m // 1000} km 이내", f"{within.get(m, within.get(str(m), 0))}개소"]
            for m in EX.RADII_M]
    dens = [[r[0] for r in dens], [r[1] for r in dens]]
    # 판정은 **가장 가까운 관서**로 낸다(소방서든 안전센터든) — 초기 출동을 안전센터가 하므로
    # 소방서까지의 거리만 보면 실제 도착 여건보다 나쁘게 나온다.
    n0 = fire.get("nearest") or st or (cs[0] if cs else None)
    head = [["최근접 소방관서", "직선거리", "판정"],
            [_clip(_stn_name(n0["name"], n0["type"]), 0.46) if n0 else ("—", DIM),
             _km(n0["dist_m"]) if n0 else "—",
             _v(RL.fire_access_verdict(n0["dist_m"]) if n0 else "판정 불가")]]
    # 등급표 — 그 판정이 **어느 거리에서 갈리는지**. 판정만 있고 눈금이 없으면 왜 그 등급인지
    # 알 수 없고, 눈금만 있고 판정이 없으면 읽는 사람이 매번 대 봐야 한다.
    band = [["직선거리", "판정", "기준 설명"],
            [f"≤ {RL.FIRE_SAFE_KM:.1f} km", _v("안전"), "7분 이내 도착 목표 충족"],
            [f"{RL.FIRE_SAFE_KM:.1f} ~ {RL.FIRE_WARN_KM:.1f} km", _v("주의"), "도착 목표의 2배 이내"],
            [f"> {RL.FIRE_WARN_KM:.1f} km", _v("위험"), "도착 목표 기준 초과"]]
    notes = [
        "직선거리이고 주행거리가 아니다. 「최근접」이며 「관할」이 아니다.",
        f"거리 기준은 {RL.FIRE_BASIS} — 법령이 정한 선이 아니다.",
        f"출처 — 소방청 「전국소방서 좌표현황」 {meta.get('as_of') or '?'} 기준 "
        f"{meta.get('rows') or 0:,}개소.",
    ]
    return {"kind": "fire", "title": "④ 소방 접근성",
            "sub": "가장 가까운 소방관서까지의 직선거리.",
            "blocks": [
                ("sec", "출동 여건"),
                ("tbl", head, {"colw": [0.46, 0.24, 0.30], "head": True}),
                ("sec", "인근 소방관서 현황"),
                ("tbl", rows, {"colw": [0.16, 0.34, 0.15, 0.11, 0.24], "head": True}),
                ("sec", "주변 소방관서 분포"),
                ("tbl", dens, {"colw": [1 / 3] * 3, "head": True}),
                ("sec", "등급 기준(직선거리 판정)"),
                ("tbl", band, {"colw": [0.28, 0.16, 0.56], "head": True}),
            ] + [("note", n) for n in notes]}


def _rtxt(r):
    """전국 순위 문구 — **1위가 가장 센 곳**이다."""
    if r.get("rank") is None or not r.get("pop"):
        return ("—", DIM)
    return f"{r['pop']}지점 중 {r['rank']}위"


def _cval(r):
    """관측값 문구. 일수는 소수 한 자리, 최대값은 천단위 구분."""
    v = r.get("value")
    if v is None:
        return ("관측값 없음", DIM)
    return f"{v:.1f} {r['unit']}" if r["unit"] == "일/년" else f"{v:,.1f} {r['unit']}"


def page_climate(ctx, site):
    """기후 면 — 특건 「자연재해위험 › 기후」 절에 대응한다.

    한 줄에 셋을 나란히 둔다: **관측 최대값 · 발생일 · 전국에서의 위치**. 값만 적으면
    「62 cm 라서 뭐」가 되고, 백분위만 적으면 실제로 얼마였는지가 사라진다.
    """
    cl = (ctx or {}).get("climate")
    if not cl:
        return None
    st, sm, wc = cl["station"], cl["summary"], cl.get("wind_code")
    stn_row = [["관측소", "직선거리", "방위", "관측기간", "관측소 해발고도"],
               [f"{st['name']}({st['stn']})", _km(st["dist_m"]), st["dir"],
                f"{sm['y0']}~{sm['y1']} · {sm['n_years']}년",
                f"{float(st['alt_m']):,.0f} m" if st.get("alt_m") else "—"]]
    ext_rows = [["항목", "관측 최대값", "발생일", "전국 순위", "판정"]]
    for r in cl["rows"]:
        ext_rows.append([r["item"], _cval(r), r.get("date") or "—", _rtxt(r),
                         _v(RL.climate_rank_verdict(r.get("rank"), r.get("pop")))])
    # 등급표 — 그 판정이 **전국 분포의 어디에서 갈리는지**. 법정 기준이 아니라 모집단 안의
    # 자리라는 것은 아래 각주가 말한다.
    band = [["전국 순위", "판정", "기준 설명"],
            [f"상위 {RL.CLIMATE_TOP_RISK:.0%} 이내", _v("위험"),
             "전국 최상위권의 강도 또는 빈도를 보이는 지역"],
            [f"상위 {RL.CLIMATE_TOP_WARN:.0%} 이내", _v("주의"),
             "전국 평균 대비 뚜렷이 높은 수준의 지역"],
            ["그외", _v("안전"), "전국 분포의 중위 이하 수준"]]
    blocks = [("sec", "기준 관측소"),
              ("tbl", stn_row, {"colw": [0.24, 0.16, 0.10, 0.28, 0.22], "head": True}),
              ("sec", f"관측 최대값 ({sm['y0']}~{sm['y1']})"),
              ("tbl", ext_rows, {"colw": [0.24, 0.18, 0.16, 0.24, 0.18], "head": True}),
              ("sec", "등급 기준(전국 순위 판정)"),
              ("tbl", band, {"colw": [0.24, 0.14, 0.62], "head": True})]
    notes = [
        f"가장 가까운 종관기상관측(ASOS) 지점의 값 — 물건 위에서 잰 값이 아니고 "
        f"{_km(st['dist_m'])} 떨어져 있다. 순위는 전국 관측지점 중의 자리로, 1위가 가장 세다.",
        f"폭풍일수는 일최대풍속 {sm['storm_ms']} m/s 이상인 날의 연평균이고(기상청 강풍일수 "
        f"정의), 낙뢰일수는 일기현상에 뇌전이 적힌 날의 연평균. 관측일 300일 미만인 해는 뺐다.",
    ]
    if wc:
        # 대조는 **최대풍속(10분평균 계열)** 과만 한다. 최대순간풍속(돌풍)은 평균시간이 달라
        # 같은 자에 올리면 과대비교가 된다 — 이 한 줄이 없으면 표가 틀린 말을 한다.
        mx = next((r for r in cl["rows"] if r["item"] == "최대풍속"), None)
        gu = next((r for r in cl["rows"] if r["item"] == "최대순간풍속"), None)
        ratio = (mx and mx["value"] and f"{mx['value'] / wc['ms'] * 100:.0f} %") or "—"
        over = mx and mx["value"] and mx["value"] > wc["ms"]
        # 여기는 **법정 기준값과의 대조**라 판정이 해석이 아니라 산술이다.
        wlv = RL.wind_code_verdict(mx and mx["value"], wc["ms"])
        rows = [["구분", "값", "비고", "판정"],
                ["법정 기본풍속", f"{wc['ms']} m/s", f"{wc['matched']} 적용 기준",
                 ("기준값", DIM)],
                ["관측 최대풍속", _cval(mx) if mx else "—",
                 ("기준값 초과 이력 있음" if over else f"기준값의 {ratio} 수준"), _v(wlv)],
                ["관측 최대순간풍속", _cval(gu) if gu else "—",
                 ("돌풍 특성상 평균시간이 상이하여 직접 대조에서 제외", DIM), ("—", DIM)]]
        blocks += [("sec", "법정 기준 대조 — 풍속"),
                   ("tbl", rows, {"colw": [0.24, 0.16, 0.42, 0.18], "head": True})]
        notes.append(f"기본풍속은 {wc['basis']} 의 지역별 값. 평균시간이 다른 "
                     f"최대순간풍속(돌풍)은 대조에서 뺀다 — 10분 평균의 1.5배 안팎이라 "
                     f"같은 자에 올리면 과대비교가 된다.")
    notes.append("전국 순위 판정은 법정 기준이 아니라 모집단 안의 자리 — 그 지역에 그 현상이 "
                 "잦거나 세다는 뜻이고, 이 물건이 그만큼 취약하다는 말은 아니다. "
                 "적설은 법정 기준값을 확보하지 못해 순위만 싣는다.")
    return {"kind": "climate", "title": "⑤ 자연재해 — 기후",
            "sub": "기준 관측소의 관측 최대값과 법정 설계기준.",
            "blocks": blocks + [("note", n) for n in notes]}


def overview_rows(r, lvw, dong, *, skip=(), scene2=None):
    """1면 「개요」 표의 줄들. **비교분석 보고서도 이 함수를 쓴다** — 같은 물건을 설명하는 칸이라
    문구가 갈리면 어느 쪽이 맞는지 알 수 없다. 여기를 고치면 두 문서가 같이 바뀐다.

    `scene2` 를 주면 「사용 영상」 줄이 「1차 / 2차 영상」 두 줄로 갈린다(비교분석).
    """
    site, mdl = r["site"], r["layers"]["buildings"]["features"]
    led, sc = lvw["keep"], (r["site"].get("scene") or {})
    rows = [
        ["소재지", site["address"]],
        ["대지면적", f"{site.get('parcel_m2') or 0:,.0f} ㎡   ·   지번코드 {site.get('pnu')}"],
        ["건축물대장", f"{len(led)}동  ·  건축면적 합계 {lvw['led_sum']:,.0f} ㎡"
                    + (f"  ·  용도 {led[0].get('main_purpose')}" if led and led[0].get("main_purpose") else "")
                    + (f"   (30 ㎡ 미만 부속 {len(lvw['dropped'])}동 제외)"
                       if lvw["dropped"] else "")
                    # 사람이 확인해 뺀 동도 **뺐다고 적는다** — 안 적으면 대장 동수가 값
                    # 파일과 달라 보이고, 그 차이가 어디서 났는지 종이에 흔적이 없다
                    # ([[hand.py]] `ledger_drop` · `site.ledger_drop`).
                    + (f"   (사람이 확인해 뺀 {len(site['ledger_drop'])}동 제외)"
                       if site.get("ledger_drop") else "")],
        ["위성 판독 건물",
         _clip(f"{len(mdl)}동  ·  건축면적 합계 {lvw['mdl_sum']:,.0f} ㎡"
               + (f"   ({_dong_list(mdl, dong)})" if mdl else ""), 0.78)],
    ]
    one = f"위성 정사영상 {sc.get('res_m')} m/px  ·  촬영일 {scene_date(site)}  ·  {sc.get('ko')}"
    rows += ([["사용 영상", one]] if scene2 is None
             else [["1차 영상", one], ["2차 영상", scene2]])
    # **「분석 방법」 줄은 두지 않는다**(사용자 결정, 2026-08-27). 「위성 영상에서 건물
    # 외곽선을 추출해 지적도·대장과 중첩하여 대조」는 **물건마다 달라지지 않는 도구 사양**
    # 이고, 개요는 이 물건의 사실만 싣는 자리다 — 「산출물」 줄을 뺀 것과 같은 이유다.
    #
    # 다만 **도로면 제외는 이 물건에만 해당하는 사실**이라 그 줄에 얹혀 있었으므로, 걸린
    # 물건에서만 자기 줄로 남긴다(그림 밑 각주는 물건마다 달라지지 않게 고정해 두었다 —
    # SEP_NOTES). 지금 산출물에는 걸리는 물건이 없다(`road_side` 는 호산동 707-2 하나).
    if skip:
        rows.append(["이격 제외", f"{' · '.join(skip)}쪽은 도로라 이격 대상에서 제외"])
    # **「산출물」 줄은 두지 않는다**(2026-08-23). 파일 몇 장 몇 개가 나가는지는 이 물건을
    # 설명하는 값이 아니라 도구 사양이고, 물건마다 달라지지도 않는다 — 개요는 이 물건의
    # 사실만 싣는다. 무엇이 나가는지는 README 와 결과 폴더가 말한다.
    return rows


# ── 내용 한 벌 ──────────────────────────────────────────────────────────────
def build_doc(r, imgs, *, near=(), skip=(), ctx=None):
    """페이지 목록. 블록은 ("sec"|"tbl"|"img"|"legend"|"note", …) 다.

    `near` 는 외부 건물 Feature 목록 — ①②③ 이름을 그림과 **같은 순서**로 얻는 데 쓴다.
    """
    site, L = r["site"], r["layers"]
    lvw = _ledger_view(r)
    led, led_sum = lvw["keep"], lvw["led_sum"]
    mdl, mdl_sum = L["buildings"]["features"], lvw["mdl_sum"]
    sc = site.get("scene") or {}
    # 이름은 [[draw.py]] 가 정한다 — 그림과 표가 같은 이름을 써야 「A동」이 지도의 어느
    # 건물인지 되짚을 수 있다.
    # **번호는 외부 건물마다** 하나다([[draw.py]] `ext_names`) — 지도의 「⑤외부」 배지와
    # 표의 번호 칸이 같은 **건물**을 가리킨다. 한 외부 건물을 우리 동 둘이 마주 서면 줄이
    # 둘이고 번호는 같다(A동 표의 ⑤ · B동 표의 ⑤ — 같은 건물을 두 동에서 잰 값이다).
    dong, ext = sep_labels(r, near, skip=skip)
    tally = _tally(L, lvw, dong, ext, skip=skip)

    # 1면 ─ 개요
    p1 = {"kind": "overview", "title": f"위성 분석 제공 정보  —  {site['address']}",
          "sub": "",
          "blocks": []}
    p1["blocks"] += [
        # 설계서 BR-13 상단의 세 칸 — 이 물건을 한 줄로 요약한다.
        # 셈의 내역은 **표 안에** 둔다 — 회색 각주는 물건마다 달라지지 않아야 한다.
        #
        # 가운데 칸은 「탐지 건물」이 아니라 **「탐지 결과」**다(사용자 결정, 2026-08-27) —
        # 적재 구역 수가 1면에 남아야 하는데, 오른쪽 「확인 필요 항목」은 **위험한 줄만** 세는
        # 자리라 15 m 밖이라 「안전」인 구역이 거기서는 0 으로 나온다. 세는 칸과 재는 칸을
        # 갈라 둔다 — 가운데는 **무엇이 얼마나 잡혔나**, 오른쪽은 **그중 무엇을 봐야 하나**.
        ("tbl", [["종합 위험도", "탐지 결과", "확인 필요 항목"],
                 [tally["overall"], f"건물 {len(mdl)}동 · {_yard_count(L['yard'])}",
                  f"{tally['n_check']}건\n이격거리 {tally['n_sep']} · 대장 정합 {tally['n_led']} · "
                  f"야외 적재물 {tally['n_yard']}"]],
         {"colw": [1 / 3] * 3, "head": True}),
        ("sec", "물건 개요"),
        ("tbl", overview_rows(r, lvw, dong, skip=skip),
         {"colw": [0.22, 0.78], "label": True}),
        ("sec", "분석 절차"),
        ("tbl", [["① 주소 입력", "② 위성영상 및 공공자료 조회", "③ 항목별 분석",
                  "④ 이미지 · 데이터 산출"]],
         {"colw": [0.25] * 4}),
        ("sec", "판정 기준"),
        # 확인 필요 열이 넓다 — 미등록·증축에서 그 열만 두 칸으로 쪼개진다(_criteria).
        ("tbl", _criteria(), {"colw": [0.24, 0.32, 0.21, 0.23], "head": True}),
        # 「적재물 위험등급 ↔ 해당 품목」 표는 싣지 않는다 — 3면이 등급을 적지 않으므로
        # 그 기준만 1면에 남으면 종이에 없는 값의 기준이 된다(2026-08-23).
        ("note", "미등록·증축은 초과율과 초과면적을 함께 본다 — 한쪽이라도 「일치」 칸에 들면 "
                 "측정오차와 구분되지 않는다."),
        ("sec", "본 물건 분석 결과"),
    ]
    # 판정어는 항목마다 다르다(설계서 3면) — 이격은 안전·주의·위험, 대장은 일치·불일치,
    # 야적물은 「현장 확인 필요」 하나다. 한 열에 섞어 쓰지 않고 그 항목의 말로 적는다.
    rows = [["항목", "분석 내용", "판정"],
            ["건물 이격거리", _sep_line(L["separation"], skip,
                                       DR.sep_hidden(L["separation"], ext, skip=skip)),
             sep_lv(_sep_worst(L["separation"], skip=skip))],
            ["야외 적재물", _yard_line(L["yard"]), tally["yard"]],
            ["대장 정합(미등록·증축)", _led_line(lvw), parcel_match(lvw)[0]]]
    p1["blocks"] += [
        ("tbl", rows, {"colw": [0.22, 0.58, 0.20], "head": True}),
        ("note", "모든 판정은 이 영상 촬영 시점 기준이다."),
    ]

    # 2면 ─ 이격거리 — **대상 동마다 한 표**(`sep_dong_rows`).
    #   방위는 보는 쪽에 따라 뒤집히므로(A 의 남 = B 의 북) 「A동 표」라고 못박아야 그 줄이
    #   어느 건물에서 잰 값인지 분명하다. 필지 안 쌍은 두 표에 한 줄씩 서고 번호 대신 상대
    #   동 이름을 적는다 — 필지 밖은 줄마다 번호를 받는다.
    res = sc.get("res_m") or 0.5
    by_dong = sep_dong_rows(L["separation"], dong, ext, skip=skip)
    names = [n for n in dong_order(dong) if n in by_dong] or list(by_dong)
    sep_notes = SEP_NOTES
    # 한 면(표만 있는 면)에 들어갈 만큼으로 줄인다 — 넘치면 「외 N」으로 알린다.
    caps = _rows_fit(BODY_ROOM - _note_cost(sep_notes),
                     *[max(1, len(by_dong[n])) for n in names]) if names else []
    tables = []
    for name, cap in zip(names, caps):
        rows = [list(SEP_HEAD)]
        for q in by_dong[name][:cap]:
            # 이격 번호는 **글머리 숫자**(①)이고 색은 **그 줄의 판정색**이다(사용자 결정,
            # 2026-08-27) — 지도의 거리 배지가 같은 모양·같은 색으로 달고 있어
            # (`draw._meas_text` 의 「① 2.5 m」) 표와 지도를 번호 하나로 오간다.
            lvl = sep_lv(q["level"])
            rows.append([(q["id"], lvl[1]), q["no"], q["dir"],
                         DR.dist_text(q["dist"], res_m=res), lvl])
        if not by_dong[name]:
            # **「판정 불가」라고 적지 않는다** — 둘레에 상대가 없는 것은 못 잰 것이 아니라
            # 이격을 셀 상대가 없다는 결과다. 판정 칸에는 판정어만 적는다(`WORDS`).
            rows.append(["—", "—", "—", "둘레에 마주 선 건물이 없음",
                         ("안전", SEP_DOC["안전"])])
        elif len(by_dong[name]) > cap:
            rows.append(["…", "", "", f"외 {len(by_dong[name]) - cap}줄", ""])
        tables.append((f"{name} 이격거리 측정 결과", rows))
    if not tables:
        tables = [("이격거리 측정 결과",
                   [list(SEP_HEAD),
                    ["—", "—", "—", "판독된 건물이 없음", ("안전", SEP_DOC["안전"])]])]

    sep_pages = _sep_pages(str(imgs["sep"]), _sep_legend(L["separation"], skip),
                           tables, sep_notes)

    # 3면 ─ 야적물
    fs = list(L["yard"].get("features") or [])
    yd_notes = YARD_NOTES
    yd_h, yd_n = _fig_page(len(fs) + 1, yd_notes)
    # **「종류」·「위험등급」 칸을 싣지 않는다**(2026-08-23). 둘 다 겉모습으로 가른 값이라
    # (`s2_yard` 는 영상만 본다) 종이에 등급으로 적히면 확정한 것처럼 읽힌다. 이 면이 말하는
    # 것은 **어디에 쌓여 있고 건물에서 몇 m 인가**이고, 그것이 판정을 내는 값이다. 구역은
    # 지도의 배지와 같은 **구역 코드**로 되짚는다 — 건물을 「A동」으로 부르는 것과 같다.
    rows = [["구역", "인접 건물과의 거리", "판정"]]
    for f in fs[:yd_n]:
        p = f["properties"]
        rows.append([p["yard_id"],
                     "—" if p.get("dist_to_building_m") is None else f"{p['dist_to_building_m']:.1f} m",
                     _zone_lv(p.get("level"))])
    if not fs:
        # **「판정 불가」라고 적지 않는다**(2026-08-23). 돌려서 아무것도 안 나온 것은 못 잰
        # 것이 아니라 **없다는 결과**다 — 그것을 「판정 불가」로 적으면 판독을 아예 건너뛴
        # 물건과 같은 말이 된다(그 구분은 `_yard_lv` 가 레이어의 note 로 가린다).
        # 판정 칸에는 **판정어만** 적는다(`WORDS`) — 「야적물 없음」은 판정 기준 표에 없는
        # 말이라 그 칸이 무엇을 재는 칸인지 흐려진다. 없다는 사실은 가운데 칸이 이미 적는다.
        rows.append(["—", "탐지된 적재 구역 없음", ("안전", SEP_DOC["안전"])])
    elif len(fs) > yd_n:
        rows.append(["…", f"외 {len(fs) - yd_n}곳", ""])
    p3 = {"kind": "yard", "title": "② 야외 적재물",
          "sub": "건물 밖 마당에 쌓아 둔 가연물. 인접 건물까지의 거리.",
          "blocks": [
              ("img", str(imgs["yard"]), {"h": yd_h}),
              ("legend", DR.yard_legend(L["yard"])),
              ("sec", "적재 구역 탐지 결과"),
              ("tbl", rows, {"colw": [0.24, 0.38, 0.38], "head": True}),
          ] + [("note", n) for n in yd_notes]}

    # 4면 ─ 미등록·증축
    (t, c), short = parcel_match(lvw)
    diff = lvw["mdl_sum"] - lvw["led_sum"]
    pct = (diff / lvw["led_sum"] * 100) if lvw["led_sum"] else 0.0
    # 이 물건에만 해당하는 값(합계·판정)은 **각주가 아니라 표의 맨 아랫줄**에 넣는다 —
    # 합계는 표에 속한 값이고, 그래야 각주가 물건마다 늘었다 줄었다 하지 않는다.
    led_rows = _ledger_rows(lvw, dong)
    led_h, led_n = _fig_page((len(led_rows) - 1) * 1.62 + 2, LED_NOTES)
    led_n = max(1, int(led_n / 1.62) - 1)
    if len(led_rows) - 1 > led_n:
        cut = len(led_rows) - 1 - led_n
        led_rows = led_rows[:led_n + 1] + [["…", f"외 {cut}동", "", "", "", "", ""]]
    led_rows.append([("합계", INK),
                     (f"대장 {len(lvw['keep'])}동 / 판독 {lvw['n_mdl']}동", INK),
                     "", (f"{lvw['led_sum']:,.0f} ㎡", INK),
                     (f"{lvw['mdl_sum']:,.0f} ㎡", INK),
                     (f"{diff:+,.0f} ㎡ ({pct:+.0f} %)", INK), (t, c)])

    p4 = {"kind": "led", "title": "③ 미등록·증축 건물",
          "sub": "대장에 적힌 동별 면적과 위성에서 판독한 면적의 대조.",
          "blocks": [("img", str(imgs["led"]), {"h": led_h}),
                     ("legend", _led_legend(L["buildings"], L["ledger"], lvw["by_bld"])),
                     ("sec", "대장 ↔ 위성 건축면적 비교"
                      + ("  (동 대응은 면적 기준 추정)" if lvw["by_area"] else "")),
                     ("tbl", led_rows, {"colw": LED_COLW, "head": True}),
                     ] + [("note", n) for n in LED_NOTES]}
    doc = [x for x in [p1, *sep_pages, p3, p4, page_fire(ctx, site),
                       page_climate(ctx, site)] if x]
    # **회색 글자를 여기서 한 번 걷어 낸다**(`SHOW_NOTES` · `SHOW_SUB`). 면을 짜는 곳마다
    # 조건을 넣으면 한 군데를 빼먹어 한 면만 각주가 남는다 — 자리 계산은 `_note_cost` 가
    # 이미 0 으로 셈했으므로 여기서 빼면 판이 맞는다.
    for pg in doc:
        if not SHOW_NOTES:
            pg["blocks"] = [b for b in pg["blocks"] if b[0] != "note"]
        if not SHOW_SUB:
            pg["sub"] = ""
    return doc


def _criteria():
    """항목별 라벨과 그 라벨이 붙는 수치 구간. **임계값은 rules 에서 읽는다** — 보고서에 숫자를
    베껴 두면 규칙이 바뀔 때 조용히 갈린다.

    미등록·증축만 조건이 둘이다(초과율 · 초과면적). 표를 따로 세워 행·열을 뒤집으면 다른 세
    항목과 읽는 방향이 갈리므로 **마지막 줄만 등급 안에서 칸을 다시 쪼갠다** — 셀을 리스트로
    주면 그 열 폭을 나눠 쓴다.

    쪼갠 칸은 **각각이 완결된 조건**이어야 한다. 규칙의 판정 순서에 기대어 「초과면적 ≥ 85 ㎡」
    라고만 적으면, 초과율이 작아 이상 없음인 건물도 그 칸에 걸리는 것처럼 읽힌다(대장
    10,000 ㎡ · +200 ㎡ 가 그렇다). 그래서 「및 · 또는」을 글자로 적는다 — 순서를 외우지
    않아도 칸 하나만 보고 맞는다.
    """
    from sitecheck import rules
    e = rules.SEP_MEASURE_ERR_M
    red, org, grn = SEP_DOC["위험"], SEP_DOC["주의"], SEP_DOC["안전"]
    # 판정어가 항목마다 다르므로(이격 = 안전·주의·위험 / 대장 = 일치·불일치) 머리행에 둘을
    # 같이 적는다. 표를 둘로 쪼개면 같은 잣대를 두 번 설명하게 된다.
    head = ["항목", ("위험 · 불일치", red), ("주의", org), ("안전 · 일치", grn)]
    rows = [head]
    for name, lim in (("이격거리(1층 건물)", rules.SEP_BLD_1F_M),
                      ("이격거리(2층 이상 건물)", rules.SEP_BLD_2F_M)):
        rows.append([name,
                     (f"< {lim:.0f} m", red),
                     (f"{lim:.0f} ~ {lim + e:.1f} m", org),
                     (f"≥ {lim + e:.1f} m", grn)])
    # 야적물의 판정어는 「현장 확인 필요」 하나다(설계서 3면) — 위험 칸이 그 칸이다.
    rows.append(["야외 적재물(건물과의 거리)",
                 (f"< {rules.YARD_SEP_LEGAL_M:.0f} m\n(현장 확인 필요)", red),
                 (f"{rules.YARD_SEP_LEGAL_M:.0f} ~ {rules.YARD_SEP_KFS_M:.0f} m", org),
                 (f"≥ {rules.YARD_SEP_KFS_M:.0f} m", grn)])
    lo, hi = rules.LEDGER_EXT_MIN_M2, rules.LEDGER_PERMIT_M2
    pct = (rules.LEDGER_EXT_RATIO - 1) * 100
    gate = f"초과율 ≥ {pct:.0f} %\n및\n"
    rows.append(["미등록·증축(면적 대조)",
                 [(f"{gate}초과면적 ≥ {hi:.0f} ㎡", red),
                  ("대장 미등재\n건물 탐지", red)],
                 (f"{gate}초과면적 {lo:.0f} ~ {hi:.0f} ㎡", org),
                 [(f"초과율\n< {pct:.0f} %", grn),
                  (f"또는 초과면적\n< {lo:.0f} ㎡", grn)]])
    return rows


def _yard_skipped(fc):
    """적재물 판독을 아예 돌리지 않았나 — 레이어의 `note` 에만 남아 있는 사실이다.

    **돌렸다는 흔적을 찾는 쪽으로 묻는다.** 건너뛴 문구를 열거하면 문구가 하나 늘 때마다
    「돌리지 않았는데 이상 없음」이 조용히 나온다(실측: `--only sep` 이 남긴 「생성되지
    않음」이 그랬다). 못 찾으면 판정을 접는 쪽이 안전하다.
    """
    note = str(fc.get("note") or "")
    return not (("검출" in note) or ("VLM" in note and "건너" not in note))


def _yard_lv(fc):
    """야적물 판정 — **이격과 같은 안전 · 주의 · 위험**(사용자 결정, 2026-08-27).

    1면 「판정 기준」 표가 이미 거리로 셋을 가른다 — 6 m 미만 위험 · 6~15 m 주의 · 15 m
    이상 안전. 한때 탐지된 구역을 거리와 무관하게 전부 「현장 확인 필요」로 접었는데, 그러면
    기준표가 셋으로 갈라 놓은 것을 결과 칸이 하나로 뭉개 **멀리 떨어진 적재물과 벽에 붙은
    적재물이 종이에서 같은 말**이 된다. 「현장 확인 필요」는 기준표의 6 m 칸에 그 뜻을 적는
    말로만 남는다.

    **한 구역의 등급이 아니라 레이어를 받는다** — 구역이 0 곳일 때 「판정 불가」와 「안전」이
    갈리기 때문이다. 판독을 건너뛴 것(`--no-yard`)은 모르는 것이고, 돌려서 아무것도 안 나온
    것은 안전이다. 그 차이는 레이어의 `note` 에만 남아 있다.
    """
    fs = fc.get("features") or []
    if not fs:
        return (("판정 불가", DIM) if _yard_skipped(fc) else ("안전", SEP_DOC["안전"]))
    worst = min(fs, key=lambda f: RL.LEVEL_ORDER.get(f["properties"].get("level"), 99))
    return sep_lv(worst["properties"].get("level"))


def _zone_lv(level):
    """적재 구역 한 곳의 판정 — 3면 표의 마지막 칸. **이격과 같은 말·같은 색**이다.

    3단계 옮기는 표는 [[draw.py]] 의 `sep_level3` 하나뿐이므로 `sep_lv` 를 그대로 부른다.
    여기서 등급 목록을 따로 적으면 같은 「참고」가 항목 판정과 종합 위험도에서 다른 말이 되어
    근거 없는 종합 등급이 나온다.
    """
    return sep_lv(level)


def _sep_worst(fc, *, skip=()):
    """이격 최고 판정 — **표에 실린 쌍**에서만 낸다. 눈금 이하로 붙은 우리 동 쌍은 뺀다."""
    w = None
    for f in DR.sep_pairs(fc, skip=skip):
        l = f["properties"].get("level")
        if l and (w is None or _rank(l) < _rank(w)):
            w = l
    return w


def _sep_ext_rows(fc, dong, ext, *, skip=(), keep=()):
    """**필지 밖 줄** — 대지경계선 **구간마다 한 줄**([[steps/s3_separation]] 의 경계선 걷기).

    번호 순(부지 북쪽부터 시계방향)이라 위에서 아래로 읽으면 **부지를 한 바퀴 도는** 순서가
    된다 — 「이 땅 둘레에 무엇이 얼마나 붙어 있나」가 이 표 하나로 읽힌다.

    **상대 id 로 접지 않는다.** 한 상대가 떨어진 두 구간을 이길 수 있어서(L 자로 감싼 필지)
    접으면 구간 하나가 사라진다. 번호는 **건물마다** 붙으므로([[draw.py]] `ext_names`) 같은
    상대의 두 줄은 **번호가 같고** 방위·거리가 다르다 — 번호는 그 줄의 이름이 아니라 그 줄이
    가리키는 **건물의 이름**이다. `ext` 가 그 이름표다(bld_id → 「①」).

    `run_id` 가 없는 옛 결과는 그때 규칙대로 상대마다 한 줄로 접는다 — 세는 방식이 다른
    결과를 한 표에 섞지 않는다.
    """
    # 번호를 못 붙일 만큼 창 밖인 「안전」 상대는 **재지 않은 것으로 한다** — 지도와 같은
    # 함수로 같은 줄을 뺀다([[draw.py]] `sep_hidden`).
    #
    # `keep` 은 **그래도 남길 상대**다(비교분석이 준다 · [[compare.py]] `sep_change_rows`).
    # 두 날짜 중 한쪽에서만 창에 걸려 빠지면 비교 표에서 그 줄의 짝이 「—」가 되고 **없던
    # 「변화 확인」이 생긴다**(실측 신당동 1187-2 N0028: 1차 18.3 m · 2차 17.9 m 로 측정오차
    # 안인데 1차만 빠져 변화로 인쇄됐다 — 1차에서 그 건물이 창 오른쪽 끝과 0.16 m 겹쳐
    # 배지를 못 놓았다). 남긴 줄은 그 날짜에 번호가 없으므로 `id` 가 「—」로 오고, 표는
    # 거리·판정만 적는다 — **그 날짜 지도에 없는 번호를 지어내지 않는다.**
    hide = DR.sep_hidden(fc, ext, skip=skip) - set(keep or ())
    runs, best = [], {}
    for f in DR.sep_pairs(fc, skip=skip):
        p = f["properties"]
        pr = p.get("pair") or []
        if len(pr) < 2 or p.get("same_parcel") or pr[1] in hide:
            continue
        if p.get("run_id") is not None:
            runs.append(p)
        else:
            cur = best.get(pr[1])
            if cur is None or p["dist_m"] < cur["dist_m"]:
                best[pr[1]] = p
    order = {n: i for i, n in enumerate(ext.values())}
    rows = [{"no": ext.get(p["pair"][1]) or "—", "bid": p["pair"][1],
             "key": DR.sep_key(p),
             "dong": dong.get(p["pair"][0], p["pair"][0]),
             "dir": p.get("dir8") or p.get("dir") or "—",
             "dist": p.get("dist_m"), "front": p.get("front_m"),
             "arc": p.get("arc_m"), "level": p.get("level")}
            for p in runs + list(best.values())]
    # **둘레 위 자리가 정렬의 정본이다.** 번호로 정렬하면 지도 창 밖이라 번호를 못 받은 줄이
    # 맨 아래로 밀려 시계방향이 끊긴다(실측 호산동 703-8: 남쪽 40 m 두 줄이 표 끝에 갔다).
    #
    # 번호도 같은 자리에서 나오므로(`draw.sep_arc_order`) 자리로 정렬하면 번호 칸도 저절로
    # 순서가 맞는다 — 한 건물이 두 자리를 마주할 때만 같은 번호가 두 줄에 나온다.
    # 자리를 모르는 줄(옛 결과)은 그때 규칙대로 번호 순으로 뒤에 붙인다.
    # 자리가 같은 줄이 여럿이면(손으로 더한 줄은 「그 상대에게 가장 가까운 경계선 위 자리」라
    # 모서리를 낀 상대 셋이 같은 값을 가질 수 있다) **번호 순**으로 가른다 — 번호는 그림과
    # 같은 곳에서 방위각 순으로 나오므로(`draw.ext_index`) 그래야 표도 시계방향이 된다.
    rows.sort(key=lambda q: (0, q["arc"], order.get(q["no"], 999)) if q["arc"] is not None
              else (1, order.get(q["no"], 999), q["dist"] or 0.0))
    return rows


def _sep_own_rows(fc, dong, *, skip=()):
    """**필지 안 동끼리 표** — 한 쌍에 한 줄(A↔B 를 두 번 적지 않는다)."""
    best = {}
    for f in DR.sep_pairs(fc, skip=skip):
        p = f["properties"]
        pr = p.get("pair") or []
        if len(pr) < 2 or not p.get("same_parcel"):
            continue
        k = tuple(sorted(pr[:2]))
        cur = best.get(k)
        if cur is None or p["dist_m"] < cur["dist_m"]:
            best[k] = p
    seat = {n: i for i, n in enumerate(dong.values())}
    rows = [{"a": dong.get(p["pair"][0], p["pair"][0]),
             "b": dong.get(p["pair"][1], p["pair"][1]),
             "dir": p.get("dir8") or p.get("dir") or "—",
             "dist": p.get("dist_m"), "level": p.get("level")}
            for p in best.values()]
    rows.sort(key=lambda q: (seat.get(q["a"], 999), q["dist"] or 0))
    return rows


def _sep_lot_rows(fc, dong, *, skip=()):
    """상대 건물이 아예 없을 때의 보조 판정(대지경계선까지) — 있으면 외부 표 뒤에 붙인다."""
    return [{"no": "—", "bid": None, "dong": dong.get(p["bld_id"], p.get("bld_id") or "—"),
             "key": DR.sep_key(p),
             "dir": "—", "dist": p.get("dist_m"), "level": p.get("level"),
             "lot": True}
            for p in (f["properties"] for f in DR.sep_pairs(fc, skip=skip))
            if p.get("kind") == "lot_line"]


def sep_labels(r, near, *, skip=(), force=()):
    """이 물건의 이름표 한 벌 — `(동 이름, 외부 건물 번호)`.

    둘 다 **건물마다 하나**다 — `{bld_id: "A동"}` 과 `{bld_id: "①"}`. 한 건물이 두 이름을
    가질 수 없다는 것이 이 표의 뜻이고, 그래서 지도의 배지도 「A동」·「⑤외부」 하나다.

    **한 곳에서만 나온다.** 그림([[draw.py]] `sep_draw`) · 표(이 파일) · 손판 고치기
    ([[refit.py]]) 가 각자 세면 같은 건물이 종이마다 다른 번호를 단다.
    """
    site, L = r["site"], r["layers"]
    ext = DR.ext_names(near, L["buildings"], force=force,
                       only=DR.sep_ext_ids(L["separation"], L["buildings"], skip=skip),
                       window=DR.label_box(site), site=site,
                       order=DR.sep_arc_order(L["separation"], skip=skip))
    return DR.dong_names(L["buildings"]), ext


# 동 이름 차례는 [[draw.py]] 가 정한다 — 번호를 매기는 차례(`sep_ids`)와 표를 놓는 차례가
# 같아야 하는데, 둘이 다른 파일에서 정렬하면 조용히 갈린다.
dong_order = DR.dong_order


def sep_dong_rows(fc, dong, ext, *, skip=(), keep=()):
    """{동 이름: [줄, …]} — **대상 동마다 한 표**(「■ A동 이격거리 측정 결과」).

    한 줄은 `{"id", "no", "dir", "dist", "level", "kind"}` 이다. `id` 는 **그 측정선의 고유
    번호**([[draw.py]] `sep_ids`) — 지도의 거리 배지와 1:1 이고, 필지 안 쌍은 두 표에 한 줄씩
    서지만 잰 것이 하나라 **번호도 하나**다. `no` 는 그 줄이 가리키는 **상대**로, 필지 안
    상대는 번호 대신 **상대 동 이름**을 담고(「B동」) 상대 건물이 아예 없어 대지경계선까지
    잰 보조 판정은 「대지경계선」을 담는다. `kind` 는 `ext` · `lot` · `own` 셋이다 — 비교분석이
    두 날짜의 줄을 짝지을 때 **번호가 아니라** 이것과 방위로 맞춘다([[compare.py]]
    `sep_change_rows`). 번호는 둘레를 도는 차례라 한 날짜에 이웃이 하나 빠지면 뒤가 다 밀린다.

    **표를 동으로 가르는 까닭은 방위가 보는 쪽에 따라 뒤집히기 때문이다**(A 의 남 = B 의 북).
    「A동 표」라고 못박아야 그 줄의 방위가 어느 건물에서 본 것인지 분명하다. 그래서 필지 안
    쌍은 접지 않고 두 표에 한 줄씩 선다 — 접으면 한쪽 방위가 거짓이 된다.
    """
    # **번호는 `keep` 을 보지 않는다** — 번호를 주는 잣대는 그 날짜 지도에 배지를 놓을 수
    # 있느냐 하나이고, 살려 둔 줄은 그 지도에 배지가 없다. 그래서 `id` 가 「—」로 온다.
    hide = DR.sep_hidden(fc, ext, skip=skip)
    ids = DR.sep_ids(fc, dong, skip=skip, hide=hide, ext=ext)
    out = {name: [] for name in dong.values()}
    for q in (_sep_ext_rows(fc, dong, ext, skip=skip, keep=keep)
              + _sep_lot_rows(fc, dong, skip=skip)):
        out.setdefault(q["dong"], []).append(
            {"id": ids.get(q["key"], "—"),
             "no": "대지경계선" if q.get("lot") else q["no"], "dir": q["dir"],
             "dist": q["dist"], "level": q["level"],
             "kind": "lot" if q.get("lot") else "ext"})
    for f in DR.sep_pairs(fc, skip=skip):
        p = f["properties"]
        pr = p.get("pair") or []
        if len(pr) < 2 or not p.get("same_parcel"):
            continue
        me = dong.get(pr[0])
        if me is None:
            continue
        out.setdefault(me, []).append(
            {"id": ids.get(DR.sep_key(p), "—"),
             "no": dong.get(pr[1], pr[1]), "dir": p.get("dir8") or p.get("dir") or "—",
             "dist": p.get("dist_m"), "level": p.get("level"), "kind": "own"})
    return out


def _tally(L, lvw, dong, ext, *, skip=()):
    """설계서 BR-13 상단 세 칸 — 종합 위험도 · 확인 필요 항목 수.

    「확인 필요 항목 = 이격 위험 + 대장 불일치 + 야적물」이 설계서의 셈이다. **뒤 면의 표에서
    셀 수 있는 것만 센다** — 이격은 2면 표의 「위험」 줄 수, 대장은 4면 표의 「불일치」 동 수,
    야적물은 3면 표의 「현장 확인 필요」 **구역 수**다.

    야적물을 **개소로 센다**(2026-08-26). 한때 「항목 하나」로 세었는데(구역이 몇이든 1),
    그러면 3면 표에 세 줄이 「현장 확인 필요」인 물건의 1면이 「야외 적재물 1」로 나가 종이
    안에서 앞뒤가 맞지 않았다 — 셋 다 표에서 세는 수여야 읽는 사람이 되짚을 수 있다.
    """
    # 이격은 **줄 수**로 센다 — 2면 표가 줄마다 한 줄이므로 표에서 세면 같은 수가 된다.
    # 필지 안 쌍은 두 표에 한 줄씩 서지만 **한 쌍은 하나로** 센다(`_sep_own_rows` 가 접는다).
    n_sep = sum(1 for q in (_sep_ext_rows(L["separation"], dong, ext, skip=skip)
                            + _sep_lot_rows(L["separation"], dong, skip=skip)
                            + _sep_own_rows(L["separation"], dong, skip=skip))
                if DR.sep_level3(q["level"]) == "위험")
    # 4면 표와 **같은 대응**을 센다 — 추정 대응을 세웠으면 그것으로(`lvw["by_bld"]`).
    by = lvw["by_bld"]
    par = DR.led_parcel(L["ledger"])
    n_led = sum(1 for f in (L["buildings"].get("features") or [])
                if DR.led_match(by.get(f["properties"].get("bld_id")), par) == "불일치")
    yard = _yard_lv(L["yard"])
    # 야적도 **이격과 같은 잣대로 「위험」 줄만** 센다(2026-08-27) — 한때 탐지된 구역을 전부
    # 세었는데, 그러면 15 m 밖에 있어 「안전」으로 적힌 구역이 1면의 「확인 필요 항목」에
    # 들어가 한 종이가 두 말을 했다.
    n_yard = sum(1 for f in (L["yard"].get("features") or [])
                 if _zone_lv(f["properties"].get("level"))[0] == "위험")
    return {"n_sep": n_sep, "n_led": n_led, "n_yard": n_yard,
            "n_check": n_sep + n_led + n_yard, "yard": yard,
            "overall": overall(_sep_worst(L["separation"], skip=skip), worst(L["yard"]),
                               lvw["verdict"]["level"]
                               if parcel_match(lvw)[1] == 0 else "정보없음")}


def _sep_legend(fc, skip=()):
    """그림에 **실제로 그린 것만**. 이름은 [[draw.py]] 가 이미 설계서 3단계로 낸다 —
    여기서 한 번 더 옮기면 「위험」을 다시 표에서 찾다 「판단 보류」가 된다(실측 2026-08-20).
    """
    return DR.sep_legend(fc, skip=skip)


def _led_legend(blds, led, by=None):
    return DR.ledger_legend(blds, led, by)


def _pair_by_area(keep, mdl):
    """등록 기하가 없을 때의 **면적 추정 대응** — 대장 동마다 판독 동 묶음 하나.

    대장에는 위치가 없어 어느 판독 건물이 어느 동인지 알 길이 없다([[steps/s4_ledger]]).
    그렇다고 표를 비워 두면 대조하러 만든 면에 대조가 없다 — 「대장 591·515 ㎡」만 남고
    위성이 읽은 값이 한 칸도 안 들어간다. 그래서 **면적이 가장 잘 맞는 대응을 하나 세우고,
    그것이 추정임을 표에 적는다.**

    **1:1 로 맞추면 안 된다.** 모델은 큰 공장 하나를 여러 조각으로 내므로 남는 조각이 죄다
    「미등록」이 된다 — s4_ledger 가 동별 판정을 접은 바로 그 이유(「15조각」)다. 그래서 한
    대장 동에 **여러 판독 동을 묶는다**:

        ① 큰 것부터 1:1 로 씨를 놓는다 — 주동은 주동과 짝이 된다
        ② 남은 판독 동은 **아직 모자란 묶음**에 넣는다. 단 넣어도 그 묶음이 「일치」로
           남을 때만 — 어디에도 못 들어가면 그것이 진짜 「대장에 없는 동」이다
        ③ 짝을 못 받은 대장 동은 「위성 미검출」

    ②의 조건이 이 방법의 안전장치다. 조각은 모자란 자리를 메우고 들어가고, 정말 여분인
    건물만 밖에 남는다 — 조각 수만큼 미등록이 찍히지 않는다.

    **한쪽으로만 단정할 수 있다.** 이 대응은 면적 차이를 가장 작게 만드는 쪽이므로, 여기서도
    어긋나면 **어떤 대응을 가정하든 어긋난다**. 반대로 맞는다고 해서 이 대응이 실제라는 뜻은
    아니다 — 맞는 대응이 하나 있다는 뜻이다. 정본은 맨 아랫줄의 필지 총량이다.
    """
    from sitecheck import rules

    def m2(f):
        return f["properties"].get("arch_area_m2") or 0

    tgt = [(b, b.get("arch_area_m2") or 0) for b in keep]        # `keep` 은 면적 큰 순
    src = sorted(mdl, key=lambda f: -m2(f))
    groups = [[src[i]] if i < len(src) else [] for i in range(len(tgt))]
    extra = []
    for f in src[len(tgt):]:
        best, gap = None, None
        for i, (_b, t) in enumerate(tgt):
            if not groups[i]:
                continue
            tot = sum(m2(x) for x in groups[i]) + m2(f)
            if rules.ledger_verdict(tot, t)["level"] not in ("이상없음", "기록"):
                continue                                        # 넣으면 묶음이 깨진다
            d = abs(t - tot)
            if gap is None or d < gap:
                best, gap = i, d
        if best is None:
            extra.append(f)
        else:
            groups[best].append(f)
    return tgt, groups, extra


def _ledger_view(r):
    """보고서용 대장 대조 — **30 ㎡ 미만 부속건물은 뺀다.**

    위성은 경비실·캐노피 같은 작은 부속을 따로 잡지 않는다(그 선이 rules.LEDGER_MIN_BLD_M2
    다). 대장 2동 · 실측 1동으로 적으면 한 동이 누락된 것처럼 읽히므로 표에서 빼고, 뺐다는
    사실을 각주에 남긴다. **판정은 규칙 함수에 다시 묻는다**(`s4_ledger.parcel_verdict`) —
    보고서가 규칙을 새로 쓰면 파이프라인과 갈린다.
    """
    from sitecheck import rules
    from sitecheck.steps import s4_ledger
    site, L = r["site"], r["layers"]
    keep, dropped = [], []
    for b in site.get("ledger") or []:
        (keep if (b.get("arch_area_m2") or 0) >= rules.LEDGER_MIN_BLD_M2
         else dropped).append(b)
    keep.sort(key=lambda b: -(b.get("arch_area_m2") or 0))
    led_sum = sum(b.get("arch_area_m2") or 0 for b in keep)
    mdl = list(L["buildings"]["features"])
    mdl_sum = sum(f["properties"].get("arch_area_m2") or 0 for f in mdl)
    # **짝은 `keep` 의 줄마다 하나씩 담는다 — 대장 동 이름으로 담지 않는다.**
    # 대장에 동명이 없는 물건이 있고(표에 「(동명없음)」으로 나온다), 그때 이름을 열쇠로
    # 쓰면 그런 동이 전부 `None` 한 칸에 겹쳐 **앞엣것이 조용히 덮인다.** 실측 구미 공단동
    # 293-15: 대장 두 동이 다 동명 없음이라 4,935 ㎡ 줄과 398 ㎡ 줄이 같은 짝(398↔338)을
    # 들었고, 그래서 표의 「판독 면적」이 두 줄 다 338 ㎡ 로 굳고(값이 고정된 것처럼 보인다)
    # 판독 동 칸도 둘 다 「B동」이 되었으며, **-93 % 인 줄이 「일치」로 찍혔다.**
    # `keep` 의 자리(index)는 늘 하나뿐이므로 겹칠 수 없다 — `_pair_by_area` 도 `keep` 과
    # 같은 차례로 묶음을 돌려준다.
    named, extra = {}, []
    for f in L["ledger"].get("features") or []:
        p = f["properties"]
        if p.get("scope") != "building":
            continue
        if p.get("ledger_dong"):
            named[p["ledger_dong"]] = p
        elif p.get("ledger_m2") is None:
            extra.append(p)
    by_row = [named.get(b.get("dong")) for b in keep]
    # 등록 기하로 짝을 못 지었으면 **면적으로 맞춘 추정 대응**을 세운다(`_pair_by_area`) —
    # 표를 비워 두는 것보다 낫다. 추정이라는 사실은 표와 각주에 적는다.
    by_area = not named and bool(mdl) and bool(keep)
    if by_area:
        tgt, groups, left = _pair_by_area(keep, mdl)
        for i, ((b, t), g) in enumerate(zip(tgt, groups)):
            if not g:
                continue
            sm = sum(x["properties"].get("arch_area_m2") or 0 for x in g)
            by_row[i] = dict(
                rules.ledger_verdict(sm, t), scope="building", measured_m2=sm,
                ledger_m2=t, ledger_dong=b.get("dong"),
                bld_id=g[0]["properties"]["bld_id"],
                members=[x["properties"]["bld_id"] for x in g], by_area=True)
        for f in left:
            a = f["properties"].get("arch_area_m2") or 0
            extra.append(dict(rules.ledger_verdict(a, None), scope="building",
                              measured_m2=a, ledger_m2=None,
                              bld_id=f["properties"]["bld_id"],
                              members=[f["properties"]["bld_id"]], by_area=True))
    # 지도는 **건물마다** 색을 칠하므로 묶음 판정을 멤버 전부에 펴 둔다. 크게 모자란 묶음은
    # 표와 같이 판정을 접는다(`short_of`) — 지도만 초록이면 표와 두 말이 된다.
    by_bld = {}
    for p in [q for q in by_row if q] + extra:
        q = (dict(p, level="정보없음", label="판독 면적이 대장보다 크게 모자람")
             if short_of(p.get("measured_m2"), p.get("ledger_m2")) else p)
        for bid in (q.get("members") or ([q["bld_id"]] if q.get("bld_id") else [])):
            by_bld[bid] = q
    return {"led_fc": L["ledger"], "by_area": by_area, "by_bld": by_bld,
            "keep": keep, "dropped": dropped, "led_sum": led_sum, "mdl_sum": mdl_sum,
            # `by_row` 는 **`keep` 과 같은 길이의 목록**이다(짝이 없으면 `None`).
            "n_mdl": len(mdl), "by_row": by_row, "extra": extra,
            "verdict": s4_ledger.parcel_verdict(mdl_sum, led_sum, len(mdl), len(keep))}


def _dong_list(mdl, dong, *, cap=10):
    """「A동 · B동 · …」. **다 적지 않는다** — 33동 물건에서 이 칸 한 줄이 종이 오른쪽 밖으로
    흘러나갔다(실측 공단동 150). 칸은 잘라 주지 않으므로 세는 쪽에서 끊는다.
    """
    ns = [dong[f["properties"]["bld_id"]]
          for f in sorted(mdl, key=lambda x: -(x["properties"].get("arch_area_m2") or 0))]
    if len(ns) <= cap:
        return " · ".join(ns)
    return " · ".join(ns[:cap]) + f" … 외 {len(ns) - cap}동"


def _tw(txt, size=8.5):
    """글자 폭 어림(inch) — 한글·기호는 1 em, 그 밖은 0.52 em. 정확할 필요는 없고 **넘치는
    줄을 알아채기만** 하면 된다."""
    em = size / 72.0
    return sum(em if ord(c) > 0x2000 else em * 0.52 for c in str(txt))


def _clip(txt, colw, *, size=8.5, pad_in=0.14):
    """열 폭 안으로 자른다. **두 렌더러 다 넘치는 글자를 잘라 주지 않는다** — PDF 는 옆 칸을
    덮어쓰고(실측 고잔동 524-8 의 「분뇨.쓰레기처리시설·경량철골구조」가 층수·면적 칸을
    덮었다), HTML 은 열 폭을 밀어내 PDF 와 판이 갈린다.
    """
    # 셀은 좌우 **양쪽**에 0.008 fig(=0.066 in)씩 여백이 있다 — 한쪽만 빼면 오른쪽 테두리에
    # 글자가 닿는다.
    lim = colw * BODY_W * A4[0] - pad_in
    if _tw(txt, size) <= lim:
        return txt
    out = ""
    for c in str(txt):
        if _tw(out + c + "…", size) > lim:
            break
        out += c
    return out + "…"


def _ledger_rows(lvw, dong):
    """대장에 적힌 것(동명·용도·구조·층수·면적) 옆에 **위성 판독 면적**을 나란히.

    설계서 ⑤ 대로 **동 이름을 맨 앞**에 둔다(「A동」) — 지도의 배지와 같은 이름이라 어느
    건물의 줄인지 되짚을 수 있다. 대장에만 있고 위성이 못 잡은 동은 붙일 이름이 없으므로
    「—」로 두고, 위성만 잡은 동은 「대장 동」 칸을 「대장에 없음」으로 적는다.
    """
    # 동별 대응을 **아예 못 낸** 필지가 있다(등록 footprint 가 대장 면적을 설명하지 못할
    # 때 — `_ledger_view`). 그때 「위성 미검출」로 적으면 위성이 건물을 못 잡은 것처럼
    # 읽히는데, 실제로는 33동을 잡고도 어느 동인지 짝을 못 지은 것이다(실측 공단동 150).
    paired = any(lvw["by_row"])
    par = DR.led_parcel(lvw["led_fc"])

    def who(m):
        """판독 동 칸 — 묶음이면 「A동+C동」. 대장에는 위치가 없어 한 동에 판독 동 여럿이
        묶일 수 있다(`_pair_by_area`)."""
        ns = [dong.get(b) for b in ((m or {}).get("members") or []) if dong.get(b)]
        return "+".join(ns) if ns else dong.get((m or {}).get("bld_id"), "—")

    rows = [["판독 동", "대장 동 · 용도 · 구조", "층수", "대장 면적", "판독 면적",
             "면적 차이", "정합 여부"]]
    for b, m in zip(lvw["keep"], lvw["by_row"]):
        a = b.get("arch_area_m2") or 0
        meas = (m or {}).get("measured_m2")
        # 정합 칸은 **지도 배지·범례와 같은 세 말**(일치·불일치·판정 불가)만 쓴다. 동별 짝을
        # 못 지은 필지는 필지 총량 판정으로 갈음하고(`led_match`), 짝은 지었는데 이 동만
        # 위성이 못 잡은 경우만 판정 불가다 — 그 사실은 「판독 면적」 칸에 적는다.
        t, c = row_match(m) if m else (
            ("판정 불가", DIM) if paired else led_lv(par))
        # 「대장 동 / 용도 · 구조」는 두 줄로 접고 줄마다 폭에 맞춰 자른다 — 한 줄로 두면
        # 용도명이 길어 옆 칸을 덮는다.
        rows.append([who(m),
                     _clip(b.get("dong") or "(동명없음)", LED_COLW[1]) + "\n"
                     + _clip(" · ".join(x for x in (b.get("main_purpose"),
                                                    b.get("struct")) if x) or "—",
                             LED_COLW[1]),
                     f"{int(b.get('floors_above') or 0)}층",
                     f"{a:,.0f} ㎡",
                     ("미검출", DIM) if (meas is None and paired) else
                     ("—" if meas is None else f"{meas:,.0f} ㎡"),
                     "—" if meas is None else
                     (f"{meas - a:+,.0f} ㎡ ({(meas / a - 1) * 100:+.0f} %)" if a else "—"),
                     (t, c)])
    for p in lvw["extra"]:
        t, c = led_lv(p)
        rows.append([who(p), "대장에 없음", "—", "—",
                     f"{p.get('measured_m2', 0):,.0f} ㎡",
                     f"+{p.get('measured_m2', 0):,.0f} ㎡", (t, c)])
    # **나쁜 것부터** — 2면 이격 표와 같은 규칙이다. 면적 큰 순으로 두면 줄 수를 자를 때
    # 정작 볼 줄(불일치·판정 불가)이 「외 N동」 속에 묻힌다(실측 구미 공단동 150: 지도에는
    # 회색이 여덟인데 표에는 한 줄도 없었다).
    order = {"불일치": 0, "판정 불가": 1, "일치": 2}
    body = sorted(rows[1:], key=lambda q: order.get(_cell(q[6])[0], 9))
    return [rows[0]] + body


def _sep_line(fc, skip=(), hide=()):
    """1면의 한 줄 요약 — **방위 · 거리 · 판정 순**으로 적는다(설계서 3면).

    `hide` 는 2면 표에서 뺀 상대([[draw.py]] `sep_hidden`) — 1면이 세는 동 수와 2면 표의
    줄 수가 갈리면 종이 안에서 앞뒤가 맞지 않는다.
    """
    # **필지 안 쌍을 두 번 세지 않는다**(2026-08-27). `sep_pairs` 는 A→B 와 B→A 를 둘 다
    # 내는데(건물마다 「내 둘레에 무엇이 있나」를 적는 표이므로 그것이 맞다), 이 줄이 그대로
    # 세면 **같은 종이 안에서 두 수가 갈린다** — 실측 호림동 3-10·구미 공단동 293-15: 1면
    # 「위험 8건」인데 바로 위 「확인 필요 항목」과 2면 표는 7이었다. 2면 표는 필지 안 쌍을
    # 한 줄로 접으므로(`_sep_own_rows`) 여기서도 접는다.
    seen, fs = set(), []
    for f in DR.sep_pairs(fc, skip=skip):
        p = f["properties"]
        pr = p.get("pair") or []
        if len(pr) > 1 and pr[1] in hide:
            continue
        if p.get("same_parcel") and len(pr) > 1:
            k = frozenset(pr[:2])
            if k in seen:
                continue
            seen.add(k)
        fs.append(p)
    if not fs:
        return "주변에 마주 선 건물이 없음"
    if all(p.get("kind") == "lot_line" for p in fs):
        # 상대 건물이 없을 때만 나오는 보조 판정이다 — 「건물 간」으로 읽히면 안 된다.
        m = min(fs, key=lambda p: p["dist_m"])
        return (f"마주 선 건물이 없어 대지경계선까지 측정 — 최근접 "
                f"{DR.dist_text(m['dist_m'])} · {DR.sep_level3(m['level'])}")
    hit = [p for p in fs if DR.sep_level3(p["level"]) in ("위험", "주의")]
    if not hit:
        return f"건물 {len(fs)}동 · 모두 안전"
    m = min(hit, key=lambda p: p["dist_m"])
    n_r = sum(1 for p in fs if DR.sep_level3(p["level"]) == "위험")
    n_c = sum(1 for p in fs if DR.sep_level3(p["level"]) == "주의")
    where = m.get("dir8") or m.get("dir") or ""
    side = "" if m.get("same_parcel") is None else (
        "(필지내)" if m["same_parcel"] else "(필지외)")
    return (f"최근접 이격거리 {where}{side} {DR.dist_text(m['dist_m'])}"
            f" · 위험 {n_r}건 · 주의 {n_c}건")


def _yard_count(fc):
    """1면 「탐지 결과」 칸의 적재 구역 수 — **판정과 무관하게 몇 개소인가.**

    「확인 필요 항목」은 위험한 줄만 세므로 15 m 밖이라 「안전」인 구역은 거기서 0 이다. 그런데
    「마당에 몇 무더기가 있었나」는 그 자체로 읽을 값이라 1면에 남아야 한다(사용자 결정,
    2026-08-27). 판독을 안 돌린 것과 돌려서 없는 것은 여기서도 가른다.
    """
    if _yard_skipped(fc):
        return "적재 판독 안 함"
    n = len(fc.get("features") or [])
    return f"적재 {n}개소" if n else "적재 없음"


def _yard_line(fc):
    fs = [f["properties"] for f in (fc.get("features") or [])]
    if not fs:
        # 판독을 건너뛴 것과 돌려서 없는 것은 다른 말이다 — 「없음」으로 뭉치면 판정이
        # 「판정 불가」인데 결과는 「없음」이라는 앞뒤 안 맞는 줄이 된다.
        return (_yard_skipped(fc) and "적재물 판독을 돌리지 않음"
                or "마당에 쌓인 가연물 없음")
    # **3면 표와 같은 잣대로 센다** — 표에서 「위험」·「주의」인 줄이 곧 건물에 근접한
    # 구역이다(판정어가 셋으로 갈린 뒤로는 그 둘이다 — 2026-08-27). 예전에는
    # `level == "해당"` 만 세어, 표에 근접이 셋인 물건의 1면이 「가까운 곳 1곳」으로 나갔다.
    hit = [p for p in fs if _zone_lv(p.get("level"))[0] in ("위험", "주의")]
    head = f"적재 구역 {len(fs)}개소 탐지"
    if hit:
        d = min((p.get("dist_to_building_m") for p in hit
                 if p.get("dist_to_building_m") is not None), default=None)
        near = f"(최소 이격 {d:.1f} m)" if d is not None else ""
        return f"{head} · 건물 근접 {len(hit)}개소{near}"
    return f"{head} · 건물에서 떨어져 있음"


def _led_line(lvw):
    if not lvw["keep"] and not lvw["mdl_sum"]:
        return "대조할 대장 자료가 없음"
    d = lvw["mdl_sum"] - lvw["led_sum"]
    pct = (d / lvw["led_sum"] * 100) if lvw["led_sum"] else 0.0
    bad = [p for p in lvw["by_row"]
           if p and DR.led_match(p) == "불일치"] + lvw["extra"]
    s = (f"대장 {lvw['led_sum']:,.0f} ㎡ / 판독 {lvw['mdl_sum']:,.0f} ㎡ "
         f"({d:+,.0f} ㎡ · {pct:+.0f} %)")
    if not any(lvw["by_row"]) and lvw["n_mdl"]:
        return s + " · 필지 총량 대조(동별 짝 못 지음)"
    return s + (f" · 불일치 {len(bad)}동" if bad else "")


# ── PDF 렌더러 ──────────────────────────────────────────────────────────────
class Runs(list):
    """한 칸 안에서 **색이 갈리는 글자 토막** — `Runs([("3.3 m · ", None), ("위험", 빨강)])`.

    그냥 리스트는 「이 열을 다시 쪼갠다」는 뜻이라(판정 기준 표) 뜻이 겹치지 않게 갈라 둔다.
    비교분석 이격 표가 이것을 쓴다 — 「거리 · 판정」을 한 칸에 적되 판정만 판정색이다.
    """


def _cell(c):
    """셀 → (글자, 색). 색이 None 이면 기본색 — 머리행에도 색을 줄 수 있게 나눠 둔다."""
    return (c, None) if not isinstance(c, tuple) else c


def _runs_text(cell):
    return "".join(str(_cell(x)[0]) for x in cell)


def _nlines(cell):
    """셀이 차지하는 줄 수. 줄바꿈은 두 렌더러가 **같은 자리에서** 접게 미리 넣어 둔 것이다."""
    if isinstance(cell, Runs):
        return _runs_text(cell).count("\n") + 1
    if isinstance(cell, list):
        return max((_nlines(s) for s in cell), default=1)
    return str(_cell(cell)[0]).count("\n") + 1


def _pdf_cell(ax, cx, top, w, h, cell, fc, al, bold):
    ax.add_patch(Rectangle((cx, top - h), w, h, facecolor=fc, edgecolor=LINE, linewidth=0.6))
    if isinstance(cell, Runs):
        # 토막을 **왼쪽부터 이어 붙여** 그린다 — 한 번에 그릴 수 없으므로 폭을 재서 시작점을
        # 잡는다(`_tw`). 어림이라도 되는 이유는 칸 안에서 가운데 맞춤만 하기 때문이다.
        wid = [_tw(_cell(x)[0]) / A4[0] for x in cell]
        start = {"left": cx + 0.008, "center": cx + (w - sum(wid)) / 2,
                 "right": cx + w - 0.008 - sum(wid)}[al]
        for x, dw in zip(cell, wid):
            txt, col = _cell(x)
            ax.text(start, top - h / 2, txt, size=8.5, color=(col or INK),
                    weight="bold" if bold else "normal", va="center", ha="left",
                    linespacing=1.35)
            start += dw
        return
    txt, col = _cell(cell)
    tx = {"left": cx + 0.008, "center": cx + w / 2, "right": cx + w - 0.008}[al]
    ax.text(tx, top - h / 2, txt, size=8.5, color=(col or INK),
            weight="bold" if bold else "normal", va="center", ha=al, linespacing=1.35)


def _pdf_table(fig, rows, y, o):
    x, w = MARGIN, BODY_W
    cw = [w * c for c in o["colw"]]
    rowh = o.get("rowh", 0.0215)
    ax = fig.add_axes([0, 0, 1, 1], zorder=1)
    ax.set_axis_off(); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    top = y
    for r, row in enumerate(rows):
        head = o.get("head") and r == 0
        h = rowh * (1.15 if head else 1.0) * (1 + 0.62 * (max(map(_nlines, row)) - 1))
        cx = x
        for c, cell in enumerate(row):
            fc = HEAD_BG if head else (BAND if (o.get("label") and c == 0) else "white")
            bold = bool(head or (o.get("label") and c == 0))
            if isinstance(cell, list) and not isinstance(cell, Runs):   # 한 열을 다시 쪼갠다
                sw = cw[c] / len(cell)
                for i, sub in enumerate(cell):
                    _pdf_cell(ax, cx + i * sw, top, sw, h, sub, fc, "center", bold)
            else:
                # **모든 칸이 가운데다**(사용자 결정, 2026-08-27). 표마다 왼쪽·오른쪽·가운데를
                # 따로 정하던 열쇠(`center`·`center_cols`·`right_cols`)는 걷어 냈다 — 표가
                # 열둘이라 어느 것은 오른쪽 어느 것은 왼쪽으로 갈려 있었고, 그 갈림에 뜻이
                # 없었다. 한 규칙이면 옵션도 없고 두 렌더러가 갈릴 자리도 없다.
                _pdf_cell(ax, cx, top, cw[c], h, cell, fc, "center", bold)
            cx += cw[c]
        top -= h
    return top


def _pdf_img(fig, path, y, h):
    from PIL import Image
    im = Image.open(path)
    iw, ih = im.size
    pw, ph = BODY_W * A4[0], h * A4[1]
    s = min(pw / iw, ph / ih)
    dw, dh = iw * s / A4[0], ih * s / A4[1]
    ax = fig.add_axes([MARGIN + (BODY_W - dw) / 2, y - dh, dw, dh], zorder=2)
    ax.imshow(im)
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_color(LINE); sp.set_linewidth(0.6)
    return y - dh - 0.010


def _pdf_legend(fig, items, y):
    ax = fig.add_axes([0, 0, 1, 1], zorder=1)
    ax.set_axis_off(); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    cx = MARGIN
    for name, col in items:
        ax.add_patch(Rectangle((cx, y - 0.010), 0.012, 0.008, facecolor=col, edgecolor="none"))
        ax.text(cx + 0.017, y - 0.006, name, size=8, color=DIM, va="center")
        cx += 0.017 + 0.0085 * len(name) + 0.022
    return y - 0.020


# 그림을 PDF 에 담는 해상도 — 아래가 바닥이고 위가 상한이다. 바닥은 인쇄 기준(300 dpi)이고,
# 상한은 그 위로 올려도 종이에서 좋아지지 않는 선이다.
REPORT_DPI_MIN, REPORT_DPI_MAX = 300, 600


def _page_dpi(pg):
    """이 면의 그림을 **원본 픽셀 그대로** 담는 데 필요한 dpi.

    **matplotlib 은 `imshow` 한 그림을 「축 크기 × 그림의 dpi」로 다시 샘플링해 PDF 에 넣는다.**
    `figure.dpi` 기본값이 100 이고 `savefig` 에 dpi 를 안 주면 그 값이 그대로 쓰이므로, 아무리
    큰 PNG 를 넣어도 종이에서 **100 dpi 로 뭉개진다.** 실측 2026-08-27:

        위험분석 2면   원본 1,600 px → 담긴 508 px (129 mm · 100 dpi)   3.1배 줄었다
        비교분석 2면   원본 2,946 px → 담긴 712 px (181 mm · 100 dpi)   4.1배 줄었다
        머리 로고      원본  435 px → 담긴  86 px ( 22 mm · 100 dpi)   5.1배 줄었다

    비교분석이 더 나쁜 것은 두 날짜를 나란히 붙여(`compare.pair_png`) 원본이 두 배로 넓기
    때문이다. `REPORT_PX` 를 1,600 으로 올려 둔 것도(「300 dpi ≈ 1,500 px」) 이 한 줄이
    없어서 종이까지 오지 못하고 있었다.

    **면마다 필요한 만큼만 올린다.** 그림이 크게 앉는 면은 높이고, 표만 있는 면은 바닥(300 dpi)
    으로 둔다 — 한 값으로 고정하면 어떤 면은 모자라고 어떤 면은 파일만 키운다. 필요한 dpi 는
    `_pdf_img` 의 축소율에서 그대로 나온다(그 함수가 쓰는 `s` 의 역수).

    **머리 로고는 이 셈에 넣지 않는다.** 435 px 짜리 워드마크를 22 mm 에 앉히면 「원본대로」가
    507 dpi 인데, 그 한 조각 때문에 면 전체가 507 dpi 가 되어 **1,600 px 지도가 2,572 px 로
    늘어난다**(실측: 그렇게 뽑은 6면 보고서가 1.3 MB → 12 MB). 로고는 22 mm 짜리 글자라
    300 dpi(260 px)면 인쇄물에서 또렷하고, 그것이 이 문서가 목표로 잡은 눈금이다.
    """
    from PIL import Image
    need = [float(REPORT_DPI_MIN)]
    for b in pg.get("blocks") or []:
        if b[0] != "img":
            continue
        iw, ih = Image.open(b[1]).size
        h = (b[2] or {}).get("h", 0.5)
        need.append(1.0 / min(BODY_W * A4[0] / iw, h * A4[1] / ih))
    return min(REPORT_DPI_MAX, max(need))


def _pdf_head(fig):
    """머리 — 고객사 로고(오른쪽 위)와 **그 폭만큼의 밑줄.**

    자리는 「지반침하 위험 보고서 샘플(주의·누적구역)」을 재서 옮겼다(`LOGO_*` · `RULE_*`).
    밑줄은 **로고와 오른쪽 끝을 맞추고 폭도 로고와 같다** — 그래서 폭을 숫자로 적지 않고
    그림의 가로세로비에서 낸다.

    로고 파일이 없으면 **밑줄도 안 그린다** — 밑줄은 로고에 딸린 것이라 혼자 있으면 무엇을
    긋는 선인지 알 수 없다(구판의 전폭 띠는 혼자 서 있어도 됐지만 이것은 아니다).
    """
    if not LOGO.exists():
        return
    im = plt.imread(str(LOGO))
    h = LOGO_H_MM / A4MM[1]
    w = (LOGO_H_MM * im.shape[1] / im.shape[0]) / A4MM[0]
    x0 = _fx(A4MM[0] - MARGIN_MM) - w
    ax = fig.add_axes([x0, _fy(LOGO_TOP_MM + LOGO_H_MM), w, h], zorder=3)
    # aspect="auto" — 축 상자를 로고 비율로 잡아 두었으므로 늘어나지 않는다. 기본값
    # (equal)이면 상자 안에서 다시 맞추다 여백이 생겨 오른쪽 끝이 어긋난다.
    ax.imshow(im, aspect="auto", interpolation="lanczos")
    ax.set_axis_off()
    fig.patches.append(Rectangle((x0, _fy(RULE_TOP_MM + RULE_H_MM)), w, RULE_H_MM / A4MM[1],
                                 transform=fig.transFigure, facecolor=RULE, edgecolor="none"))


def render_pdf(doc, out):
    plt.rcParams["font.family"] = FONT
    plt.rcParams["axes.unicode_minus"] = False
    with PdfPages(out) as pdf:
        for i, pg in enumerate(doc, start=1):
            fig = plt.figure(figsize=A4)
            _pdf_head(fig)
            fig.text(MARGIN, _fy(TITLE_TOP_MM), pg["title"], size=15, weight="bold",
                     color=INK, va="top")
            if pg.get("sub"):
                fig.text(MARGIN, _fy(SUB_TOP_MM), pg["sub"], size=8.5, color=DIM, va="top")
            fig.text(MARGIN, _fy(A4MM[1] - FOOT_BOT_MM), "위성 분석 제공 정보 · 샘플",
                     size=8, color=DIM)
            fig.text(1 - MARGIN, _fy(A4MM[1] - FOOT_BOT_MM), f"{i} / {len(doc)}",
                     size=8, color=DIM, ha="right")
            # `y` 는 **다음 블록을 놓을 자리**라 마지막에 그린 것보다 한 줄 아래다. 넘침은
            # 자리가 아니라 **찍힌 것**으로 재야 하므로 잉크의 아래끝을 따로 센다.
            y = ink = _fy(BODY_TOP_MM)
            for b in pg["blocks"]:
                if b[0] == "sec":
                    # **위 기준**으로 놓는다 — baseline 으로 놓으면 글자가 자리보다 위로
                    # 올라가서, 절 제목이 첫 블록인 면에서 부제와 겹친다(실측 「이어서」 면).
                    #
                    # **글머리 기호 ■ 만 밑줄과 같은 파랑**이다(샘플 신판: ■ 는 (0,60,220) ·
                    # 글자는 진회색). 한 줄을 두 번 그려 앞 글자만 덮는다 — 「■ 」 의 폭을
                    # 재서 label 을 밀어 놓는 길도 있지만, 그 폭은 글꼴·크기마다 달라 숫자로
                    # 적어 두면 글꼴을 바꿀 때 조용히 어긋난다. 같은 자리에 겹쳐 그리면
                    # 글리프 윤곽이 정확히 포개지므로 잴 것이 없다.
                    fig.text(MARGIN, y, f"■ {b[1]}", size=10.5, weight="bold",
                             color=INK, va="top")
                    fig.text(MARGIN, y, "■", size=10.5, weight="bold",
                             color=RULE, va="top")
                    ink = y - 0.0150
                    y -= 0.0195
                elif b[0] == "tbl":
                    y = ink = _pdf_table(fig, b[1], y, b[2])
                    y -= 0.017
                elif b[0] == "img":
                    y = _pdf_img(fig, b[1], y, b[2].get("h", 0.5))
                    ink = y + 0.010
                elif b[0] == "legend":
                    y = _pdf_legend(fig, b[1], y)
                    ink = y + 0.002
                    y -= 0.006
                elif b[0] == "note":
                    import textwrap
                    for j, ln in enumerate(textwrap.wrap(b[1], width=58) or [""]):
                        fig.text(MARGIN + (0.008 if j else 0), y,
                                 ("· " if j == 0 else "") + ln, size=8.5, color=DIM)
                        ink = y - 0.004
                        y -= 0.0152
                    y -= 0.002
            if ink < FLOOR_Y:
                # 넘친 내용은 **조용히 사라진다**(matplotlib 은 잘라 내지도, 다음 쪽으로
                # 넘기지도 않는다). 판짜기가 어긋난 것을 종이를 보고서야 알면 늦다.
                con.warn(f"{i}면이 넘쳤다 — 아래끝 {(1 - ink) * A4MM[1]:.0f} mm "
                         f"(한도 {(1 - FLOOR_Y) * A4MM[1]:.0f} mm). 표 줄 수나 "
                         f"그림 높이를 줄여야 한다")
            # **dpi 를 면마다 준다** — 안 주면 그림이 100 dpi 로 뭉개진다(`_page_dpi`).
            pdf.savefig(fig, dpi=_page_dpi(pg)); plt.close(fig)
        pdf.infodict()["Title"] = doc[0]["title"]
    return Path(out)


# ── HTML 렌더러 — **PDF 와 같은 판, 같은 크기** ─────────────────────────────
# 단위를 mm·pt 로 쓴다. 예전에는 폭 820 px 에 글자도 px 였는데, 그러면 A4 로 인쇄했을 때
# PDF 와 글자 크기·여백이 다 어긋난다. matplotlib 의 `size=8.5` 는 8.5 pt 이므로 CSS 도
# pt 로 적으면 **같은 물리 크기**로 앉고, 판은 210×297 mm 로 못 박아 비율까지 같아진다.
# 자리값은 위쪽 `*_MM` 상수를 f-string 으로 박아 두 렌더러가 한 값을 쓴다.
ROW_MM = 0.0215 * A4MM[1]                # PDF 표 한 줄 높이(figure 비율 → mm)
PAD_MM = 0.008 * A4MM[0]                 # 셀 좌우 여백


def _css():
    return f"""
:root {{ --ink:{INK}; --dim:{DIM}; --line:{LINE}; --head:{HEAD_BG}; --band:{BAND};
        --rule:{RULE}; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:#e9ebee; color:var(--ink);
       font-family:"Noto Sans CJK KR","Noto Sans KR","Malgun Gothic",sans-serif; }}
/* 쪽 밑 글줄을 **flex 로** 내린다. position:absolute + bottom 은 렌더러마다 담는 상자의
   높이를 다르게 잡아(min-height 를 안 보는 쪽이 있다) 글줄이 본문 바로 밑에 붙는다. */
.page {{ width:{A4MM[0]}mm; min-height:{A4MM[1]}mm; margin:6mm auto; background:#fff;
        box-shadow:0 1px 4px rgba(0,0,0,.14); display:flex; flex-direction:column; }}
.brand {{ flex:none; height:{RULE_TOP_MM + RULE_H_MM}mm; text-align:right;
         padding:{LOGO_TOP_MM}mm {MARGIN_MM}mm 0 0; }}
/* 밑줄은 **로고를 감싼 상자의 아래 테두리**다 — 폭을 mm 로 적으면 로고를 바꿀 때 옛 폭으로
   남는다. inline-block 이라 상자가 그림 폭에 딱 맞는다(PDF 쪽도 같은 폭을 쓴다). */
.brand .mark {{ display:inline-block; padding-bottom:{RULE_TOP_MM - LOGO_TOP_MM - LOGO_H_MM:.2f}mm;
               border-bottom:{RULE_H_MM}mm solid var(--rule); }}
.brand img {{ height:{LOGO_H_MM}mm; display:block; }}
.body {{ flex:1 1 auto; padding:0 {MARGIN_MM}mm; }}
h1 {{ font-size:15pt; font-weight:700; line-height:1.15;
     margin:{TITLE_TOP_MM - RULE_TOP_MM - RULE_H_MM:.2f}mm 0 0; }}
.sub {{ font-size:8.5pt; color:var(--dim); line-height:1.2;
       margin:1.9mm 0 {BODY_TOP_MM - SUB_TOP_MM - 3.6:.2f}mm; }}
h2 {{ font-size:10.5pt; font-weight:700; margin:4.6mm 0 1.2mm; }}
h2::before {{ content:"■ "; color:var(--rule); }}
table {{ width:100%; border-collapse:collapse; font-size:8.5pt; margin:0 0 3.4mm; }}
td, th {{ border:0.2mm solid var(--line); padding:0 {PAD_MM:.2f}mm;
         height:{ROW_MM:.2f}mm; line-height:1.35; }}
th {{ background:var(--head); font-weight:700; text-align:center;
     height:{ROW_MM * 1.15:.2f}mm; }}
td.label {{ background:var(--band); font-weight:700; text-align:center; }}
td.c {{ text-align:center; }}
.legend {{ margin:2mm 0 1mm; font-size:8pt; color:var(--dim); }}
.legend span {{ margin-right:5.5mm; white-space:nowrap; }}
.legend i {{ display:inline-block; width:2.5mm; height:1.7mm; margin-right:1.2mm; }}
img.map {{ display:block; margin:0 auto; border:0.2mm solid var(--line);
          max-width:{BODY_W * A4MM[0]:.1f}mm; }}
.note {{ font-size:8.5pt; color:var(--dim); line-height:1.42; margin:0.6mm 0 0;
        padding-left:2.4mm; text-indent:-2.4mm; }}
.foot {{ flex:none; margin:0 {MARGIN_MM}mm; padding:1mm 0 {FOOT_BOT_MM - 3.0:.2f}mm;
        display:flex; justify-content:space-between; font-size:8pt; color:var(--dim); }}
@page {{ size:A4; margin:0; }}
@media print {{ body {{ background:#fff; }}
        .page {{ margin:0; box-shadow:none; page-break-after:always; }} }}
"""


def _h(s):
    return html.escape(str(s))


def _hb(s):
    """셀 글자 — 줄바꿈은 PDF 와 **같은 자리에서** 접는다."""
    return "<br>".join(_h(x) for x in str(s).split("\n"))


def _b64(path):
    return "data:image/png;base64," + base64.b64encode(Path(path).read_bytes()).decode()


def _html_head(embed):
    """머리 — 고객사 로고와 그 폭만큼의 밑줄. PDF `_pdf_head` 와 같은 자리·같은 크기다."""
    if not LOGO.exists():
        return '<div class="brand"></div>'
    src = _b64(LOGO) if embed else LOGO.name
    return f'<div class="brand"><span class="mark"><img src="{src}" alt="고객사"></span></div>'



def render_html(doc, out, *, embed=True):
    P = ['<!doctype html><html lang="ko"><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         f'<title>{_h(doc[0]["title"])}</title>', f"<style>{_css()}</style>"]
    head = _html_head(embed)
    for i, pg in enumerate(doc, start=1):
        P.append('<section class="page">')
        P.append(head)
        P.append('<div class="body">')
        P.append(f'<h1>{_h(pg["title"])}</h1>')
        # 부제가 없는 면(1면)도 **자리는 남긴다** — PDF 는 본문을 늘 같은 높이에서 시작하는데
        # HTML 만 위로 당겨지면 두 판이 갈린다.
        P.append('<p class="sub">%s</p>'
                 % (_h(pg["sub"]) if pg.get("sub") else "&nbsp;"))
        for b in pg["blocks"]:
            if b[0] == "sec":
                P.append(f"<h2>{_h(b[1])}</h2>")
            elif b[0] == "tbl":
                rows, o = b[1], b[2]
                # 쪼갠 칸은 **진짜 칸**으로 낸다 — 열을 잘게 깔아 두고 안 쪼갠 줄은
                # colspan 으로 덮는다. td 안에 상자를 덧대면 테두리와 높이가 어긋난다.
                sp = [max((len(x[c]) if (isinstance(x[c], list)
                                         and not isinstance(x[c], Runs)) else 1)
                          for x in rows if c < len(x)) for c in range(len(rows[0]))]
                P.append("<table>")
                # 열 폭도 PDF 와 같은 값으로 못 박는다 — 내용에 맡기면 두 판이 갈린다.
                P.append("<colgroup>")
                for c, cw in enumerate(o.get("colw", [])):
                    P += [f'<col style="width:{cw / sp[c] * 100:.4g}%">'] * sp[c]
                P.append("</colgroup>")
                for r, row in enumerate(rows):
                    P.append("<tr>")
                    for c, cell in enumerate(row):
                        cells = (cell if (isinstance(cell, list)
                                          and not isinstance(cell, Runs)) else [cell])
                        n = sp[c] // len(cells)
                        cs = f' colspan="{n}"' if n > 1 else ""
                        for x in cells:
                            if isinstance(x, Runs):
                                txt = "".join(
                                    (f'<span style="color:{col}">{_hb(t)}</span>'
                                     if col else _hb(t))
                                    for t, col in (_cell(y) for y in x))
                                st = ""
                            else:
                                t, col = _cell(x)
                                txt, st = _hb(t), (f' style="color:{col}"' if col else "")
                            if o.get("head") and r == 0:
                                P.append(f"<th{cs}{st}>{txt}</th>")
                                continue
                            # 모든 칸이 가운데다 — PDF 쪽 `_pdf_table` 과 같은 규칙이다.
                            cls = "label" if o.get("label") and c == 0 else "c"
                            P.append(f'<td class="{cls}"{cs}{st}>{txt}</td>')
                    P.append("</tr>")
                P.append("</table>")
            elif b[0] == "img":
                # 높이 한도를 **줄마다** 준다 — PDF 는 (본문 폭 × h) 상자 안에 맞추므로
                # 세로가 먼저 걸리는데, CSS 에서 max-height 를 빼면 폭 한도까지 커져서
                # 같은 그림이 HTML 에서 훨씬 크게 앉고 판을 넘긴다.
                src = _b64(b[1]) if embed else Path(b[1]).name
                mh = (b[2] or {}).get("h", 0.5) * A4MM[1]
                P.append(f'<img class="map" style="max-height:{mh:.1f}mm" src="{src}">')
            elif b[0] == "legend":
                P.append('<p class="legend">' + "".join(
                    f'<span><i style="background:{c}"></i>{_h(n)}</span>' for n, c in b[1])
                    + "</p>")
            elif b[0] == "note":
                P.append(f'<p class="note">· {_h(b[1])}</p>')
        P.append("</div>")
        P.append(f'<div class="foot"><span>위성 분석 제공 정보 · 샘플</span>'
                 f'<span>{i} / {len(doc)}</span></div></section>')
    P.append("</html>")
    Path(out).write_text("\n".join(P), encoding="utf-8")
    return Path(out)


# ── 조립 ────────────────────────────────────────────────────────────────────
def find_result(folder):
    """결과 파일 — `demo.json`(GT · demo.py) 또는 `result.json`(모델 · run.py). 형식이 같다."""
    folder = Path(folder)
    if folder.is_file():
        return folder
    for name in ("demo.json", "result.json"):
        if (folder / name).exists():
            return folder / name
    return None


def build(address, root, out_stem=None, *, skip=(), html_too=True, pdf=True,
          folder=None, name=None):
    """보고서를 낸다. `out_stem` 을 안 주면 **결과 폴더 안에 「보고서」**로 넣는다 —
    주소마다 폴더가 하나씩 있으므로 보고서도 그 옆에 있어야 짝이 흩어지지 않는다.

    `name` 은 **어느 값 파일을 읽을지 부른 쪽이 못 박는 것**이다. 안 주면 `find_result` 가
    `demo.json` 을 먼저 집는데, 한 폴더에 둘이 같이 있으면(모델 결과 옆에 GT 결과를
    `--out` 으로 떨어뜨리면 그렇게 된다) 모델 실행이 GT 값으로 종이를 뽑고도 아무 말을 하지
    않는다. 파이프라인은 자기가 방금 쓴 이름을 넘긴다([[pipeline.py]] `finish`).
    """
    folder = Path(folder) if folder else (Path(root) / slug(address))
    p = (folder / name) if (name and (folder / name).exists()) else find_result(folder)
    if p is None:
        raise FileNotFoundError(
            f"결과가 없다: {folder or Path(root) / slug(address)}\n"
            f"  GT 로 내려면 `python demo.py \"{address}\"`, "
            f"모델로 내려면 `python run.py \"{address}\"`")
    out_stem = out_stem or str(p.parent / "보고서")
    r = json.loads(p.read_text("utf-8"))
    site, L = r["site"], r["layers"]
    near = _neighbors(r)
    d = p.parent / "report"
    # 창은 **한 번만** 만든다 — 네 장이 같은 창이어야 나란히 놓고 볼 수 있고, 원본 tif 도
    # 한 번만 읽는다.
    v = _view(site)
    lvw0 = _ledger_view(r)
    imgs = {"base": img_base(v, d / f"{DR.BASE_NAME}.png"),
            "sep": img_separation(site, L["buildings"], L["separation"], near,
                                  d / "1_이격거리.png", skip=skip, v=v),
            "yard": img_yard(site, L["buildings"], L["yard"], near,
                             d / "2_야적물.png", v=v),
            "led": img_ledger(site, L["buildings"], L["ledger"], d / "3_미등록증축.png",
                              by=lvw0["by_bld"], v=v)}
    # 대장 주 용도는 지역 화재통계의 장소분류(창고시설·공장시설)를 고르는 데 쓴다.
    keep = lvw0["keep"]
    ctx = EX.context(site, keep[0].get("main_purpose") if keep else None)
    for e in ctx.get("errors") or []:
        con.warn(f"외부데이터 — {e}")
    (p.parent / "_context.json").write_text(
        json.dumps({k: v for k, v in ctx.items() if k != "missing"},
                   ensure_ascii=False, indent=1), "utf-8")
    doc = build_doc(r, imgs, near=near, skip=skip, ctx=ctx)
    # `pdf=False` 는 **손으로 만든 PDF 를 지키는 자리**다 — 저장소에 든 데모 보고서는 Chrome
    # 인쇄본이라 여기서 다시 뽑으면 판이 무너진다([[hand_writting.py]] · [[pdf_refit.py]]).
    made = [render_pdf(doc, Path(f"{out_stem}.pdf"))] if pdf else []
    if html_too:
        made.append(render_html(doc, Path(f"{out_stem}.html")))
    return made


def main(argv=None):
    ap = argparse.ArgumentParser(description="데모 결과 → 보고서(PDF · HTML)")
    ap.add_argument("address", nargs="?", default=DEFAULT)
    ap.add_argument("--root", default=None, help="결과 상위 폴더(기본 demo/)")
    ap.add_argument("--from", dest="folder", default=None,
                    help="결과 폴더를 직접 지정 — demo.json(GT) 또는 result.json(모델)")
    ap.add_argument("--out", default=None,
                    help="확장자 없는 저장 이름(기본: 결과 폴더 안의 「보고서」)")
    ap.add_argument("--skip-dir", action="append", default=None,
                    help="이격에서 뺄 방향(도로 쪽). 여러 번 줄 수 있다")
    ap.add_argument("--no-html", action="store_true")
    a = ap.parse_args(argv)
    root = Path(a.root) if a.root else config.HERE / "demo"
    skip = tuple(a.skip_dir or ())
    for f in build(a.address, root, a.out, skip=skip, html_too=not a.no_html,
                   folder=a.folder):
        print(f"  → {f}  ({f.stat().st_size / 1024:,.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
