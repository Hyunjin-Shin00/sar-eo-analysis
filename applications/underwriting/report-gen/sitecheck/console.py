"""화면에 찍는 것 — **한 벌이고 여기 하나다.**

주소 한 건에 이만큼만 찍는다. 단계마다 한 줄, 끝에 결과 한 묶음이다.

    [1/1] 경상북도 구미시 공단동 267-115
      주소 해석    완료  PNU 4719011300102670115 · 대장 5동 · 영상 구미
      건물 폴리곤   완료  5동 · 옆 지번 29동 · 정합 잔차 0.36 m
      이격거리     완료  30건
      야적물      완료  0건
      대장 대조    완료  6건
      산출물      완료  14개 파일

      결과: 경고
            건물 5 · 대장 대조 6(이상없음 6) · 이격거리 30(경고 16 · 주의 1 · 이상없음 13) · 야적물 0
            out/경상북도_구미시_공단동_267-115

**자세한 내막은 기본으로 안 찍는다** — 정합 이득 · 편이 추정 · 물려받은 레이어 · 필지 편이는
`--detail` 을 켤 때만 나온다. 켜지 않아도 **전부 결과 파일에 남는다**(`site.notes` ·
`provenance.steps`). 화면은 지나가면 없어지는 것이고 파일은 아니므로, 없어지는 쪽을 줄인다.

세 등급이고 `setup()` 으로 정한다.

    0 QUIET    아무것도 안 찍는다            `--quiet`
    1 NORMAL   단계 한 줄 + 결과 (기본)
    2 DETAIL   그 위에 내막까지              `--detail`

**등급을 모듈 전역으로 둔 이유**는 내막을 찍는 자리가 `steps/` 안쪽 깊은 곳(정합·편이·시차)
이기 때문이다. 그 자리까지 깃발을 실어 나르면 함수 서명 열 개가 화면 사정을 알게 된다 —
찍을지 말지는 화면의 사정이지 계산의 사정이 아니다.
"""
from __future__ import annotations

import sys
import unicodedata

QUIET, NORMAL, DETAIL = 0, 1, 2
LEVEL = NORMAL

DONE, FAIL = "완료", "실패"
_NAME_W = 12          # 단계 이름 칸(터미널 폭 기준) — 가장 긴 이름 '그림·보고서'가 11이다


def setup(level=NORMAL):
    """등급을 정한다. 진입점이 명령줄을 읽고 한 번만 부른다([[cli.py]])."""
    global LEVEL
    LEVEL = int(level)
    return LEVEL


def on(level=NORMAL):
    """지금 등급이 `level` 이상인가 — 깊은 자리의 `verbose=` 인자에 넘길 값."""
    return LEVEL >= level


def _w(s):
    """터미널에서 차지하는 칸 수. 한글은 두 칸이라 `len()` 으로 맞추면 표가 어긋난다."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(s))


def _pad(s, n):
    return str(s) + " " * max(0, n - _w(s))


def _out(text):
    print(text, flush=True)


def head(text):
    """주소 한 건의 머리. 앞에 빈 줄을 둔다 — 건과 건 사이가 눈에 들어와야 한다."""
    if LEVEL >= NORMAL:
        _out(f"\n{text}")


def step(name, ok=True, note=""):
    """단계 한 줄 — `  이름        완료  덧말`. 실패면 `완료` 자리에 `실패` 가 온다."""
    if LEVEL >= NORMAL:
        _out(f"  {_pad(name, _NAME_W)}{DONE if ok else FAIL}"
             + (f"  {note}" if note else ""))


def sub(text):
    """단계에 딸린 한 줄 — **사람이 넣은 값처럼 지나가면 안 되는 것**만 여기로 온다."""
    if LEVEL >= NORMAL:
        _out(f"  {' ' * _NAME_W}└ {text}")


def detail(text):
    """내막 — `--detail` 에서만. 안 찍어도 결과 파일에 남아 있는 것들이다."""
    if LEVEL >= DETAIL:
        _out(f"  {' ' * _NAME_W}· {text}")


def warn(text):
    """어긋난 것 — 조용히 지나가면 안 되는 것. **표준오류로 낸다.**

    단계 줄과 섞이지 않아야 눈에 들고, 결과를 파이프로 받는 쪽에도 안 섞인다.
    """
    if LEVEL >= NORMAL:
        print(f"  [!] {text}", file=sys.stderr, flush=True)


def result(worst, parts, path=None):
    """끝맺음 — 최고 판정 한 줄, 항목별 수 한 줄, 어디에 냈는지 한 줄."""
    if LEVEL < NORMAL:
        return
    pad = " " * 8
    _out(f"\n  결과: {worst or '—'}")
    if parts:
        _out(f"{pad}{' · '.join(parts)}")
    if path:
        _out(f"{pad}{path}")


def tail(text):
    """목록 전체의 끝맺음 — `완료 3/5` 처럼."""
    if LEVEL >= NORMAL:
        _out(f"\n{text}")


def fail(address, why):
    """건너뛴 건. 표준오류로 낸다 — 성공 목록을 파이프로 받는 쪽과 섞이면 안 된다."""
    if LEVEL >= NORMAL:
        print(f"  건너뜀 · {address} — {why}", file=sys.stderr, flush=True)


class _Silent:
    """아무것도 안 찍는 짝 — 부르는 쪽이 `verbose=False` 일 때 이것을 쓴다.

    `if verbose:` 를 자리마다 적는 대신 **찍는 대상을 갈아 끼운다.** 그러면 부르는 쪽 코드가
    한 벌이고, 조용히 할지는 들어올 때 한 번만 정해진다.
    """

    def __getattr__(self, _name):
        return lambda *a, **kw: None


SILENT = _Silent()
