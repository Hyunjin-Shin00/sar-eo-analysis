"""이식해 온 GT 의 **지붕 시차 잔차**를 이 지번 건물에서 재서 그만큼 GT 를 옮긴다.

왜 필요한가. 2차 영상(`daegu2`)의 GT 는 사람이 새로 그린 것이 아니라 1차(`daegu`) GT 를
옮겨 온 것이다(`seglab/scripts/port_gt.py`). 옮길 때 지붕 시차를 **장면 전체에 상수 하나**로
보정하는데(대구 −0.5,−1.5 px), 시차는 건물 높이와 장면 안 위치를 타므로 한 숫자로는 다
맞출 수 없다 — port_gt 자신이 그렇게 적어 두었다(daegu2 사분면별 dx +0.2 ~ −4.2 px).

실측(대구 4주소 · 이 지번 건물 테두리 ↔ 영상 엣지 봉우리 · 2026-08-23):

    주소            1차 봉우리      2차 봉우리      옮긴 양                이득(1차/2차)
    신당동 1187-2   (-0.5,-1.0) px  (-3.5,-1.0) px  (-3.0, 0.0) 1.5 m 서   1.12/1.45
    파호동 204      (-2.5, 0.0)     (-0.5,-3.0)     (+2.0,-3.0) 1.0 m 동·1.5 m 북  1.13/1.19
    호림동 3-10     (-0.5, 0.0)     (-3.5,+0.5)     (-3.0,+0.5) 1.5 m 서   1.02/1.33
    호산동 702-5    ( 0.0,+0.5)     (-1.0, 0.0)     (-1.0,-0.5) 0.5 m 서   1.03/1.03

보정 뒤 그려진 건물은 두 영상에서 지붕에 대해 **같은 자리**에 앉는다(네 주소 모두 차이
0.0 px). 「18일은 맞는데 28일이 안 맞는다」가 이것으로 없어진다. 파호동 204 · 호림동 3-10 은
그 뒤 비교분석 표본에서 빠졌지만(`cmp_addresses.txt`) **방향이 주소마다 다르다**는 근거라
값은 남긴다 — 넷 중 둘이 서, 하나가 동, 하나가 남북까지 섞인다.

**이 지번 건물만으로 잰다.**
창 안 전부(30~45동)로 재면 옆 지번 건물이 값을 끌고 간다 — 수가 많아 테두리 길이의 대부분을
차지하는데, 시차는 건물 높이를 타므로 낮은 이웃들의 평균은 정작 볼 건물의 시차가 아니다.
실측(호산동 702-5 · 2차): 창 전부로 재면 (+2,0) px 이득 1.02, 이 지번 공장 한 동으로 재면
(−1,0) px 이득 1.47 — **방향이 반대고 신호는 20배 뚜렷하다.** 재는 것은 이 지번이지만
**옮기는 것은 창 안 전부**다(그래야 건물끼리의 거리가 보존된다).

**차이로 잰다.** 1차의 봉우리는 0 이 아니다 — 사람이 처마 바깥을 따라 그린 계통 편이가
건물마다 있다(위 표: 파호동 204 는 1차에서도 −2.5 px 다). 그러므로 옮기는 양은 **2차 봉우리
− 1차 봉우리**이고, 목표는 「영상에 딱 맞추는 것」이 아니라 **1차에서 앉아 있던 것과 같은
자리에 앉히는 것**이다. 두 시기를 견주는 문서라 그 일관성이 절대 위치보다 중요하다.

1차를 잴 때는 `port_gt` 가 이미 먹인 시차 상수까지 빼서 **원본이 그려진 자리 그대로** 재야
한다. 그 상수를 남겨 두고 재면 뺄셈이 이미 먹인 보정을 한 번 더 옮긴다(실측: 네 주소가 전부
y −2 px 로 나왔다 — nudge −1.5 px 를 되먹은 값이다).

**0.5 px 격자에서 잰다** ([[parcel_fit.peak_sub]]). 정수만 보면 최적점이 반 픽셀 옆일 때
그 근처 두 점만 보게 되는데, 지붕이 비스듬한 건물에서는 x 를 반 픽셀 잘못 잡으면 y 의
최적점이 1 px 넘게 따라 움직인다(실측 호산동: 정수 격자 (0,+2) 이득 1.08 · 0.5 px 격자
(−1.0,0.0) 이득 1.47 — 같은 건물 같은 영상인데 답이 다르다). 그리고 **비긴 봉우리는 0 에
가까운 쪽으로 고른다** — 공장 지붕은 베이가 반복돼 봉우리가 여러 개 서고, 신호가 약한 창
에서는 최고점이 잡음이라 0 이 후보에 들어와 저절로 안 옮기게 된다.

**평행이동만 한다.** 회전·축척을 넣을 근거가 없고, 근거 없는 자유도는 조용히 틀리는 쪽으로만
쓰인다.

무엇이 바뀌고 무엇이 안 바뀌나
------------------------------
창 전체를 같은 양으로 옮기므로 **건물끼리의 거리는 그대로다** — 이격 표의 값(A1)은 움직이지
않는다(실측: 네 주소 모두 두 시기의 이격·면적이 완전히 같다). 면적도 그대로다(합동이동).
바뀌는 것은 그림 위 자리와, 필지에 대한 상대 위치에서 나오는 것들이다(야적 영역 = 필지 −
건물 · 귀속 면적 지분).

**1차 영상에는 걸리지 않는다.** GT 가 이식된 장면에서만 돈다(그 사실은 `_ported_from.json`
이 말해 준다). 원본 GT 를 이 보정에 태우면 사람이 그 영상을 보고 그린 자리를 영상 엣지
쪽으로 다시 미는 셈이라, 고칠 것이 없는데 움직인다.

    python -m sitecheck.steps.gt_parallax demo_cmp/t2/*/    저장된 결과의 시차 잔차를 잰다
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sitecheck import settings as config

SEARCH_PX = 6      # 탐색 반경(px) — 쫓는 것이 몇 px 짜리 시차라 넓게 잡으면 남의 봉우리를 문다
SUB = 2            # 한 픽셀을 둘로 — 0.5 px(0.25 m) 격자. 정수만 보면 답이 달라진다
TIE_TOL = 0.01     # 최고점의 1 % 안이면 비긴 것으로 보고 0 에 가까운 쪽을 고른다
DRAW_HALF_PX = 0.5  # 그릴 때 픽셀 중심을 쓴다(georef.px_rings_to_ll) — 그 자리에서 재야 한다
MAX_PX = 6         # 이보다 큰 값은 시차가 아니다(3 m) — 재기 실패로 본다
MIN_RINGS = 1      # **이 지번 건물만** 쓰므로 한 동짜리 필지가 흔하다
MIN_AREA_PX = 600  # 고른 동의 넓이 합(px²) 하한 ≈ 150 ㎡ — 헛간 하나로 장면을 옮기지 않는다
MIN_PX = 0.5       # 0.5 px(0.25 m) 미만은 옮기지 않는다 — 격자 자체가 0.5 px 다
WIN_PAD_PX = 24    # 잴 창 = 고른 동의 bbox + 이만큼


# ── 이식 내력 ────────────────────────────────────────────────────────────────
def _region_scene(region):
    """seglab 지역 이름(`test_daegu_ortho`) → 영상 key. `meta.src_tif` 가 말해 준다."""
    for k in config.SCENES:
        m = config.scene_meta(k) or {}
        if f"regions/{region}/" in (m.get("src_tif") or ""):
            return k
    return None


def ported(scene_key):
    """이 장면의 GT 가 옮겨 온 것이면 그 내력, 아니면 None.

    먼저 **폴더 안 사본**(`assets/gt/<장면>.json` 의 `ported_from`)을 본다 — GT 사본을
    담아 두는 이유가 seglab 없이 도는 것이라, 그 사본만 보고 판단할 수 있어야 한다.
    없으면 원본 옆의 `_ported_from.json` 을 찾는다.
    """
    from sitecheck.gt import gt_file
    p = gt_file(scene_key)
    if not p:
        return None
    try:
        j = json.loads(Path(p).read_text("utf-8"))
    except Exception:                                            # noqa: BLE001
        return None
    d = j.get("ported_from")
    if not d:
        f = Path(p).parent / "_ported_from.json"
        if not f.exists():
            return None
        try:
            d = json.loads(f.read_text("utf-8"))
        except Exception:                                        # noqa: BLE001
            return None
    src = d.get("src_scene") or _region_scene(str(d.get("src") or ""))
    if not src or src == scene_key or src not in config.SCENES:
        return None
    return dict(d, src_scene=src)


def link_px(src_key, dst_key):
    """src 장면 픽셀 → dst 장면 픽셀 **평행이동**(dx, dy). 두 원본 지오트랜스폼에서 직접.

    `meta.bbox` 를 쓰지 않는 이유는 port_gt 와 같다 — 그 값은 UTM 사각형의 경위도
    외접사각형이라 선형 보간하면 자오선 수렴만큼 틀린다. 두 장면이 같은 CRS·같은 격자가
    아니면 평행이동으로 이을 수 없으므로 None 을 돌려준다(회전·축척은 다루지 않는다).
    """
    from sitecheck.steps import georef
    Ts, cs, _W, _H = georef.raw_xform(config.SCENES[src_key]["dir"].resolve())
    Td, cd, _W2, _H2 = georef.raw_xform(config.SCENES[dst_key]["dir"].resolve())
    if str(cs) != str(cd):
        return None
    if max(abs(Ts.a - Td.a), abs(Ts.e - Td.e), abs(Ts.b - Td.b), abs(Ts.d - Td.d)) > 1e-9:
        return None
    if not Ts.a or not Ts.e:
        return None
    return (Ts.c - Td.c) / Td.a, (Ts.f - Td.f) / Td.e


# ── 측정 ────────────────────────────────────────────────────────────────────
def _subject(rings_px, par_px):
    """**이 지번 건물만.** 없으면 빈 목록.

    창 안 전부(30~45동)로 재면 옆 지번 건물이 값을 끌고 간다 — 수가 많아 테두리 길이의
    대부분을 차지하는데, 시차는 건물 높이를 타므로 낮은 이웃들의 평균은 정작 볼 건물의
    시차가 아니다. 실측(호산동 702-5 · 2차): 창 전부로 재면 (+2,0) px 이득 1.02, 이 지번
    공장 한 동으로 재면 (−3,0) px 이득 1.47 — **방향이 반대고 신호는 20배 뚜렷하다.**
    """
    from shapely.geometry import Polygon
    if par_px is None:
        return []
    out = []
    for r in rings_px:
        try:
            g = Polygon(r)
            if not g.is_valid:
                g = g.buffer(0)
            if not g.is_empty and par_px.contains(g.centroid):
                out.append(r)
        except Exception:                                        # noqa: BLE001
            continue
    return out


def _parcel_px(site):
    """필지 → 영상 픽셀. 못 만들면 None."""
    from shapely.geometry import shape
    from sitecheck.steps import georef, s2_yard
    if not site.get("parcel"):
        return None
    try:
        T, crs, _W, _H = georef.xform(site)
        return s2_yard._lonlat_to_px(T, crs, shape(site["parcel"]))
    except Exception:                                            # noqa: BLE001
        return None


def _area_px(rings):
    from shapely.geometry import Polygon
    a = 0.0
    for r in rings:
        try:
            g = Polygon(r)
            a += abs(g.area) if g.is_valid else abs(g.buffer(0).area)
        except Exception:                                        # noqa: BLE001
            continue
    return a


def _win(rings, pad=WIN_PAD_PX):
    xs = [x for r in rings for x, _y in r]
    ys = [y for r in rings for _x, y in r]
    return (min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad)


def measure(dst_key, rings_px, *, parcel_px=None, verbose=False):
    """{'px': (nx, ny), …} — dst GT 를 이만큼 옮겨야 dst 영상 지붕에 앉는다. 못 재면 None."""
    from sitecheck.steps import parcel_fit
    src = ported(dst_key)
    if not src:
        return None
    sk = src["src_scene"]
    link = link_px(sk, dst_key)
    if link is None:
        if verbose:
            print(f"  [지붕시차] {sk}→{dst_key} 두 장면을 평행이동으로 잇지 못한다 — 건너뛴다")
        return None
    lx, ly = link
    use = _subject(rings_px, parcel_px)
    if len(use) < MIN_RINGS or _area_px(use) < MIN_AREA_PX:
        if verbose:
            print(f"  [지붕시차] 이 지번 건물이 {len(use)}동({_area_px(use):.0f} px²) — "
                  f"재기에 모자라 옮기지 않는다")
        return None
    # **옮길 때 쓴 값 전부**를 빼야 원본 GT 자리로 돌아간다 — 지오트랜스폼 평행이동뿐
    # 아니라 그때 먹인 시차 상수(`nudge_px`)까지. 그 상수를 남겨 둔 채로 1차를 재면
    # 봉우리가 그만큼 밀려 나와, 뺄셈이 **이미 먹인 보정을 한 번 더** 옮긴다.
    nu = src.get("nudge_px") or [0.0, 0.0]
    bx, by = lx + float(nu[0]), ly + float(nu[1])
    sh = src.get("shift_px")
    if sh and len(sh) == 2 and max(abs(float(sh[0]) - bx), abs(float(sh[1]) - by)) > 0.51:
        # 기록과 지오트랜스폼이 어긋나면 **기록**을 믿는다 — 실제로 그 값으로 옮겼다.
        bx, by = float(sh[0]), float(sh[1])
    # dst 링을 원본 자리로 되돌린 것 = **같은 건물의 1차 GT**. GT 파일을 다시 읽지 않는
    # 이유는 그 사이 창밖·nodata 로 걸러진 동이 있어 두 창의 표본이 달라지기 때문이다 —
    # 뺄셈이 성립하려면 두 봉우리를 **같은 동**에서 재야 한다.
    # **그려지는 자리에서 잰다.** 픽셀 링은 경위도로 올라갈 때 픽셀 중심(+0.5)을 쓰므로
    # (`georef.px_rings_to_ll`), 원본 좌표 그대로 재면 반 픽셀 어긋난 자리를 재게 된다 —
    # 그 반 픽셀이 비스듬한 지붕에서는 1 px 넘는 차이로 돌아온다.
    h = DRAW_HALF_PX
    use_d = [[(x + h, y + h) for x, y in r] for r in use]
    use_src = [[(x - bx + h, y - by + h) for x, y in r] for r in use]
    kw = {"search_px": SEARCH_PX, "min_rings": MIN_RINGS, "sub": SUB, "tie_tol": TIE_TOL}
    pd = parcel_fit.peak_sub(dst_key, use_d, _win(use_d), **kw)
    ps = parcel_fit.peak_sub(sk, use_src, _win(use_src), **kw)
    if pd is None or ps is None:
        if verbose:
            print(f"  [지붕시차] 봉우리를 못 쟀다 — {dst_key} "
                  f"{'없음' if pd is None else '있음'} · {sk} {'없음' if ps is None else '있음'}")
        return None
    if pd["at_edge"] or ps["at_edge"]:
        if verbose:
            print(f"  [지붕시차] 봉우리가 탐색 경계에 있다 — 옮기지 않는다 "
                  f"({sk} {ps['px']} · {dst_key} {pd['px']})")
        return None
    nx, ny = round(pd["px"][0] - ps["px"][0], 2), round(pd["px"][1] - ps["px"][1], 2)
    if (nx * nx + ny * ny) ** 0.5 > MAX_PX:
        if verbose:
            print(f"  [지붕시차] ({nx:+.1f},{ny:+.1f}) px 는 시차로 보기에 크다 — 옮기지 않는다")
        return None
    return {"px": (nx, ny), "src_scene": sk, "src_peak": list(ps["px"]),
            "dst_peak": list(pd["px"]), "n": len(use),
            "src_gain": round(ps["max_gain"], 3), "dst_gain": round(pd["max_gain"], 3),
            "back_px": [round(bx, 2), round(by, 2)]}


def apply(site, rings_px, *, verbose=False):
    """창 안 GT 링을 시차만큼 **전부 같이** 옮겨 돌려준다. 옮겼으면 `site` 에 적는다.

    재는 것은 이 지번 건물이지만 **옮기는 것은 창 안 전부**다. 옆 지번 건물까지 같은 양을
    옮겨야 건물끼리의 거리가 보존되고(이격 표의 값이 안 움직인다), 한 그림 안에서 어떤
    동은 옮기고 어떤 동은 안 옮긴 상태가 되지 않는다.

    **옮겼다는 사실을 결과에 남긴다** — 이 폴더의 다른 보정과 같은 규칙이다(영상 지오레퍼런스
    · 필지 레이어 편이). 그림만 조용히 맞추면 왜 값이 바뀌었는지 나중에 아무도 모른다.
    """
    key = ((site.get("scene") or {}).get("key")) or ""
    if not key or not rings_px:
        return rings_px
    m = measure(key, rings_px, parcel_px=_parcel_px(site), verbose=verbose)
    if not m:
        return rings_px
    nx, ny = m["px"]
    if max(abs(nx), abs(ny)) < MIN_PX:
        if verbose:
            print(f"  [지붕시차] 잔차 ({nx:+.1f},{ny:+.1f}) px — 옮길 것이 없다")
        return rings_px
    res = float((site.get("scene") or {}).get("res_m") or 0.5)
    # **다시 불려도 두 번 적지 않는다.** 링은 매번 GT 파일에서 새로 읽어 오므로 옮기는
    # 것 자체는 몇 번을 해도 같은 자리다(겹쳐 밀리지 않는다). 그런데 저장된 결과를 다시
    # 그리는 길([[report/single.py]])이 이 함수를 또 부르므로, 같은 값이면 적기만 건너뛴다.
    again = site.get("gt_nudge_px") == [nx, ny]
    site["gt_nudge"] = dict(m, px=[nx, ny], res_m=res)
    site["gt_nudge_px"] = [nx, ny]
    if not again:
        site.setdefault("notes", []).append(
            f"이식 GT 를 ({nx:+.1f},{ny:+.1f}) px · ({nx*res:+.1f},{-ny*res:+.1f}) m (동,북) 옮겼다 — "
            f"이 GT 는 {config.SCENES[m['src_scene']]['ko']} 장면에서 옮겨 온 것이라 촬영각이 "
            f"다른 이 영상에서는 지붕이 그만큼 어긋난다. 이 지번 건물 {m['n']}동의 봉우리를 "
            f"두 장면에서 같은 자로 재어 뺀 값이다({m['src_scene']} {tuple(m['src_peak'])} → "
            f"{key} {tuple(m['dst_peak'])} px · 이득 {m['src_gain']:.2f}/{m['dst_gain']:.2f}). "
            f"창 안 건물을 다 같이 옮기므로 건물끼리의 거리와 면적은 바뀌지 않는다")
    if verbose:
        print(f"  [지붕시차] {key} GT 를 ({nx:+.1f},{ny:+.1f}) px 옮겼다 · "
              f"{m['src_scene']} {tuple(m['src_peak'])} → {key} {tuple(m['dst_peak'])} · "
              f"이 지번 {m['n']}동 · 이득 {m['src_gain']:.2f}/{m['dst_gain']:.2f}")
    return [[(x + nx, y + ny) for x, y in r] for r in rings_px]


# ── 확인 도구 ────────────────────────────────────────────────────────────────
def _report(dirs):
    """저장된 결과의 창에서 시차 잔차를 **다시 잰다** — 보정이 먹었으면 0 에 가까워야 한다."""
    from sitecheck.steps import georef
    from sitecheck import gt as GT
    print(f"{'주소':30s} {'장면':8s} {'동':>3s} {'1차봉우리':>12s} {'2차봉우리':>12s} "
          f"{'이득':>11s} {'재보니':>12s} {'적용됨':>12s} {'남은':>12s}")
    print("─" * 110)
    for d in dirs:
        d = Path(d)
        f = next((p for p in (d / "result.json", d / "demo.json") if p.exists()), None)
        if f is None:
            continue
        res = json.loads(f.read_text("utf-8"))
        site = res["site"]
        georef.migrate(site)
        key = (site.get("scene") or {}).get("key") or "—"
        had = site.get("gt_nudge_px")
        # **모델 경로 결과에는 해당 없다.** 이 도구는 GT 링을 재므로(`rings_in_window`),
        # 모델이 낸 결과 폴더를 넣으면 표에 줄은 나오는데 「재보니」는 그 창의 GT 를 잰 값이고
        # 「적용됨」은 늘 「—」다 — 숫자가 나오면서 뜻이 없는 상태다. 그 폴더는 조용히
        # 빠지는 것보다 **해당 없다고 찍는 편이 낫다**(아래 「이식 아님」과 같은 판단이다).
        if not str(((res.get("provenance") or {}).get("model") or {}).get("building")
                   ).startswith("GT"):
            print(f"{d.name[:28]:30s} {key:8s} {'—':>3s} {'—':>12s} {'—':>12s} "
                  f"{'—':>11s} {'모델 경로':>12s} {'—':>12s} {'—':>12s}")
            continue
        if not ported(key):
            # 실패가 아니라 **해당 없음**이다 — 사람이 그 영상을 보고 그린 GT 라 옮길 것이 없다.
            print(f"{d.name[:28]:30s} {key:8s} {'—':>3s} {'—':>12s} {'—':>12s} "
                  f"{'—':>11s} {'이식 아님':>12s} {'—':>12s} {'—':>12s}")
            continue
        try:
            rings, _win_unused = GT.rings_in_window(site)
        except Exception as e:                                   # noqa: BLE001
            print(f"{d.name[:28]:30s} {key:8s}  {type(e).__name__}: {e}")
            continue
        # **링은 GT 파일에서 온 그대로 잰다**(저장된 보정을 미리 먹이지 않는다). 그러면
        # 「재보니」는 지금 이 창에서 나오는 값이고, 「남은」은 그것과 저장된 결과가 실제로
        # 쓴 값의 차 — 0 이면 저장된 그림이 지금 잣대와 맞는다는 뜻이다. 링을 미리 밀어서
        # 재면 1차 쪽도 같이 밀려(원본 자리로 되돌릴 때 같은 양을 빼므로) 남은 양이 늘 그대로
        # 나온다.
        m = measure(key, rings, parcel_px=_parcel_px(site))
        if not m:
            print(f"{d.name[:28]:30s} {key:8s} {len(rings):3d} {'—':>12s} {'—':>12s} "
                  f"{'—':>11s} {'못 잼':>12s} {str(had or '—'):>12s} {'—':>12s}")
            continue
        nx, ny = m["px"]
        hx, hy = (had or [0, 0])
        print(f"{d.name[:28]:30s} {key:8s} {m['n']:3d} "
              f"{('(%+.1f,%+.1f)' % tuple(m['src_peak'])):>12s} "
              f"{('(%+.1f,%+.1f)' % tuple(m['dst_peak'])):>12s} "
              f"{('%.2f/%.2f' % (m['src_gain'], m['dst_gain'])):>11s} "
              f"{('(%+.1f,%+.1f)' % (nx, ny)):>12s} {str(had or '—'):>12s} "
              f"{('(%+.1f,%+.1f)' % (nx - hx, ny - hy)):>12s}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "--all":
        args = [str(p.parent) for pat, name in ((config.OUT, "result.json"),
                                                (config.HERE / "demo", "demo.json"),
                                                (config.HERE / "demo_cmp" / "t1", "demo.json"),
                                                (config.HERE / "demo_cmp" / "t2", "demo.json"))
                for p in sorted(Path(pat).glob(f"*/{name}"))]
    _report(args)
