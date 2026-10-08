"""손으로 만든 PDF 를 지금 값에 맞추는 **부품**. 물건 이름은 여기 없다.

판짜기는 [[pdf_refit.py]] 가 원본에서 재서 그대로 쓰고, 이 파일은 **무엇을 적을지**를 값에서
뽑는다. 어느 물건의 어느 표를 고칠지는 저장소 뿌리의 [[hand_writting.py]] 가 정한다.

적을 값은 보고서 렌더러가 쓰는 함수를 그대로 부른다([[single.py]] `sep_dong_rows` ·
[[draw.py]] `dist_text` · `dong_names`) — 종이와 화면이 같은 함수에서 나와야 「어느 쪽이
정본이냐」를 묻지 않는다.

**여러 번 돌려도 된다.** 저장소에 든 PDF 는 이미 한 번 고친 판이라, 「원본이 몇 줄이었나」를
손으로 적어 두면 두 번째 실행이 그 고침을 또 얹는다(실측 2026-08-24: 호림동 B동 표가 한 줄
더 올라가 소제목을 덮었다). 그래서 줄 수는 `fit_table` 이 **지금 PDF 에서 재고**, 줄 단위
고침은 `once`·`set_counts` 가 **옛 값이 남아 있을 때만** 손댄다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from sitecheck import draw as DR
from sitecheck.report import single as FR
from sitecheck.report.pdf_refit import face

ROOT = Path(__file__).resolve().parents[2]

INK = (0.133, 0.133, 0.133)
SEP_COLOR = {"위험": (0.851, 0.169, 0.169), "주의": (0.910, 0.475, 0.039),
             "안전": (0.114, 0.604, 0.247)}
GREY = (0.6, 0.6, 0.6)

# 쪽마다 갈아 끼울 그림의 이름 — 단건 보고서는 2·3·4 면이 이격·야적·미등록증축 순이다.
SINGLE_FIGS = ("1_이격거리.png", "2_야적물.png", "3_미등록증축.png")
CMP_FIGS = ("sep_비교.png", "yard_비교.png", "led_비교.png")


def load(rel):
    """저장소 기준 상대경로로 값 파일을 읽는다."""
    return json.loads((ROOT / rel).read_text("utf-8"))


# ── 값 뽑기 ─────────────────────────────────────────────────────────────
def sep_by_dong(r):
    """{동 이름: [[이격 번호, 외부건물 번호, 방위, 거리, 판정], …]} — 손판의 표 그대로.

    **줄을 짜는 곳은 [[single.py]] `sep_dong_rows` 하나다.** 화면 보고서의 2면도 같은 함수에서
    나오므로 종이와 화면이 갈릴 수 없다 — 여기서는 그 줄을 손판의 칸 모양(글자 넷)으로 옮기기만
    한다. 예전에는 이 파일이 필지 밖·안을 각자 모아 동마다 갈라 담았고, 그래서 렌더러가 표
    모양을 바꿀 때 이쪽만 옛 모양으로 남았다.
    """
    site, L = r["site"], r["layers"]
    near = (r.get("context") or {}).get("buildings_near") or {"features": []}
    near = near["features"] if isinstance(near, dict) else near
    dong, ext = FR.sep_labels(r, near)
    res = (site.get("scene") or {}).get("res_m") or 0.5
    return {name: [[q["id"], q["no"], q["dir"], DR.dist_text(q["dist"], res_m=res),
                    FR.sep_lv(q["level"])[0]] for q in rows]
            for name, rows in FR.sep_dong_rows(L["separation"], dong, ext).items()}


# 1면 판정어의 색 — 항목마다 말이 다르다(이격 = 안전·주의·위험 / 야적 = 현장 확인 필요 /
# 대장 = 일치·불일치). 화면 보고서의 잉크와 같은 값이다([[single.py]] `SEP_DOC`·`MATCH_DOC`).
DOC_COLOR = dict(SEP_COLOR, **{
    "현장 확인 필요": SEP_COLOR["위험"], "안전": SEP_COLOR["안전"],
    "일치": SEP_COLOR["안전"], "불일치": SEP_COLOR["주의"], "판정 불가": GREY})


def result_rows(r, *, skip=()):
    """1면 「본 물건 분석 결과」 세 줄 — **화면 보고서와 같은 함수**로 뽑는다.

    문구를 여기 손으로 적어 두면 화면과 종이가 갈린다 — 실제로 갈렸다(2026-08-26: 종이는
    「서측 … 최소 이격 1.5 m」, 화면은 「북서 … 0.0 m」).
    """
    L, lvw = r["layers"], FR._ledger_view(r)
    _dong, ext = FR.sep_labels(r, FR._neighbors(r), skip=skip)
    rows = [["건물 이격거리", FR._sep_line(L["separation"], skip,
                                         DR.sep_hidden(L["separation"], ext, skip=skip)),
             FR.sep_lv(FR._sep_worst(L["separation"], skip=skip))[0]],
            ["야외 적재물", FR._yard_line(L["yard"]), FR._yard_lv(L["yard"])[0]],
            ["대장 정합(미등록·증축)", FR._led_line(lvw), FR.parcel_match(lvw)[0][0]]]
    return rows, [[None, None, DOC_COLOR.get(q[2])] for q in rows]


def overview_line(fx, r):
    """1면 「물건 개요」의 **건축물대장 줄**을 지금 값으로 맞춘다 — 화면과 같은 함수로 뽑는다.

    이 줄만 손대는 이유는 여기만 값에 따라 말이 달라지기 때문이다 — 대장에서 뺀 동이 있으면
    괄호가 붙는다(30 ㎡ 미만 부속 / 사람이 확인해 뺀 동). 그 사정이 종이에만 옛 말로 남으면
    같은 물건의 종이와 화면이 다른 동수를 설명하게 된다.

    「건축면적 합계」가 든 줄은 **둘**이고 표지로 가른다 — 대장 줄에는 「용도」가 있고 판독
    건물 줄에는 없다. 이미 맞으면 아무것도 하지 않는다.

    **판독 건물 줄도 같이 맞춘다**(2026-08-27). 예전에는 대장 줄만 고쳤는데, 그 값이 손판을
    만들 때와 늘 같았기 때문이다(같은 GT 로 뽑았으니까). 모델 경로 산출물에 이 손판을 쓰면
    그 전제가 깨진다 — 실측 호림동: 종이 1면이 「판독 2동 · 합계 **2,158 ㎡**」(손판을 만든
    GT 값)라고 말하는데 바로 밑 대조 줄은 「판독 1,995 ㎡」(모델 값)였다. 한 면에서 같은
    물건의 면적이 두 숫자로 적히는 것이라 그대로 둘 수 없다.
    """
    dong = DR.dong_names(r["layers"]["buildings"])
    rows = dict(FR.overview_rows(r, FR._ledger_view(r), dong))
    n = 0
    for key, has_use in (("건축물대장", True), ("위성 판독 건물", False)):
        want = rows.get(key)
        if not want:
            continue
        want = want.replace("  ·  ", " \xa0·\xa0 ").replace("   (", " \xa0(")
        for txt, _sp in list(fx.lines(0)):
            cur = txt.strip()
            if "건축면적 합계" in cur and ("용도" in cur) == has_use and cur != want:
                n += fx.edit_line(0, cur, want)
                break
    return n


OVERVIEW_DROP = ("분석 방법", "적재 구역 출처")


def drop_overview_rows(fx, labels=OVERVIEW_DROP):
    """1면 「물건 개요」 표에서 **그 이름의 줄을 지운다.** 지운 줄 수를 돌려준다.

    두 칸을 종이에서 뺐다(사용자 결정, 2026-08-27) — 「분석 방법」은 물건마다 달라지지 않는
    도구 사양이고([[report/single.overview_rows]]), 「적재 구역 출처」는 3면 적재 표 제목이
    이미 말하는 사실이다([[report/compare._overview]]). 화면 보고서는 이제 그 줄을 만들지
    않지만 **손판 PDF 에는 인쇄되어 남는다**(Chrome 인쇄본이라 다시 뽑을 수 없다).

    **맨 아랫줄만 지운다.** 두 줄은 개요 표의 끝에 얹혀 있었으므로 위쪽 경계선이 그대로 표의
    새 바닥이 되고 아래 덩어리를 밀 필요가 없다 — 지운 만큼 다음 절 앞의 흰 자리가 넓어질
    뿐이다. 가운데 줄이면 아래를 다 밀어야 하므로 그 길은 만들지 않고 **멈춘다.**

    지우는 범위는 **그 줄의 위 경계선 아래부터 아래 경계선 끝까지**다. 세로 테두리와 라벨
    칸 바탕이 그 안에 통째로 들어가야 redaction 이 선까지 걷어 낸다(`Refit.flush` 는 지우는
    자리에 **통째로 들어간** 선만 없앤다) — 위 경계선은 밖에 남으므로 살아서 새 바닥이 된다.
    """
    import fitz
    from sitecheck.report import pdf_refit as PR
    pg = fx.doc[0]
    bord = [r for r, f in PR._rects(pg) if PR._near(f, PR.BORDER) and r.height < 1.2]
    if not bord:
        return 0
    n = 0
    for label in labels:
        hit = next((sp for txt, sp in fx.lines(0) if txt.strip() == label), None)
        if hit is None:
            continue
        lx, ty = hit[0]["bbox"][0], hit[0]["bbox"][1]
        # 그 라벨 칸을 가로지르는 경계선만 본다 — 1면에는 표가 여럿이다.
        hz = [r for r in bord if r.x0 <= lx + 1 <= r.x1]
        above = [r for r in hz if r.y1 <= ty + 1]
        below = [r for r in hz if r.y0 >= ty + 1]
        if not (above and below):
            continue
        a = max(above, key=lambda r: r.y0)
        b = min(below, key=lambda r: r.y0)
        rh = b.y0 - a.y0
        if [r for r in hz if b.y0 + rh * 0.5 < r.y0 < b.y0 + rh * 1.6]:
            raise SystemExit(f"1면 개요 「{label}」 이 맨 아랫줄이 아니다 — 아래를 밀어야 한다")
        # **가로 폭은 `hz` 가 아니라 경계선 전체에서 잰다.** 경계선은 칸마다 토막나 있어
        # (라벨 칸 42.75~155.25 · 값 칸 155.25~552.75) `hz` 로 재면 라벨 칸만 지워지고
        # 값 글자와 오른쪽 테두리가 남는다 — 실측 2026-08-27 에 그렇게 나왔다.
        edge = [r for r in bord
                if abs(r.y0 - a.y0) < 1.0 or abs(r.y0 - b.y0) < 1.0]
        x0, x1 = min(r.x0 for r in edge), max(r.x1 for r in edge)
        fx.erase(pg, fitz.Rect(x0 - 0.6, a.y1 + 0.02, x1 + 0.6, b.y1 + 0.02))
        n += 1
    return n


def set_check(fx, r, near=(), *, skip=()):
    """1면 상단 「확인 필요 항목」 두 줄 — 총계와 내역을 지금 셈으로 맞춘다.

    **이미 맞으면 아무것도 하지 않는다**(`once` 와 같은 규약). 찾을 글자를 손으로 적지 않고
    **모양으로** 찾는다 — 한 번 고친 판에서 옛 글자가 없어 죽지 않게.
    """
    dong, ext = FR.sep_labels(r, near, skip=skip)
    t = FR._tally(r["layers"], FR._ledger_view(r), dong, ext, skip=skip)
    want = {r"^\d+건$": f"{t['n_check']}건",
            r"^이격거리 \d+ · 대장 정합 \d+ · 야외 적재물 \d+$":
                f"이격거리 {t['n_sep']} · 대장 정합 {t['n_led']} · 야외 적재물 {t['n_yard']}"}
    n = 0
    for txt, _sp in list(fx.lines(0)):
        cur = txt.strip()
        for pat, new in want.items():
            if re.match(pat, cur) and cur != new:
                n += fx.edit_line(0, cur, new)
    return n


def sep_counts(r):
    """1면 결과 줄이 적는 (위험, 주의) 건수 — 화면 보고서와 **같은 함수**로 센다
    ([[single.py]] `_sep_line`)."""
    fs = [f["properties"] for f in DR.sep_pairs(r["layers"]["separation"])]
    return (sum(1 for p in fs if DR.sep_level3(p.get("level")) == "위험"),
            sum(1 for p in fs if DR.sep_level3(p.get("level")) == "주의"))


def yard_rows(r):
    """3면 적재 표의 줄 — **화면 보고서와 같은 말**을 쓴다([[single.py]] `_zone_lv`).

    구역이 0 곳이면 가운데 칸에 「탐지된 적재 구역 없음」, 판정 칸에는 **판정어**(「안전」)를
    적는다 — 판정 칸에 판정 기준 표에 없는 말이 들어가면 그 칸이 무엇을 재는지 흐려진다.
    """
    ys = r["layers"]["yard"]["features"]
    if not ys:
        return ([["—", "탐지된 적재 구역 없음", "안전"]],
                [[None, None, SEP_COLOR["안전"]]])
    rows, cols = [], []
    for p in (f["properties"] for f in ys):
        word = FR._zone_lv(p.get("level"))[0]
        rows.append([p["yard_id"], f'{p["dist_to_building_m"]:.1f} m', word])
        cols.append([None, None, SEP_COLOR.get(word, GREY)])
    return rows, cols


def _span(q, res):
    """1차·2차 칸 — 「22.7 m · 안전」. 한 칸 안에서 색이 갈리므로 조각으로 낸다."""
    if q is None:
        return "—"
    word = FR.sep_lv(q["level"])[0]
    return [(f"{DR.dist_text(q['dist'], res_m=res)} · ", INK), (word, SEP_COLOR.get(word))]


def cmp_rows(t1, t2, dongs=None):
    """비교분석 이격 표 — [번호, 방위, 1차, 2차, 변화 여부].

    **짝짓기는 [[compare.py]] `sep_change_rows` 가 한다** — 번호·방위로 맞춘다. 예전에는 여기서
    두 날짜의 줄을 자리로 `zip` 했는데, 한쪽에만 있는 구간이 생기면 그 뒤가 통째로 밀렸다
    (실측 2026-08-26 호산동 702-5: 1차 8줄 · 2차 7줄에서 「③ 동 15.9 m」가 2차의 「③ 남
    4.9 m」와 짝지어져 종이가 없는 변화를 말했다).
    """
    from sitecheck.report import compare as CMP
    res = (t1["site"].get("scene") or {}).get("res_m") or 0.5
    out = {}
    for name, pairs in CMP.sep_change_rows(t1, t2).items():
        if dongs and name not in dongs:
            continue
        rows, cols = [], []
        for q1, q2 in pairs:
            chg = FR._cell(CMP._sep_chg(q1, q2))[0]
            rows.append([CMP.row_no(q1, q2), (q1 or q2)["dir"],
                         _span(q1, res), _span(q2, res), chg])
            cols.append([None, None, None, None,
                         INK if chg != "변화 없음" else GREY])
        out[name] = (rows, cols)
    return out


# ── 고치기 ──────────────────────────────────────────────────────────────
def colorize(rows, verdict_col=3):
    """판정 칸만 그 판이 쓰던 색으로. 나머지는 먹색."""
    tail = lambda r: [None] * (len(r) - verdict_col - 1)          # noqa: E731
    return [[None] * verdict_col + [SEP_COLOR.get(r[verdict_col])] + tail(r)
            for r in rows]


def fit_table(fx, t, rows, colors=None):
    """표를 **지금 값의 줄 수**에 맞춘다 — 늘면 원본 두께로 행을 잇고, 줄면 남는 행을 지운다.
    돌려주는 것은 그 표 아래 덩어리를 밀 양(pt)이다(늘면 +, 줄면 −).

    **몇 번 돌려도 같은 결과다** — 줄 수를 손으로 적어 둔 원본 수가 아니라 **지금 PDF 에서
    재기** 때문이다. 다섯 부는 한 번 고친 PDF 위에서 다시 돌아가므로 그래야 한다.

    **열 수가 다르면 멈춘다.** `write_row` 는 `zip(칸, 글자)` 라 남는 글자를 **말없이 버린다**
    — 화면 보고서의 표에 열이 하나 늘면(2026-08-27 이격 표: 넷 → 다섯) 손판은 판정 칸을
    잃은 채 글자만 한 칸씩 밀려 그럴듯하게 인쇄된다. 손판은 Chrome 인쇄본이라 열을 늘릴 수
    없으므로, 그때는 **종이를 다시 뽑아야 한다**고 말하고 멈추는 것이 맞다.
    """
    want = max((len(r) for r in rows), default=0)
    if want > len(t.cols):
        raise SystemExit(
            f"손판의 표는 {len(t.cols)}열인데 지금 값은 {want}열이다 — 화면 보고서에서 열이"
            f" 늘었다. 손판(Chrome 인쇄본)은 열을 못 늘리므로 그 PDF 를 다시 뽑아야 한다.")
    cols = colors or [colorize([r])[0] for r in rows]
    add = len(rows) - len(t.row_tops)
    if add > 0:
        fx.grow(t, add)
    elif add < 0:
        # 자르는 자리는 **경계선 아래**부터다 — `row_tops[i]` 는 그 경계선 사각형이 시작하는
        # y 라(선 두께 0.75) 거기서 지우면 남길 마지막 줄의 밑줄이 같이 지워진다.
        fx.erase(fx.doc[t.page], (t.cols[0].x0 - 1, t.row_tops[len(rows)] + 0.9,
                                  t.cols[-1].x1 + 1, t.bottom + 1.5))
        del t.row_tops[len(rows):]
    for i, row in enumerate(rows):
        fx.write_row(t, i, row, colors=cols[i])
    return add * t.row_h


def has(fx, page_no, text):
    """그 쪽에 이 글자가 아직 있나."""
    return any(text in txt for txt, _sp in fx.lines(page_no))


def once(fx, page_no, old, new, **kw):
    """**옛 값이 남아 있을 때만** 갈아 끼운다 — 이미 고친 판에서 다시 돌려도 죽지 않는다
    (`edit_line` 은 못 찾으면 `LookupError` 를 던진다)."""
    return fx.edit_line(page_no, old, new, **kw) if has(fx, page_no, old) else 0


def set_counts(fx, page_no, danger, warn):
    """1면 결과 줄의 「위험 N건 · 주의 M건」을 지금 셈으로 맞춘다.

    **이미 맞으면 아무것도 하지 않는다** — 찾을 글자를 손으로 적어 두면(옛 코드는 「위험 7건 ·
    주의 0건」을 찾았다) 한 번 고친 PDF 에서 그 글자가 없어 `LookupError` 로 죽는다.
    """
    want = f"위험 {danger}건 · 주의 {warn}건"
    for txt, _sp in fx.lines(page_no):
        m = re.search(r"위험 \d+건 · 주의 \d+건", txt)
        if m and m.group(0) != want:
            return fx.edit_line(page_no, m.group(0), want)
    return 0


def retext(fx, page_no, want, *, xrange=None, only_if=None):
    """쪽의 낱말을 **자리로 골라** 갈아 끼운다. `want` 는 `{옛 글자: 새 글자}`. 바꾼 수를 돌려준다.

    `edit_line` 은 글자로만 찾으므로 **같은 글자가 여러 칸에 있으면** 못 가른다 — 대장 표는
    「판독 동」 칸과 「대장 동」 칸에 둘 다 `A동` 이 있다. `xrange` 로 열을 집으면 갈린다
    (실측 신당동 비교분석 4면: 판독 동 x 61.4 · 대장 동 x 101.3).

    **동시에 바꾼다.** 먼저 다 찾아 놓고 그 다음에 쓰므로 「C동→A동, A동→B동」처럼 이름이
    자리를 맞바꿔도 두 번 잡히지 않는다.

    `only_if` 는 **아직 안 바꾼 판에만 있는 글자**다 — 그것이 없으면 아무것도 안 한다. 바꾼
    뒤에는 새 이름이 옛 이름의 자리를 차지하므로(A동 이 둘) 이 표지가 없으면 다시 돌릴 때
    또 바꾼다.
    """
    import pymupdf as fitz
    hit = []
    for blk in fx.doc[page_no].get_text("dict")["blocks"]:
        if blk.get("type") != 0:
            continue
        for ln in blk["lines"]:
            t = "".join(sp["text"] for sp in ln["spans"]).strip()
            b = ln["bbox"]
            if xrange and not (xrange[0] <= b[0] <= xrange[1]):
                continue
            if t in want or t == only_if:
                hit.append((t, ln))
    if only_if is not None and not any(t == only_if for t, _ in hit):
        return 0
    page = fx.doc[page_no]
    n = 0
    for t, ln in hit:
        if t not in want:
            continue
        sp = ln["spans"][0]
        b = fitz.Rect(ln["bbox"])
        fx.erase(page, (b.x0 - 0.8, b.y0 - 0.8, b.x1 + 0.8, b.y1 + 0.8))
        fx.text(page, want[t], x=sp["origin"][0], y=sp["origin"][1],
                size=sp["size"], color=fx.color_of(sp), bold=fx.is_bold(sp))
        n += 1
    return n


# ── 그림 ────────────────────────────────────────────────────────────────
# **픽셀이 아니라 놓인 자리(pt)로 가른다.** 본문 도면은 폭 470 pt 쯤, 머리글 로고는 84 pt 다.
#
# 예전에는 그림의 **픽셀 폭**으로 갈랐는데(<200 px 면 로고), 그러면 로고를 큰 그림으로 갈아
# 끼운 순간 그 로고가 다음 실행에서 「본문 도면」으로 분류된다 — 실측 2026-08-25: 워드마크를
# 694×124 캔버스로 넣은 뒤 다시 돌렸더니 **네 부의 머리글에 위성사진이 들어갔다**(이름 셋이
# 한 칸씩 밀렸다). 놓인 자리는 내용 스트림이 정하는 것이라 무엇을 넣어도 안 변하므로, 그것으로
# 가르면 몇 번을 돌려도 같다.
MIN_FIG_PT = 200.0        # 놓인 자리가 이보다 좁으면 본문 도면이 아니다(로고)


def _figs(fx):
    """쪽마다 **실제로 그려지는** 큰 그림 하나. 작은 로고는 건너뛴다.

    **`get_images` 가 아니라 `get_image_info` 를 쓴다.** 앞엣것은 쪽의 자원 목록이라 예전
    갈아 끼우기가 남긴, 그려지지도 않는 항목까지 센다 — 실측 호림동 3-10 은 3면 자원에 넷이
    있었고(129 가 셋, 646 하나) 실제로 그려지는 것은 129 하나뿐이었다.

    그 차이가 **그림을 엉뚱한 면에 넣었다.** 목록이 [p1·p2·p2·p2·p2·p3·p3] 로 나오는데 이름
    셋과 앞에서부터 짝지으므로, 세 번째 이름(`3_미등록증축`)이 p3 이 아니라 **p2 의 같은
    xref 에** 들어갔다. 그래서 저장소에 담겨 있던 호림동 보고서는 **3면(야외 적재물) 자리에
    미등록증축 그림**이 실려 있었다(2026-08-24 발견 · 호산동·고잔동은 자원이 깨끗해 멀쩡했다).

    실제로 그려지는 것만 세면 쪽마다 하나씩 나오고, 갈아 끼우기도 그 하나에만 걸린다 —
    덤으로 쓸데없는 `replace_image` 호출이 없어져 파일이 더 붓지 않는다.
    """
    out = []
    for i, page in enumerate(fx.doc):
        seen = set()
        for q in page.get_image_info(xrefs=True):
            x, b = q.get("xref"), q.get("bbox")
            if not x or x in seen or not b or (b[2] - b[0]) < MIN_FIG_PT:
                continue
            seen.add(x)
            out.append((i, x))
    return out


def swap(fx, rel, names=SINGLE_FIGS):
    """쪽 순서대로 그림을 갈아 끼운다. `rel` 은 저장소 기준 폴더."""
    for (pno, xref), nm in zip(_figs(fx), names):
        fx.swap_image(pno, xref, str(ROOT / rel / nm))


def _logo_xref(fx):
    """머리글 로고 — **작은 그림**이다(큰 것은 본문 도면). (쪽, xref, 놓인 자리) 를 돌려준다.

    쪽마다 하나씩 있지만 **xref 는 여섯 쪽이 함께 쓴다**(실측) — 한 번만 갈아 끼우면 전부
    바뀐다. 놓인 자리는 쪽마다 조금씩 다를 수 있어(1면만 15.7pt · 나머지 15.0pt) 가장 흔한
    가로세로비를 쓴다.
    """
    hits = []
    for i, page in enumerate(fx.doc):
        for q in page.get_image_info(xrefs=True):
            b = q.get("bbox")
            if q.get("xref") and b and 0 < (b[2] - b[0]) < MIN_FIG_PT:
                hits.append((i, q["xref"], (b[2] - b[0]), (b[3] - b[1])))
    if not hits:
        return None
    from collections import Counter
    ratio = Counter(round(w / h, 2) for _i, _x, w, h in hits if h).most_common(1)[0][0]
    pno, xref, _w, _h = hits[0]
    return pno, xref, ratio


def swap_logo(fx, png=None):
    """머리글 로고를 갈아 끼운다. 바꿨으면 True.

    **가로세로비가 다르면 늘어난다.** PDF 안에서 그림이 놓이는 사각형은 내용 스트림이 정한
    것이라 그림만 바꿔서는 안 움직인다 — 옛 로고(구(舊) 로고, 5.4:1)를 새 로고
    (고객사 워드마크만, 3.5:1)로 그냥 바꾸면 가로로 늘어난다. 그래서 **원래 사각형과 같은
    비율의 흰 판**을 만들어 그 위에 새 로고를 **오른쪽 끝에 맞춰** 얹는다. 머리글 바탕이
    순백이라(실측) 남는 왼쪽은 보이지 않고, 오른쪽 끝은 본문 여백선에 그대로 선다.

    알파는 흰 바탕에 합성해서 없앤다 — 원본 로고도 SMask 없는 불투명 RGB 였다.
    """
    import tempfile

    from PIL import Image
    png = Path(png or (ROOT / "assets" / "brand" / "client_logo.png"))
    got = _logo_xref(fx)
    if got is None or not png.exists():
        return False
    pno, xref, ratio = got
    logo = Image.open(png).convert("RGBA")
    h = logo.height
    canvas = Image.new("RGBA", (max(logo.width, int(round(h * ratio))), h), (255, 255, 255, 255))
    canvas.alpha_composite(logo, (canvas.width - logo.width, 0))
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as t:
        canvas.convert("RGB").save(t.name)
        fx.swap_image(pno, xref, t.name, keep_size=False)
    return True


# 손판 머리글을 신판 형식으로 — 값은 [[single.py]] 가 정하는 것을 그대로 가져온다.
RULE_RGB = tuple(int(FR.RULE.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
RULE_PT = FR.RULE_H_MM * 72 / 25.4                      # 밑줄 두께
GAP_PT = (FR.RULE_TOP_MM - FR.LOGO_TOP_MM - FR.LOGO_H_MM) * 72 / 25.4   # 로고 아래 → 밑줄


def swap_bar(fx, png=None):
    """전폭 남색 띠를 **로고 폭 밑줄**로 바꾼다. 바꾼 쪽 수를 돌려준다.

    손으로 만든 판은 「지반침하 위험 보고서 샘플」의 **구판** 형식이라 도련까지 닿는 남색 띠를
    쓴다. 사용자가 준 **신판**(주의·누적구역)은 **로고 폭만큼의 얇은 밝은 파란 밑줄**이다 —
    화면(HTML)은 [[single.py]] 가 이미 신판으로 그리므로, 종이도 같은 얼굴이어야 한다.

    **세로 자리는 로고에서 잰다.** 손판의 머리글은 우리 렌더러보다 아래에 앉아 있어(로고 위
    31.5 pt vs 4.37 mm) 절대 좌표를 옮겨 쓸 수 없다. 대신 신판이 지키는 **관계**를 옮긴다 —
    밑줄은 로고 아래 `GAP_PT`, 두께 `RULE_PT`, 오른쪽 끝은 로고와 같다.

    **폭도 로고에서 잰다.** 로고가 놓인 사각형이 아니라 **그 안에서 실제로 보이는 워드마크**의
    폭이다(`swap_logo` 가 원래 비율을 지키려고 왼쪽을 흰 여백으로 채우므로 상자가 더 넓다).
    """
    import pymupdf as fitz
    from PIL import Image
    png = Path(png or (ROOT / "assets" / "brand" / "client_logo.png"))
    aspect = (lambda im: im.width / im.height)(Image.open(png)) if png.exists() else 3.5
    n = 0
    for page in fx.doc:
        logo = None
        for q in page.get_image_info(xrefs=True):
            b = q.get("bbox")
            if b and 0 < (b[2] - b[0]) < MIN_FIG_PT:
                logo = b
        if logo is None:
            continue
        bar = None
        for dr in page.get_drawings():
            r = dr["rect"]
            if dr.get("fill") and r.y0 < 120 and (r.x1 - r.x0) > 300 and (r.y1 - r.y0) < 8:
                bar = r
        if bar is not None:                      # 이미 바꾼 판이면 띠가 없다 — 그냥 지나간다
            fx.erase(page, fitz.Rect(bar.x0 - 1, bar.y0 - 1, bar.x1 + 1, bar.y1 + 1))
        # **이미 그은 밑줄 자리도 한 번 지운다** — 두 번 돌려도 겹쳐 굵어지지 않게.
        w = (logo[3] - logo[1]) * aspect
        y0 = logo[3] + GAP_PT
        fx.erase(page, fitz.Rect(logo[2] - w - 1, y0 - 1, logo[2] + 1, y0 + RULE_PT + 1))
        fx.fill(page, fitz.Rect(logo[2] - w, y0, logo[2], y0 + RULE_PT), RULE_RGB)
        n += 1
    return n


def _same_color(c, want=None, tol=1e-3):
    """색이 같은가 — **어림으로 본다.** `color_of` 는 소수 넷째 자리에서 반올림하므로
    그대로 견주면 방금 우리가 칠한 것도 「다르다」가 되어, 두 번째 실행이 또 칠한다."""
    want = RULE_RGB if want is None else want
    return c is not None and len(c) == len(want) and all(abs(a - b) <= tol
                                                         for a, b in zip(c, want))


def blue_bullets(fx, mark="■"):
    """절 제목의 **글머리 기호 ■ 만** 밑줄과 같은 파랑으로 다시 그린다. 바꾼 개수를 돌려준다.

    샘플 신판은 ■ 를 `(0, 60, 220)`, 뒤 글자를 진회색으로 쓴다 — 우리 손판은 둘 다 먹색
    `(34,34,34)` 이었다. ■ 는 제 몫의 span 이라(뒤 글자와 x 가 떨어져 있다) 그 자리만 지우고
    같은 자리·같은 크기로 다시 앉히면 된다([[pdf_refit.py]] `move_spans` 와 같은 수법).

    **이미 파란 것은 건너뛴다** — 몇 번을 돌려도 같다.
    """
    import pymupdf as fitz
    n = 0
    for page in fx.doc:
        hits = []
        for blk in page.get_text("dict")["blocks"]:
            if blk.get("type") != 0:
                continue
            for ln in blk["lines"]:
                for sp in ln["spans"]:
                    if sp["text"].strip() == mark and not _same_color(fx.color_of(sp)):
                        hits.append(sp)
        for sp in hits:
            b = fitz.Rect(sp["bbox"])
            fx.erase(page, (b.x0 - 0.6, b.y0 - 0.6, b.x1 + 0.6, b.y1 + 0.6))
            fx.text(page, mark, x=sp["origin"][0], y=sp["origin"][1],
                    size=sp["size"], color=RULE_RGB, bold=fx.is_bold(sp))
            n += 1
    return n


# ── 범례 ────────────────────────────────────────────────────────────────
def _hex(c):
    return tuple(int(str(c).lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))


def read_legend(page):
    """그림 바로 아래 **범례 띠**를 읽는다 → `(기하, [이름, …])`. 없으면 None.

    띠는 「색칸 + 이름」이 가로로 늘어선 한 줄이고, 큰 그림 바로 아래에 붙는다. 기하(칸 크기 ·
    글자 크기 · 사이 간격 · 왼쪽 끝)를 **원본에서 재서** 다시 그릴 때 그대로 쓴다 — 숫자로
    적어 두면 손판마다 다른 값을 하나로 뭉개게 된다(단건은 그림 왼끝 124.5, 비교분석은 여백
    42.8 에서 시작한다).
    """
    imgs = [q["bbox"] for q in page.get_image_info(xrefs=True)
            if (q["bbox"][2] - q["bbox"][0]) >= MIN_FIG_PT]
    if not imgs:
        return None
    ybot = max(b[3] for b in imgs)
    chips = []
    for dr in page.get_drawings():
        r, f = dr["rect"], dr.get("fill")
        # **흰 칸은 색칸이 아니다** — 절 제목 ■ 뒤에 깔린 바탕이 같은 크기로 잡힌다.
        if (f and sum(f) / 3 < 0.98 and ybot < r.y0 < ybot + 40
                and 4 < (r.x1 - r.x0) < 30 and 4 < (r.y1 - r.y0) < 30):
            chips.append(r)
    if not chips:
        return None
    # **가장 위 한 줄만.** 아래에는 절 제목이 있고, 그 ■ 도 같은 크기의 사각형이다.
    y0 = min(r.y0 for r in chips)
    chips = [r for r in chips if abs(r.y0 - y0) < 2]
    y1 = max(r.y1 for r in chips)
    rows = []
    for blk in page.get_text("dict")["blocks"]:
        if blk.get("type") != 0:
            continue
        for ln in blk["lines"]:
            b = ln["bbox"]
            if y0 - 3 <= b[1] <= y1 + 3:
                rows.append(ln)
    if not rows:
        return None
    rows.sort(key=lambda ln: ln["bbox"][0])
    sp0 = rows[0]["spans"][0]
    left = min(r.x0 for r in chips)
    # 「색칸 → 이름」 · 「이름 → 다음 색칸」 사이는 원본에서 잰다.
    ct = rows[0]["bbox"][0] - min(r.x1 for r in chips if r.x0 == left)
    ee = 11.5
    if len(rows) > 1:
        ee = rows[1]["bbox"][0] - rows[0]["bbox"][2] - (chips[0].x1 - chips[0].x0) - ct
    geo = {"left": left, "y0": y0, "cw": chips[0].x1 - chips[0].x0,
           "ch": chips[0].y1 - chips[0].y0, "size": sp0["size"],
           "color": Refit_color(sp0), "base": sp0["origin"][1],
           "ct": max(2.0, ct), "ee": max(6.0, ee),
           "right": max(ln["bbox"][2] for ln in rows)}
    names = ["".join(sp["text"] for sp in ln["spans"]).strip() for ln in rows]
    return geo, names


def Refit_color(span):
    c = span["color"]
    return tuple(round(((c >> k) & 0xFF) / 255, 4) for k in (16, 8, 0))


def fix_legend(fx, page_no, entries):
    """범례를 **코드가 내는 것**으로 다시 그린다. 고쳤으면 True, 이미 같으면 False.

    `entries` 는 `[(이름, "#rrggbb"), …]` — 보고서 렌더러가 그림과 **같은 팔레트**에서 내는
    값이다([[draw.py]] `yard_legend` 등). 손판의 범례는 그 팔레트가 바뀌기 전에 찍힌 것이라
    그림과 갈릴 수 있다 — 실측 2026-08-25: 고잔동 3면은 「목재·팔레트 / 그 밖의 적치물」 두
    색이라 적혀 있는데 그림은 **한 색**으로 그린다(적재 구역의 종류별 색은 2026-08-23 에
    걷어 냈다. 종류는 표에서 읽는다). 호림동 2면은 「주의」 칸이 통째로 빠져 있어, 그림의
    주황색 측정선이 무엇인지 종이가 말하지 못했다.

    **이름이 이미 같으면 손대지 않는다** — 몇 번을 돌려도 같다.

    아주 밝은 색칸에는 원본처럼 **가는 회색 테**를 두른다(「외부 건물(점선)」의 #dee4ec 는
    흰 종이에서 테 없이는 안 보인다).
    """
    import pymupdf as fitz
    page = fx.doc[page_no]
    got = read_legend(page)
    if not got:
        return False
    geo, names = got
    want = [n for n, _c in entries]
    if names == want:
        return False
    fx.erase(page, fitz.Rect(geo["left"] - 1.5, geo["y0"] - 2.5,
                             max(geo["right"], geo["left"]) + 3, geo["y0"] + geo["ch"] + 2.5))
    x = geo["left"]
    for name, col in entries:
        rgb = _hex(col)
        r = fitz.Rect(x, geo["y0"], x + geo["cw"], geo["y0"] + geo["ch"])
        fx.fill(page, r, rgb)
        if sum(rgb) / 3 > 0.85:                       # 아주 밝으면 테를 두른다
            t = 0.8
            for e in (fitz.Rect(r.x0, r.y0, r.x1, r.y0 + t),
                      fitz.Rect(r.x0, r.y1 - t, r.x1, r.y1),
                      fitz.Rect(r.x0, r.y0, r.x0 + t, r.y1),
                      fitz.Rect(r.x1 - t, r.y0, r.x1, r.y1)):
                fx.fill(page, e, (0.6, 0.6, 0.6))
        tx = x + geo["cw"] + geo["ct"]
        fx.text(page, name, x=tx, y=geo["base"], size=geo["size"], color=geo["color"])
        x = tx + face(False).text_length(name, geo["size"]) + geo["ee"]
    return True


def legends_from_html(html_path):
    """화면(HTML)이 낸 **면별 범례** → `{쪽번호: [(이름, 색), …]}`.

    **왜 HTML 에서 읽나.** 범례는 그림을 그린 팔레트에서 그대로 나오므로([[draw.py]]), 화면과
    같아지면 종이도 그림과 맞는다. 값에서 다시 뽑으면 「어느 함수가 정답인가」가 한 벌 더
    생기고(단건은 `_sep_legend`·`yard_legend`·`_led_legend`, 비교분석은 두 날짜를 합친 것)
    그 두 벌이 갈리는 순간 종이가 또 어긋난다.

    HTML 은 `hand_writting.py` 가 종이를 고치기 **직전에** 새로 내므로 늘 최신이다.
    """
    import html as _html
    s = Path(html_path).read_text("utf-8")
    out = {}
    for i, pg in enumerate(s.split('<section class="page">')[1:]):
        m = re.search(r'<p class="legend">(.*?)</p>', pg, re.S)
        if m:
            out[i] = [(_html.unescape(n).strip(), c) for c, n in
                      re.findall(r'<i style="background:([^"]+)"></i>([^<]*)', m.group(1))]
    return out


def fix_legends(fx, html_path, *, verbose=True):
    """그 보고서의 모든 면에서 범례를 화면과 맞춘다. 고친 면 목록을 돌려준다."""
    done = []
    for pno, entries in legends_from_html(html_path).items():
        if pno < fx.doc.page_count and fix_legend(fx, pno, entries):
            done.append(pno + 1)
    if done and verbose:
        print(f"    범례를 화면과 맞춘 면: {' · '.join(f'{n}면' for n in done)}")
    return done


# ── 확인 ────────────────────────────────────────────────────────────────
def flat(cell):
    """조각(글자,색) 목록을 글자열로 — 고친 PDF 에서 읽어 낸 것과 견주려고."""
    if isinstance(cell, str) or cell is None:
        return cell
    return "".join(t for t, _ in cell)


def figs_ok(pdf, figdir, names=SINGLE_FIGS):
    """**어느 그림이 어느 면에 실렸나**를 픽셀로 확인한다. 어긋난 (면, 실린 것) 목록을 돌려준다.

    표만 대조하면 그림이 엉뚱한 면에 들어간 것을 못 잡는다 — 실제로 못 잡았다(호림동 3면).
    그래서 쪽마다 실린 그림을 뽑아 `figdir` 의 세 장 중 어느 것과 가장 가까운지 재고, 그것이
    그 면에 와야 할 것과 다르면 적는다. 값이 아니라 **픽셀**로 재므로 고치는 코드와 다른 길이다.
    """
    import io

    import numpy as np
    import pymupdf as fitz
    from PIL import Image
    refs = {}
    for nm in names:
        q = Path(figdir) / nm
        if q.exists():
            refs[nm] = Image.open(q).convert("RGB")
    if len(refs) < len(names):
        return [("재료 그림이 모자라 확인 못 함", str(figdir))]
    bad = []
    with fitz.open(pdf) as d:
        for pno, want in enumerate(names, start=1):
            info = [q for q in d[pno].get_image_info(xrefs=True)
                    if q.get("bbox") and (q["bbox"][2] - q["bbox"][0]) >= MIN_FIG_PT]
            if not info:
                bad.append((pno + 1, "그림 없음"))
                continue
            got = Image.open(io.BytesIO(d.extract_image(info[0]["xref"])["image"])).convert("RGB")
            best, score = None, None
            for nm, ref in refs.items():
                v = float(np.abs(np.asarray(got, dtype=int)
                                 - np.asarray(ref.resize(got.size, Image.LANCZOS),
                                              dtype=int)).mean())
                if score is None or v < score:
                    best, score = nm, v
            if best != want:
                bad.append((pno + 1, f"{want} 자리에 {best}"))
    return bad


def logo_ok(pdf, png=None, tol=6.0):
    """머리글 로고가 지금 자산인가 — 픽셀로 잰다. 어긋나면 사유를, 맞으면 빈 문자열을 돌려준다.

    `swap_logo` 는 자산을 **오른쪽 끝에 맞춘 흰 판**으로 넣으므로, 넣은 그림의 오른쪽 끝을
    자산과 같은 크기로 잘라 견준다.
    """
    import io

    import numpy as np
    import pymupdf as fitz
    from PIL import Image
    png = Path(png or (ROOT / "assets" / "brand" / "client_logo.png"))
    if not png.exists():
        return f"자산이 없다: {png}"
    want = Image.open(png).convert("RGBA")
    flat = Image.new("RGB", want.size, (255, 255, 255))
    flat.paste(want, mask=want.split()[-1])
    with fitz.open(pdf) as d:
        for page in d:
            for q in page.get_image_info(xrefs=True):
                b = q.get("bbox")
                if not (b and 0 < (b[2] - b[0]) < MIN_FIG_PT):
                    continue
                got = Image.open(io.BytesIO(d.extract_image(q["xref"])["image"])).convert("RGB")
                w = round(got.height * flat.width / flat.height)
                crop = got.crop((max(0, got.width - w), 0, got.width, got.height))
                ref = flat.resize(crop.size, Image.LANCZOS)
                v = float(np.abs(np.asarray(crop, dtype=int)
                                 - np.asarray(ref, dtype=int)).mean())
                return "" if v <= tol else f"평균차 {v:.1f} (허용 {tol})"
    return "로고를 못 찾았다"


def verify(recipes, figs=()):
    """**고친 뒤 다시 읽어** 우리 값과 같은지 본다 — 고치는 코드와 다른 길로 잰다.

    표(`fit_table` 이 쓴 줄)와 그림(`swap` 이 넣은 장) 둘 다 본다. `figs` 는
    `(pdf 상대경로, 재료 폴더, 이름들)` 목록이다.
    """
    from sitecheck.report import pdf_refit as PR
    bad = 0
    for pdf, figdir, names in figs:
        wrong = figs_ok(ROOT / pdf, ROOT / figdir, names)
        print(f"· 그림 자리 {pdf}")
        if wrong:
            bad += len(wrong)
            for pg, why in wrong:
                print(f"    틀림 {pg}면 — {why}")
        else:
            print(f"    OK  {len(names)}면 다 제자리")
        why = logo_ok(ROOT / pdf)
        print(f"    {'OK  머리글 로고' if not why else '틀림 머리글 로고 — ' + why}")
        if why:
            bad += 1
        # **범례가 화면과 같은가** — 표만 보던 동안 고잔동 3면은 그림이 한 색인데 종이는
        # 「목재·팔레트 / 그 밖의 적치물」 두 색이라 적고 있었다(2026-08-25 발견).
        html = ROOT / str(pdf).replace(".pdf", ".html")
        if html.exists():
            want = legends_from_html(html)
            wrong = []
            import pymupdf as fitz
            with fitz.open(ROOT / pdf) as d:
                for pno, entries in want.items():
                    if pno >= d.page_count:
                        continue
                    got = read_legend(d[pno])
                    names = got[1] if got else None
                    if names != [n for n, _c in entries]:
                        wrong.append((pno + 1, names, [n for n, _c in entries]))
            if wrong:
                bad += len(wrong)
                for pg, got, wnt in wrong:
                    print(f"    틀림 {pg}면 범례 — 종이 {got} · 화면 {wnt}")
            else:
                print(f"    OK  범례 {len(want)}면 다 화면과 같다")
    for fn in recipes:
        pdf, plan = fn(True)                       # check 모드로 「무엇이 되어야 하나」만 받는다
        fx = PR.Refit(str(ROOT / pdf))
        tabs = [t for i in sorted(fx.tables) for t in fx.tables[i]]
        print("·", pdf)
        for title, _, now in plan:
            if not (now and isinstance(now[0], list)):
                continue                            # 줄 단위 고침은 표가 아니다
            want = [[flat(c) for c in row] for row in now]
            hit = [t for t in tabs if [[c or "" for c in r] for r in t.rows_text]
                   == [[(c or "").replace(" ", " ") for c in r] for r in want]]
            ok = bool(hit)
            if not ok:                              # 공백 차이를 무시하고 한 번 더
                norm = lambda rs: [[re.sub(r"\s+", "", c or "") for c in r] for r in rs]   # noqa: E731
                hit = [t for t in tabs if norm(t.rows_text) == norm(want)]
                ok = bool(hit)
            print(f"    {'OK ' if ok else '틀림'} {title}")
            if not ok:
                bad += 1
                for r in want:
                    print("        바라는 줄", r)
    print("맞지 않는 표", bad, "개")
    return bad
