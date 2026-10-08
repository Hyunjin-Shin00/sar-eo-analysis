"""손으로 만든 보고서 PDF 의 **판짜기는 그대로 두고 값·그림만** 우리 산출물로 맞춘다.

왜 이 도구가 있는가
-------------------
`demo/` · `demo_cmp/` 에 든 보고서 PDF 는 이 저장소가 뽑은 것이 아니다 — 화면설계서에
맞춰 **손으로 다듬은 판**을 브라우저에서 인쇄한 것이고, 그 판을 내는 코드는 여기 없다.
그래서 값이 바뀔 때마다 다시 뽑을 수가 없다. 그렇다고 저장소 렌더러로 새로 내면 판이
달라진다. 남는 길은 **있는 PDF 안에서 글자와 그림만 갈아 끼우는 것**이다.

그게 가능한 이유
----------------
* 글꼴이 **Noto Sans CJK KR** 이고 같은 글꼴이 이 기계에 있다. 같은 크기로 다시 앉히면
  글자 상자가 0.01 pt 까지 원본과 겹친다(`selftest` 로 재 볼 수 있다).
* 표가 규칙적이다 — 열은 머리행 칸 사각형이, 행은 테두리 선이 정확히 알려 준다. 그래서
  자리를 **재서** 쓰지 손으로 적어 두지 않는다. 판이 조금 달라도 따라간다.
* 그림은 우리 `report/*.png` · `*_비교.png` 를 그대로 넣은 것이라 XObject 만 바꾸면 된다.

무엇을 건드리지 않는가
----------------------
쪽 크기 · 여백 · 글꼴 · 글자 크기 · 색 · 열 위치 · 행 높이 · 테두리. 바뀌는 것은 **칸
안의 글자**와 **그림 픽셀**뿐이다. 행이 늘거나 줄면 그 표 아래 것을 같은 행 높이만큼
밀되(`shift`), 새 행의 테두리는 원본에서 잰 것을 그대로 다시 그린다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import pymupdf as fitz

# ── 글꼴 ────────────────────────────────────────────────────────────────
# PDF 안의 FontDescriptor 가 `NotoSansCJKkr-Regular` · `-Bold` 라고 적어 둔다.
# 같은 글꼴이 데비안 계열의 fonts-noto-cjk 에 들어 있다. TTC 의 첫 face(JP) 를 쓰는데,
# CJK 통합한자만 지역별로 다르고 **한글·숫자·괄호친 숫자는 face 가 같다** — 실제로
# 글자 상자가 원본과 소수점 둘째 자리까지 맞는 것으로 확인했다.
FONT_REG = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

_FACE: dict[str, fitz.Font] = {}


def face(bold: bool = False) -> fitz.Font:
    k = "b" if bold else "r"
    if k not in _FACE:
        _FACE[k] = fitz.Font(fontfile=FONT_BOLD if bold else FONT_REG)
    return _FACE[k]


# 표 색 — 원본에서 잰 값이다. 비교는 느슨하게 한다(PDF 는 색을 실수로 담는다).
HEAD_FILL = (0.9490, 0.9529, 0.9608)
BORDER = (0.8118, 0.8118, 0.8118)
WHITE = (1.0, 1.0, 1.0)


def _near(a, b, tol=0.01):
    return (a is not None and b is not None and len(a) == len(b)
            and all(abs(x - y) <= tol for x, y in zip(a, b)))


# ── 잰 것 ───────────────────────────────────────────────────────────────
@dataclass
class Col:
    x0: float
    x1: float
    align: str = "center"      # center · right · left
    anchor: float = 0.0        # center 면 중심 x, right 면 오른쪽 끝, left 면 왼쪽 끝


@dataclass
class Table:
    page: int
    head_top: float
    head_bot: float
    cols: list[Col]
    row_tops: list[float]      # 본문 행의 위쪽 y (테두리 안쪽 아님, 경계선 y)
    row_h: float
    base_off: float            # 행 위쪽 → 글자 기준선까지
    head_text: list[str] = field(default_factory=list)
    rows_text: list[list[str]] = field(default_factory=list)

    @property
    def bottom(self) -> float:
        return self.row_tops[-1] + self.row_h if self.row_tops else self.head_bot

    def __repr__(self):  # noqa: D105
        return (f"<Table p{self.page+1} head={self.head_top:.1f}~{self.head_bot:.1f} "
                f"cols={len(self.cols)} rows={len(self.row_tops)} h={self.row_h:.2f} "
                f"{self.head_text}>")


def _rects(page):
    """채운 사각형만 (type f, items 가 're' 하나) 골라 낸다."""
    out = []
    for g in page.get_drawings():
        if g["type"] != "f" or g["fill"] is None:
            continue
        if [it[0] for it in g["items"]] != ["re"]:
            continue
        out.append((fitz.Rect(g["rect"]), tuple(g["fill"])))
    return out


def find_tables(page, page_no) -> list[Table]:
    """머리행(연회색 칸)과 테두리 선으로 표를 찾아 **자리를 잰다**."""
    rs = _rects(page)
    heads = [r for r, f in rs if _near(f, HEAD_FILL) and r.height > 8]
    borders = [r for r, f in rs if _near(f, BORDER)]
    if not heads:
        return []

    # 같은 y 대의 머리 칸을 한 줄로 묶는다
    heads.sort(key=lambda r: (round(r.y0, 1), r.x0))
    groups: list[list[fitz.Rect]] = []
    for r in heads:
        if groups and abs(groups[-1][0].y0 - r.y0) < 1.0:
            groups[-1].append(r)
        else:
            groups.append([r])

    tables = []
    for grp in groups:
        grp.sort(key=lambda r: r.x0)
        top, bot = grp[0].y0, grp[0].y1
        x_lo, x_hi = grp[0].x0, grp[-1].x1
        # 이 표에 속한 가로 테두리(폭이 표 전체에 걸치는 얇은 것)의 y
        ys = sorted({round(r.y0, 2) for r in borders
                     if r.height < 1.2 and r.width > (x_hi - x_lo) * 0.15
                     and r.x0 >= x_lo - 1 and r.x1 <= x_hi + 1 and r.y0 >= bot - 1.5})
        # 다음 표의 머리행 위까지만
        nxt = min([g[0].y0 for g in groups if g[0].y0 > bot + 1] or [1e9])
        ys = [y for y in ys if y < nxt]
        if len(ys) < 2:
            continue
        # 행 경계 → 행 높이. 첫 경계는 머리행 아래선이다.
        gaps = [(a, round(b - a, 2)) for a, b in zip(ys, ys[1:]) if b - a > 3]
        if not gaps:
            continue
        # **행 높이는 중앙값으로 잡는다** — 평균으로 하면 표 아래의 다음 덩어리까지 한 행으로
        # 삼켜서(고잔동 2면 「■ B동 …」 제목) 행 수도 열 정렬도 같이 틀어진다. 브라우저가
        # 행 경계를 화면 픽셀에 맞춰 반올림해 같은 표 안에서도 0.7 pt 쯤 들쭉날쭉하므로
        # 허용 폭을 넉넉히 두되(2 pt), 표가 끝나는 자리는 간격이 확 벌어져 걸린다.
        hs = sorted(h for _, h in gaps)
        row_h = hs[len(hs) // 2]
        tol = max(2.0, row_h * 0.10)
        tops = []
        for y, h in gaps:                        # 머리행 바로 아래부터 **연속인 데까지만**
            if abs(h - row_h) > tol:
                break
            tops.append(y)
        if not tops:
            continue
        cols = [Col(r.x0, r.x1) for r in grp]
        t = Table(page_no, top, bot, cols, tops, row_h, 0.0)
        _measure_text(page, t)
        tables.append(t)
    return tables


def _spans(page, y0, y1):
    out = []
    for b in page.get_text("dict")["blocks"]:
        if b["type"]:
            continue
        for l in b["lines"]:
            for s in l["spans"]:
                if y0 <= s["origin"][1] <= y1:
                    out.append(s)
    return out


def _measure_text(page, t: Table):
    """이미 있는 글자로 **열 정렬과 기준선 위치를 잰다** — 손으로 적지 않는다."""
    # 머리행
    t.head_text = _cells(_spans(page, t.head_top, t.head_bot), t)
    # 본문
    for top in t.row_tops:
        sp = _spans(page, top, top + t.row_h)
        t.rows_text.append(_cells(sp, t))
        if sp and not t.base_off:
            t.base_off = round(sp[0]["origin"][1] - top, 3)

    # 열별 정렬: 각 열에서 여러 행의 글자 상자를 보고 왼끝/중심/오른끝 중 무엇이 고정인지
    for i, c in enumerate(t.cols):
        lefts, rights, mids = [], [], []
        for top in t.row_tops:
            sp = [s for s in _spans(page, top, top + t.row_h) if c.x0 <= s["origin"][0] < c.x1]
            if not sp:
                continue
            lefts.append(min(s["bbox"][0] for s in sp))
            rights.append(max(s["bbox"][2] for s in sp))
            mids.append((lefts[-1] + rights[-1]) / 2)
        if len(lefts) < 2:
            c.align, c.anchor = "center", (c.x0 + c.x1) / 2
            continue
        var = {"left": max(lefts) - min(lefts), "right": max(rights) - min(rights),
               "center": max(mids) - min(mids)}
        c.align = min(var, key=var.get)
        c.anchor = {"left": sum(lefts) / len(lefts), "right": sum(rights) / len(rights),
                    "center": sum(mids) / len(mids)}[c.align]
        c.anchor = round(c.anchor, 2)


def _cells(spans, t: Table) -> list[str]:
    out = []
    for c in t.cols:
        sp = sorted([s for s in spans if c.x0 <= s["origin"][0] < c.x1],
                    key=lambda s: s["origin"][0])
        out.append(re.sub(r"\s+", " ", "".join(s["text"] for s in sp)).strip())
    return out


# ── 고치기 ──────────────────────────────────────────────────────────────
class Refit:
    """한 PDF 를 열어 값·그림을 갈아 끼운다."""

    def __init__(self, path):
        self.path = path
        self.doc = fitz.open(path)
        self.tables = {i: find_tables(p, i) for i, p in enumerate(self.doc)}
        self._fonts = set()
        # **두 벌로 모아 두었다가 마지막에 한 번에 한다.** 흰 사각형으로 덮기만 하면 옛
        # 글자가 파일 안에 그대로 남아 **복사·검색하면 나온다** — 종이에는 새 값이,
        # 긁어 보면 옛 값이 나오는 문서가 된다. 그래서 글자는 redaction 으로 **정말 지운다**.
        # 지우기는 그리기보다 먼저 해야 한다(새로 그린 글자까지 지워 버리지 않게).
        self._cut: dict[int, list] = {}
        self._ops: dict[int, list] = {}
        self._buf: dict[bool, bytes] = {}

    # ── 굵기 ──
    # PyMuPDF 의 span["flags"] 는 Type3 글꼴에서 굵기를 못 읽는다(늘 0). 굵기는
    # FontDescriptor 의 /FontWeight 에 적혀 있으므로 거기서 캐 온다 — 머리행과 소제목이
    # 굵은 판이라 이걸 못 읽으면 다시 그린 자리만 가늘어진다.
    def is_bold(self, span) -> bool:
        m = re.match(r"Type3 \((\d+) 0 R\)", span.get("font", ""))
        if not m:
            return bool(span.get("flags", 0) & 2 ** 4)
        x = int(m.group(1))
        if not hasattr(self, "_wt"):
            self._wt = {}
        if x not in self._wt:
            o = self.doc.xref_object(x)
            fd = re.search(r"/FontDescriptor\s+(\d+) 0 R", o)
            w = 400
            if fd:
                w = int((re.search(r"/FontWeight\s+(\d+)", self.doc.xref_object(int(fd.group(1))))
                         or re.match(r"(400)", "400")).group(1))
            self._wt[x] = w
        return self._wt[x] >= 600

    @staticmethod
    def color_of(span):
        return tuple(round(((span["color"] >> k) & 0xFF) / 255, 4) for k in (16, 8, 0))

    # 글꼴은 쪽마다 한 번만 붙인다 — **쓰는 글자만 잘라** 담는다(`_subset`).
    def _font(self, page, bold):
        """이 쪽에 쓸 글꼴 이름. **이름에 부분집합의 지문을 붙인다.**

        예전에는 `NSKR`/`NSKB` 로 고정이었다. 그런데 잘라 담은 글꼴은 **이 실행에서 쓰는
        글자만** 들어 있고, 쪽에 같은 이름의 글꼴이 이미 있으면 PyMuPDF 는 새 파일로 바꾸지
        않고 있던 것을 그대로 쓴다 — 그러면 **지난 실행에 없던 글자가 두부(▨)로 찍힌다.**
        실측 2026-08-25: 호림동 2면은 지난 실행이 표를 쓰며 `NSKR` 을 심어 두어서, 이번에
        더한 범례 「대상 건물 · 외부 건물(점선) …」 이 전부 두부가 됐다(3면은 `NSKR` 이 없어
        멀쩡했다 — 그래서 한 문서 안에서도 갈렸다).

        지문을 붙이면 부분집합이 달라질 때만 이름이 달라진다. 같은 내용을 다시 쓰면 이름도
        같아 그대로 재사용하므로 **여러 번 돌려도 글꼴이 쌓이지 않고**, 아무도 안 가리키게 된
        옛 글꼴은 저장할 때 `garbage=4` 가 걷어 간다.
        """
        buf = self._buf.get(bold)
        import hashlib
        tag = hashlib.md5(buf).hexdigest()[:6] if buf else "full"
        name = ("NSKB" if bold else "NSKR") + tag
        key = (page.number, name)
        if key not in self._fonts:
            if buf:
                page.insert_font(fontname=name, fontbuffer=buf)
            else:
                page.insert_font(fontname=name, fontfile=FONT_BOLD if bold else FONT_REG)
            self._fonts.add(key)
        return name

    def erase(self, page, rect):
        """그 자리의 **글자를 지우고**(redaction) 흰 바탕으로 덮는다."""
        r = fitz.Rect(rect)
        self._cut.setdefault(page.number, []).append(r)
        self.fill(page, r, WHITE)

    def fill(self, page, rect, color):
        self._ops.setdefault(page.number, []).append(("rect", fitz.Rect(rect), color))

    def text(self, page, s, *, x, y, size, color=(0.133, 0.133, 0.133), bold=False, align="left"):
        """`s` 는 글자열이거나 **(글자, 색) 조각의 목록**이다.

        조각으로 받는 이유: 비교분석 표의 칸이 「22.7 m · 안전」처럼 **한 칸 안에서 색이
        갈린다**(값은 먹색, 판정은 초록·빨강). 칸을 한 색으로 그리면 판정이 먹색이 되어
        원본과 달라진다. 정렬은 조각을 이어 붙인 **전체 폭**으로 잡는다.
        """
        if not s:
            return
        parts = [(s, color)] if isinstance(s, str) else list(s)
        parts = [(t, c) for t, c in parts if t]
        if not parts:
            return
        w = sum(face(bold).text_length(t, size) for t, _ in parts)
        x0 = {"left": x, "right": x - w, "center": x - w / 2}[align]
        for t, c in parts:
            # **줄바꿈없는 공백을 보통 공백으로 바꾼다.** 두 글자는 이 글꼴에서 같은 글리프라
            # 종이에서는 구분되지 않는데, 잘라 담은 글꼴의 ToUnicode 가 그 글리프를 U+00A0
            # 으로 되돌려 적어서 **긁어 복사하면 「4.1\xa0m」** 이 된다. 폭이 같으므로
            # (실측 동일) 자리는 그대로다.
            self._ops.setdefault(page.number, []).append(
                ("text", (x0, y), t.replace("\xa0", " "), size,
                 c if c is not None else color, bold))
            x0 += face(bold).text_length(t, size)

    # ── 표 ──
    def write_row(self, t: Table, i: int, cells, colors=None, sizes=None, bolds=None):
        """i 번째 본문 행의 칸 글자를 바꾼다. `None` 인 칸은 건드리지 않는다.

        행 위치는 **잰 경계**를 그대로 쓴다 — 브라우저가 행 높이를 화면 픽셀에 맞춰
        반올림해 같은 표에서도 0.7 pt 씩 다르므로, 평균으로 밀면 글자가 칸 안에서 흔들린다.
        """
        page = self.doc[t.page]
        top = (t.row_tops[i] if i < len(t.row_tops)
               else t.row_tops[-1] + (i - len(t.row_tops) + 1) * t.row_h)
        y = top + t.base_off
        h = (t.row_tops[i + 1] - top) if i + 1 < len(t.row_tops) else t.row_h
        for j, (c, s) in enumerate(zip(t.cols, cells)):
            if s is None:
                continue
            # 테두리를 살려 두려고 칸 **안쪽만** 지운다. 위아래로 1 pt 씩 물러선다 —
            # 경계선 사각형이 두께 0.75 pt 인데 문서마다 경계 **위**에 붙기도 하고 **아래**에
            # 붙기도 해서(고잔동 · 호림동이 다르다), 덜 물러서면 줄마다 밑줄이 6 px 에서
            # 2 px 로 얇아진다(600 dpi 실측). 글자는 칸 위에서 8.5 pt 아래에 앉으므로
            # 1 pt 를 비워도 다 덮인다.
            self.erase(page, (c.x0 + 0.9, top + 1.0, c.x1 - 0.9, top + h - 1.0))
            col = (colors or [None] * len(t.cols))[j] or (0.133, 0.133, 0.133)
            sz = (sizes or [9.0] * len(t.cols))[j]
            bd = (bolds or [False] * len(t.cols))[j]
            self.text(page, s, x=c.anchor, y=y, size=sz, color=col, bold=bd, align=c.align)

    def grow(self, t: Table, n: int):
        """표 끝에 n 행을 잇는다 — 테두리를 원본과 같은 두께·색으로 그린다."""
        page = self.doc[t.page]
        y = t.row_tops[-1] + t.row_h
        for _ in range(n):
            self.frame(page, t.cols, y, y + t.row_h)
            t.row_tops.append(y)
            y += t.row_h
        return y

    # ── 줄·표를 통째로 다시 그리기(행 수가 바뀌어 아래가 밀릴 때) ──
    def move_spans(self, page_no, spans, dy, *, erase=True):
        """이미 있는 글자 줄을 dy 만큼 **옮겨 다시 그린다** — 크기·색·굵기는 그대로."""
        page = self.doc[page_no]
        if erase:
            bb = fitz.Rect(spans[0]["bbox"])
            for s in spans[1:]:
                bb |= fitz.Rect(s["bbox"])
            self.erase(page, (bb.x0 - 0.6, bb.y0 - 0.6, bb.x1 + 0.6, bb.y1 + 0.6))
        for s in spans:
            if s["text"].strip():
                self.text(page, s["text"], x=s["origin"][0], y=s["origin"][1] + dy,
                          size=s["size"], color=self.color_of(s), bold=self.is_bold(s))

    def head_spans(self, t: Table):
        """머리행 글자 — 머리행은 본문과 **정렬이 다르다**(「이격거리」는 칸 가운데인데 값은
        오른끝). 그래서 다시 앉히지 않고 있는 것을 그대로 옮긴다."""
        return _spans(self.doc[t.page], t.head_top, t.head_bot)

    def frame(self, page, cols, y0, y1, *, top=False):
        """칸 테두리 — 원본이 쓰는 두께(0.75 pt)·색으로 사각형을 깔아 그린다."""
        w = 0.75
        for c in cols:
            self.fill(page, (c.x0, y0, c.x0 + w, y1), BORDER)
        self.fill(page, (cols[-1].x1 - w, y0, cols[-1].x1, y1), BORDER)
        self.fill(page, (cols[0].x0, y1 - w, cols[-1].x1, y1), BORDER)
        if top:
            self.fill(page, (cols[0].x0, y0, cols[-1].x1, y0 + w), BORDER)

    def render_table(self, page_no, cols, y0, head, rows, *, row_h, head_h,
                     base_off, head_off, colors=None, sizes=None):
        """머리행 + 본문을 y0 부터 통째로 그린다(칸 색·테두리·글자 모두).

        `colors[i][j]` 는 i 행 j 칸의 색. 없으면 본문 먹색. 머리행은 늘 굵은 글씨다.
        """
        page = self.doc[page_no]
        for c in cols:                                   # 머리행 바탕
            self.fill(page, (c.x0, y0, c.x1, y0 + head_h), HEAD_FILL)
        self.frame(page, cols, y0, y0 + head_h, top=True)
        for c, s in zip(cols, head):
            self.text(page, s, x=c.anchor, y=y0 + head_off, size=9.0, bold=True,
                      align=c.align)
        y = y0 + head_h
        for i, r in enumerate(rows):
            self.frame(page, cols, y, y + row_h)
            for j, (c, s) in enumerate(zip(cols, r)):
                if s is None:
                    continue
                col = ((colors or [])[i][j] if colors else None) or (0.133, 0.133, 0.133)
                sz = ((sizes or [])[i][j] if sizes else None) or 9.0
                self.text(page, s, x=c.anchor, y=y + base_off, size=sz, color=col,
                          align=c.align)
            y += row_h
        return y

    # ── 줄 단위로 값 갈아 끼우기 ──
    def lines(self, page_no):
        """(전체 글자, 스팬들) 로 쪽의 모든 줄을 준다."""
        out = []
        for b in self.doc[page_no].get_text("dict")["blocks"]:
            if b["type"]:
                continue
            for l in b["lines"]:
                out.append(("".join(s["text"] for s in l["spans"]), l["spans"]))
        return out

    def edit_line(self, page_no, find, repl, *, count=1, where=None):
        """줄을 찾아 **글자만** 바꾼다 — 자리·크기·색은 그 줄이 쓰던 것을 그대로 쓴다.

        칸마다 색이 다른 줄(빨강 「위험」이 섞인 줄)도 되도록, 원래 글자마다 그 글자가
        쓰던 색·크기를 붙여 두고 바꾼 뒤 같은 모양으로 다시 나눠 그린다. 새로 생긴 글자는
        **바로 앞 글자의 모양**을 물려받는다. 숫자는 폭이 모두 같아서(4.995 pt @ 9) 숫자만
        갈아 끼우면 뒤 글자가 밀리지 않는다.
        """
        page = self.doc[page_no]
        n = 0
        for txt, spans in self.lines(page_no):
            if find not in txt or (where and not where(txt)):
                continue
            style = []
            for s in spans:
                col = tuple(round(((s["color"] >> k) & 0xFF) / 255, 4) for k in (16, 8, 0))
                for ch in s["text"]:
                    style.append((ch, s["size"], col, bool(s["flags"] & 2 ** 4)))
            old = "".join(c for c, *_ in style)
            new = old.replace(find, repl, 1)
            if new == old:
                continue
            # 글자 → 모양 대응을 새 글자열에 옮긴다
            i = old.index(find)
            keep_l, keep_r = style[:i], style[i + len(find):]
            mid_style = style[i] if i < len(style) else style[-1]
            mid = [(ch, mid_style[1], mid_style[2], mid_style[3]) for ch in repl]
            style = keep_l + mid + keep_r

            x0 = spans[0]["origin"][0]
            y = spans[0]["origin"][1]
            bb = fitz.Rect(spans[0]["bbox"])
            for s in spans[1:]:
                bb |= fitz.Rect(s["bbox"])
            self.erase(page, (bb.x0 - 0.6, bb.y0 - 0.6, bb.x1 + 0.6, bb.y1 + 0.6))
            # **같은 모양이 이어지면 한 덩어리로 그린다.** 글자마다 따로 그리면 종이는
            # 같아 보여도 긁어 복사할 때 낱말이 붙어 나온다(「최근접이격거리동측」).
            # 띄어쓰기도 빼지 않고 그린다 — 빼면 그 자리가 붙은 글자로 읽힌다.
            x = x0
            run, i2 = [], 0
            while i2 < len(style):
                ch, sz, col, bold = style[i2]
                j = i2
                while j < len(style) and style[j][1:] == (sz, col, bold):
                    j += 1
                run.append(("".join(c for c, *_ in style[i2:j]), sz, col, bold))
                i2 = j
            for txt2, sz, col, bold in run:
                self.text(page, txt2, x=x, y=y, size=sz, color=col, bold=bold)
                x += face(bold).text_length(txt2, sz)
            n += 1
            if n >= count:
                break
        if n == 0:
            raise LookupError(f"p{page_no+1}: {find!r} 를 못 찾았다")
        return n

    # ── 그림 ──
    def swap_image(self, page_no, xref, png, *, keep_size=True):
        """XObject 픽셀만 바꾼다 — 놓인 자리·크기·쪽 안의 순서는 그대로다.

        `keep_size` 는 원본 XObject 와 **같은 픽셀 수**로 줄여 넣는다는 뜻이다. 손으로 뽑은
        판이 문서마다 다른 배율로 줄여 담아 두어서(고잔동 555 px · 호림동 1600 px),
        원본 배율을 지켜야 종이 위 선 굵기와 파일 크기가 예전과 같이 나온다.
        """
        import io

        from PIL import Image
        old = self.doc.extract_image(xref)
        im = Image.open(png).convert("RGB")
        if keep_size and (im.width, im.height) != (old["width"], old["height"]):
            im = im.resize((old["width"], old["height"]), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, format="PNG", optimize=True)
        self.doc[page_no].replace_image(xref, stream=buf.getvalue())
        return (im.width, im.height)

    def _subset(self):
        """이 문서에 **실제로 쓰는 글자만** 담은 글꼴을 만든다.

        안 하면 PyMuPDF 가 Noto Sans CJK TTC 를 통째로 박아(압축해도 13.6 MB) 14 MB 짜리
        문서가 28 MB 가 된다. PyMuPDF 의 `subset_fonts()` 는 이 CFF 기반 CJK 글꼴에서
        「Reserved charstring byte」로 실패하므로 fontTools 로 직접 자른다. 자르기는 글자
        너비를 바꾸지 않으므로 이미 잡아 둔 자리가 그대로 맞는다.
        """
        import io
        want: dict[bool, set] = {}
        for ops in self._ops.values():
            for op in ops:
                if op[0] == "text":
                    want.setdefault(op[5], set()).update(op[2])
        self._buf = {}
        for bold, chars in want.items():
            try:
                from fontTools import subset as _sub
                from fontTools.ttLib import TTFont
                f = TTFont(FONT_BOLD if bold else FONT_REG, fontNumber=0, lazy=True)
                o = _sub.Options()
                # **retain_gids 가 없으면 글자가 안 찍힌다.** 이 글꼴은 CID 기반 CFF 라
                # 자를 때 글리프 번호가 다시 매겨지는데, PDF 는 Identity-H 로 **번호를 그대로**
                # 적어 넣어서 엉뚱한 글리프(또는 빈 글리프)를 가리키게 된다. 번호를 지키면
                # 빈 자리가 남아 652 KB 가 되지만, 통째로 넣는 13.6 MB 보다 훨씬 작다.
                o.set(layout_features=[], retain_gids=True, notdef_outline=True,
                      hinting=False, desubroutinize=True)
                ss = _sub.Subsetter(options=o)
                ss.populate(text="".join(sorted(chars)))
                ss.subset(f)
                b = io.BytesIO()
                f.save(b)
                self._buf[bold] = b.getvalue()
            except Exception as e:                           # noqa: BLE001
                print(f"  ! 글꼴 자르기 실패({'굵게' if bold else '보통'}): {e} — 통째로 넣는다")

    def flush(self):
        """모아 둔 것을 **지우기 먼저, 그리기 나중**으로 실행한다."""
        self._subset()
        for pno, rects in self._cut.items():
            page = self.doc[pno]
            for r in rects:
                page.add_redact_annot(r)
            # 그림은 손대지 않는다. 선(표 테두리·칸 바탕)은 **지우는 자리에 통째로 들어간
            # 것만** 없앤다 — 칸 안쪽만 지울 때는 테두리가 걸치기만 하므로 살아남고, 표
            # 한 덩어리를 들어낼 때는 그 표의 바탕과 테두리가 같이 빠진다. 흰 사각형으로
            # 덮기만 하면 파일 안에는 남아서, 이 문서를 다시 읽는 쪽이 **없는 표를 본다**.
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                                  graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                                  text=fitz.PDF_REDACT_TEXT_REMOVE)
        self._cut = {}
        for pno, ops in self._ops.items():
            page = self.doc[pno]
            # **바탕을 다 깔고 나서 글자를 얹는다.** 섞인 차례로 그리면 나중에 부른 지우개가
            # 앞서 그린 글자를 덮는다 — 표를 늘리면 그 자리에 있던 각주를 옮기는데, 각주
            # 지우개가 새 줄 위에 떨어졌다(실측 호산동 ⑦행이 반쯤 지워졌다).
            ops = [o for o in ops if o[0] == "rect"] + [o for o in ops if o[0] != "rect"]
            for op in ops:
                if op[0] == "rect":
                    page.draw_rect(op[1], color=None, fill=op[2], overlay=True)
                else:
                    _, xy, t, size, color, bold = op
                    page.insert_text(xy, t, fontname=self._font(page, bold),
                                     fontsize=size, color=color)
        self._ops = {}

    def save(self, out=None):
        """제자리에 덮어쓴다. redaction 을 적용하면 통째로 다시 써야 해서(증분 저장 불가)
        옆에 쓴 뒤 바꿔 끼운다 — 쓰다 죽어도 원본이 반쯤 덮이지 않는다."""
        import os
        self.flush()
        out = out or self.path
        tmp = f"{out}.__new__"
        # garbage=4 여야 한다 — 3 으로 두면 갈아 끼운 옛 그림 스트림이 파일에 남아
        # 14 MB 짜리가 51 MB 가 된다(실측).
        self.doc.save(tmp, garbage=4, deflate=True)
        self.doc.close()
        os.replace(tmp, out)


# ── 스스로 재 보기 ──────────────────────────────────────────────────────
def selftest(path, page_no=1):
    """이미 있는 행을 **같은 값으로** 다시 그려 원본과 겹치는지 잰다."""
    import numpy as np
    r = Refit(path)
    t = r.tables[page_no][0]
    before = r.doc[page_no].get_pixmap(dpi=300)
    r.write_row(t, 0, t.rows_text[0])
    r.save("/tmp/_selftest.pdf")
    after = fitz.open("/tmp/_selftest.pdf")[page_no].get_pixmap(dpi=300)
    A = np.frombuffer(before.samples, np.uint8).reshape(before.height, before.width, before.n)
    B = np.frombuffer(after.samples, np.uint8).reshape(after.height, after.width, after.n)
    d = np.abs(A.astype(float) - B.astype(float))
    return {"table": repr(t), "mean": round(float(d.mean()), 5),
            "pct_gt32": round(float(np.mean(d.max(2) > 32)) * 100, 4)}


if __name__ == "__main__":
    import sys
    for f in sys.argv[1:]:
        r = Refit(f)
        print("=" * 8, f)
        for i, ts in r.tables.items():
            for t in ts:
                print("   ", t)
                print("      cols:", [(round(c.x0, 1), round(c.x1, 1), c.align, c.anchor)
                                      for c in t.cols])
                for row in t.rows_text:
                    print("      ·", row)
