"""정사영상 지오레퍼런스 편이 **측정**.

**필지만의 문제가 아니다.** 연속지적도 필지와 GIS건물통합정보 footprint 가 **같은 방향으로
같이** 어긋난다 — 대구에서 footprint 가 지붕 위쪽 도로를 덮는 것을 확인했다. 두 레이어는
서로 다른 출처인데 함께 틀릴 수는 없으므로, 어긋난 쪽은 **영상**이다.

여기는 **재는 곳**이고, 그 값을 쓰는 곳은 [[georef.py]] 다 — 재어 놓은 양만큼 **영상의
지오트랜스폼을 되돌린다.** 지도 기하는 아무도 옮기지 않는다. 그러므로 아래 값의 부호는
"지도 기하를 이만큼 옮기면 영상과 맞는다"는 뜻이고, `georef` 가 그것을 뒤집어 영상에 넣는다.

편이는 **footprint 경계 ↔ 영상 엣지**로 잰다. footprint 는 건물 외곽선이고 영상에는 건물
모서리가 뚜렷해 대응이 직접적이다. 필지 경계(담장·연석)로 재면 신호가 약하고, 표본이 적으면
도로 연석이나 장면 경계 같은 엉뚱한 선형 구조에 최댓값이 걸린다.

측정값(라벨 crop 영역, footprint 500~1,600동):

    대구      (+8,  0) px = (+4.0,  0.0) m   이득 1.451
    구미      (+8, -2) px = (+4.0, -1.0) m   이득 1.185
    남동공단  (+16,-12) px = (+8.0, -6.0) m   이득 1.513
    창원      (+12, -6) px = (+6.0, -3.0) m   이득 1.485   ← 측정 기록만. 장면은 제외됨

네 장면 모두 동쪽 4~8 m 로 방향이 일치한다 — 개별 잡음이 아니라 계통 편이다. 창원
측정값을 지우지 않고 남긴 이유는 **계통성의 근거가 네 장면 일치라는 사실 자체**이기
때문이다. 다만 창원은 영상 등록부에서 빠졌으므로(`settings.EXCLUDED_SCENES`) 아래
`VERIFIED` 에는 넣지 않는다.

**여기서 재는 것은 영상 편이뿐이다.** 대구는 이 보정을 받은 뒤에도 **필지 레이어만**
24 m 남쪽에 남는다 — 장면 편이가 아니라 그 레이어 자신의 것이라 `parcel_bias.py` 가 따로
잰다. 두 보정을 한 값으로 합치면 맞아 있던 footprint 가 그만큼 어긋난다.

`VERIFIED` 표의 값도 그 방향이다("벡터를 이만큼 옮기면 영상과 맞는다"). `georef` 는 같은
양을 영상 원점에서 뺀다.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from sitecheck import settings as config

# **미터로 둔다.** 픽셀 상수는 해상도가 바뀌면 뜻이 달라진다 — 0.5 m/px 에서 48 px 는
# ±24 m 지만 0.25 m 항공영상에서는 ±12 m 라, 같은 코드가 새 영상에서 조용히 좁아진다.
SEARCH_M = 24.0        # 탐색 반경(m)
STEP_M = 1.0           # 탐색 간격(m)
LINE_M = 1.5           # footprint 경계선 두께(m)
MAX_SHIFT_M = 20.0     # 이보다 큰 편이는 정합 실패로 본다
MIN_RINGS = 30
MIN_RINGS_LOCAL = 6   # 국소 창에서 요구하는 최소 footprint 수 — 이보다 적으면 장면 평균으로
MIN_GAIN = 1.05
CACHE = config.OUT / "_cache"


def _res(scene_key):
    """장면 해상도(m/px). meta 에 없으면 SkySat 정사영상 기본값 0.5."""
    try:
        m = config.scene_meta(scene_key) or {}
        r = float(m.get("res_m") or 0)
        return r if r > 0 else 0.5
    except Exception:                                        # noqa: BLE001
        return 0.5


def _px(m_val, res, lo=1):
    return max(lo, int(round(m_val / res)))

# 장면별 검수 확정값 — 벡터를 이만큼 옮기면 영상과 맞는다(px, 0.5 m/px).
# **이것은 이제 대비책일 뿐이다.** 실제 판정에는 `estimate_local()` 이 필지 주변에서
# 그때그때 잰 값이 쓰이고(`s0_locate._align_parcels` 가 국소를 먼저 부른다), 여기 값은
# 국소 정합이 실패했을 때만 나선다. 그래서 등록부에 없는 새 영상도 그대로 돈다 —
# 표에 없으면 `estimate()` 가 장면 전체에서 한 번 재고 `out/_cache` 에 남긴다.
VERIFIED = {
    "daegu": (8, 0),
    "gumi": (8, -2),
    "namdong": (16, -12),
}


def _edge_map(scene_dir):
    """영상 엣지 강도. nodata 경계는 지운다 — 가장 강한 엣지라 안 지우면 결과를 지배한다."""
    from PIL import Image
    from scipy.ndimage import binary_erosion, gaussian_filter, sobel
    Image.MAX_IMAGE_PIXELS = None
    g = np.asarray(Image.open(Path(scene_dir) / "scene.png").convert("L"), np.float32)
    valid = g > 6
    gb = gaussian_filter(g, 1.2)
    e = np.hypot(sobel(gb, 0), sobel(gb, 1))
    inner = binary_erosion(valid, np.ones((15, 15), bool))
    e = np.where(inner, e, 0.0)
    return e / (e[inner].mean() + 1e-6 if inner.any() else e.mean() + 1e-6)


def _rings(polys_px):
    """폴리곤 목록 → 외곽 링 좌표배열. shapely 도형과 **좌표 리스트**를 다 받는다.

    GT 는 파일에 `[[x, y], …]` 로 들어 있어([[gt_parallax.py]]) shapely 로 감쌌다 푸는
    왕복이 공짜가 아니다 — 여기서 쓰는 것은 외곽 링뿐이므로 온 대로 받는다.
    """
    out = []
    for p in polys_px:
        if not hasattr(p, "geom_type"):
            a = np.asarray(p, np.float64)
            if a.ndim == 2 and a.shape[1] == 2 and len(a) >= 3:
                out.append(a)
            continue
        for q in (p.geoms if p.geom_type.startswith("Multi") else [p]):
            if q.geom_type == "Polygon" and not q.is_empty:
                out.append(np.asarray(q.exterior.coords, np.float64))
    return out


def estimate_local(scene_key, footprints_px, window_px, *, search_px=None,
                   min_rings=MIN_RINGS_LOCAL, verbose=False):
    """**필지 주변 창에서만** 편이를 잰다 — 편이가 장면 안에서 위치에 따라 달라지기 때문이다.

    장면 하나에 상수 하나를 쓰면 평균만 맞고 개별 필지는 여전히 어긋난다(실측: 대구
    장면 평균 +8 px 를 적용해도 호산동 필지는 수십 m 밀려 있었다). 정사보정 오차는
    지형 기복을 타므로 위치에 따라 변한다.

    창은 필지 bbox + 여유다. 창이 좁으면 엣지맵 계산도 싸다(장면 전체는 1 억 화소).
    """
    r = peak(scene_key, footprints_px, window_px, search_px=search_px, min_rings=min_rings)
    if r is None:
        return None
    res = _res(scene_key)
    dx, dy = r["px"]
    if not r["zero"] or r["at_edge"] or r["gain"] < MIN_GAIN:
        if verbose:
            why = "경계" if r["at_edge"] else f"이득 {r['gain']:.3f}"
            print(f"  [국소정합] {scene_key} 국소 보정 안 함 — ({dx:+d},{dy:+d}) {why}")
        return None
    if verbose:
        print(f"  [국소정합] {scene_key} ({dx:+d},{dy:+d}) px "
              f"({dx*res:+.1f},{dy*res:+.1f} m) · footprint {r['n']}동 · 이득 {r['gain']:.3f}")
    return dx, dy, r["gain"], r["n"]


_GRAY = {}


def gray(scene_key):
    """장면 회색조(uint8) — **한 번만 디코드하고 캐시한다.**

    한 주소를 처리하는 동안 이 함수가 여러 번 불린다(1차 엣지 정합 · 이식 GT 시차 보정).
    PNG 는 부분 디코드가 안 되므로 열 때마다 장면 전체를 푼다(대구 2.2 s · 400 MB float).
    uint8 로 한 장만 들고 있으면 100 MB 로 끝나고 두 번째부터는 공짜다.
    """
    if scene_key not in _GRAY:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        sd = config.SCENES[scene_key]["dir"].resolve()
        _GRAY[scene_key] = np.asarray(Image.open(sd / "scene.png").convert("L"), np.uint8)
    return _GRAY[scene_key]


def _edge_crop(scene_key, window_px, pad_extra):
    """창 + 여유의 **정규화된 엣지 강도**와 그 원점 (E, wx0, wy0). 못 만들면 None.

    `peak` 과 `peak_sub` 가 같은 것을 본다 — 두 곳에서 따로 만들면 잣대가 갈린다.
    """
    from scipy.ndimage import binary_erosion, gaussian_filter, sobel
    wx0, wy0, wx1, wy1 = window_px
    pad = int(pad_extra) + 8
    wx0, wy0 = int(wx0) - pad, int(wy0) - pad
    wx1, wy1 = int(wx1) + pad, int(wy1) + pad
    full = gray(scene_key)
    H, W = full.shape
    wx0, wy0 = max(0, wx0), max(0, wy0)
    wx1, wy1 = min(W, wx1), min(H, wy1)
    if wx1 - wx0 < 64 or wy1 - wy0 < 64:
        return None
    g = full[wy0:wy1, wx0:wx1].astype(np.float32)
    valid = g > 6
    if valid.mean() < 0.3:
        return None
    gb = gaussian_filter(g, 1.2)
    E = np.hypot(sobel(gb, 0), sobel(gb, 1))
    inner = binary_erosion(valid, np.ones((11, 11), bool))
    E = np.where(inner, E, 0.0)
    E /= (E[inner].mean() + 1e-6) if inner.any() else (E.mean() + 1e-6)
    return E, wx0, wy0


def _mask(rings, shape_hw, wx0, wy0, line_w, search_px, off=(0.0, 0.0)):
    """링 테두리를 크롭 좌표에 그린 불리언 마스크와 그린 링 수. `off` 는 소수 픽셀 이동."""
    from PIL import Image, ImageDraw
    hh, ww = shape_hw
    im = Image.new("1", (ww, hh), 0)
    d = ImageDraw.Draw(im)
    n_in = 0
    for r in rings:
        pts = [(x - wx0 + off[0], y - wy0 + off[1]) for x, y in r]
        if len(pts) >= 2 and any(-search_px <= a <= ww + search_px and
                                 -search_px <= b <= hh + search_px for a, b in pts):
            d.line(pts, fill=1, width=line_w)
            n_in += 1
    M = np.asarray(im, bool)
    return (M if M.any() else None), n_in


def peak_sub(scene_key, polys_px, window_px, *, search_px=6, sub=2,
             min_rings=1, line_m=LINE_M, tie_tol=0.0):
    """**0.5 px 격자**에서 봉우리를 찾는다 — 정수 격자가 못 닿는 자리에 최적점이 있다.

    왜 필요한가. 정수로만 재면 최적점이 반 픽셀 옆일 때 그 근처 두 점만 보게 되는데,
    지붕이 비스듬한 건물에서는 x 를 반 픽셀 잘못 잡으면 y 의 최적점이 1 px 넘게 따라
    움직인다(실측 호산동 702-5 · 2차: 정수 격자 (0,+2) 이득 1.08 · 0.5 px 격자 (−0.5,+0.5)
    이득 1.47 — **같은 건물 같은 영상인데 답이 다르다**).

    후보마다 다시 그리지 않는다. 소수부만 다른 마스크 `sub × sub` 장을 미리 그려 두고
    각각을 정수로 굴린다 — 그림 그리기는 4번, 점수는 격자 전부에서 난다.

    `sub` = 한 픽셀을 몇 등분할지(2 = 0.5 px). 나머지 인자와 반환은 `peak` 과 같다.
    """
    res = _res(scene_key)
    rings = _rings(polys_px)
    if len(rings) < min_rings:
        return None
    crop = _edge_crop(scene_key, window_px, search_px + 1)
    if crop is None:
        return None
    E, wx0, wy0 = crop
    line_w = _px(line_m, res)
    sub = max(1, int(sub))
    n_in, grid = 0, {}
    for fy in range(sub):
        for fx in range(sub):
            off = (fx / sub, fy / sub)
            M, n_in = _mask(rings, E.shape, wx0, wy0, line_w, search_px, off=off)
            if M is None:
                return None
            for iy in range(-search_px, search_px + 1):
                for ix in range(-search_px, search_px + 1):
                    v = float(E[np.roll(np.roll(M, iy, axis=0), ix, axis=1)].mean())
                    grid[(ix + off[0], iy + off[1])] = v
    if n_in < min_rings or not grid:
        return None
    zero = grid.get((0.0, 0.0))
    bk = max(grid, key=lambda k: grid[k])
    top = grid[bk]
    if tie_tol > 0 and top > 0:
        lim = top * (1.0 - tie_tol)
        bk = min((k for k, v in grid.items() if v >= lim),
                 key=lambda k: (k[0] * k[0] + k[1] * k[1], abs(k[0]), abs(k[1])))
    return {"px": (bk[0], bk[1]), "score": grid[bk], "zero": zero,
            "gain": (grid[bk] / zero) if zero else 0.0,
            "max_gain": (top / zero) if zero else 0.0, "n": n_in,
            "at_edge": abs(bk[0]) >= search_px - 0.5 or abs(bk[1]) >= search_px - 0.5,
            "search_px": search_px}



def peak(scene_key, polys_px, window_px, *, search_px=None, min_rings=MIN_RINGS_LOCAL,
         line_m=LINE_M, step_px=None, tie_tol=0.0):
    """폴리곤 테두리가 영상 엣지에 가장 잘 얹히는 정수 편이 — **문턱 없이 봉우리 자체.**

    `estimate_local` 이 쓰는 자와 같은 자다. 다만 여기서는 이득·경계 판정을 하지 않고
    잰 값을 그대로 돌려준다 — 무엇을 보정으로 채택할지는 부르는 쪽마다 다르기 때문이다
    (1차 엣지 정합은 이득이 있어야 옮기고, 이식 GT 시차 보정([[gt_parallax.py]])은 두
    장면의 봉우리를 **빼서** 쓰므로 각각의 이득은 채택 기준이 아니다).

    `step_px` — 탐색 간격. 기본은 `STEP_M`(1 m = 0.5 m/px 영상에서 2 px)이라 **홀수 px 를
    낼 수 없다.** 1 m 편이를 쫓는 1차 엣지 정합에는 그것으로 충분하지만, 0.5 m 단위를 봐야
    하는 자리는 `step_px=1` 로 부른다.

    `tie_tol` — **비긴 봉우리는 0 에 가까운 쪽으로 고른다.** 최고점의 (1−tie_tol) 안에 든
    후보 중 원점에서 가장 가까운 것을 고른다. 0 이면 순수 최고점(기본 · 옛 동작 그대로).
    이 잣대가 필요한 이유는 두 가지다 — 공장 지붕은 베이가 반복돼 봉우리가 여러 개 서고
    (실측 호산동 1차: dx −4 에서 2.271 · dx 0 에서 2.264 로 사실상 동점), 신호가 약한
    창에서는 최고점이 잡음이라 0 이 후보에 들어와 **저절로 안 옮기게** 된다.

    반환 {"px": (dx, dy), "score", "zero", "gain", "max_gain", "n", "at_edge", "search_px"}
    · 못 재면 None.
    """
    res = _res(scene_key)
    if search_px is None:
        search_px = _px(SEARCH_M, res, 8)
    step = int(step_px) if step_px else _px(STEP_M, res)
    rings = _rings(polys_px)
    if len(rings) < min_rings:
        return None
    crop = _edge_crop(scene_key, window_px, search_px)
    if crop is None:
        return None
    E, wx0, wy0 = crop
    M, n_in = _mask(rings, E.shape, wx0, wy0, _px(line_m, res), search_px)
    if n_in < min_rings or M is None:
        return None

    best, zero, grid = (0, 0, -1.0), None, {}
    for dy in range(-search_px, search_px + 1, step):
        for dx in range(-search_px, search_px + 1, step):
            Ms = np.roll(np.roll(M, dy, axis=0), dx, axis=1)
            v = float(E[Ms].mean()) if Ms.any() else 0.0
            grid[(dx, dy)] = v
            if dx == 0 and dy == 0:
                zero = v
            if v > best[2]:
                best = (dx, dy, v)
    top = best[2]
    if tie_tol > 0 and top > 0:
        lim = top * (1.0 - tie_tol)
        dx, dy = min((k for k, v in grid.items() if v >= lim),
                     key=lambda k: (k[0] * k[0] + k[1] * k[1], abs(k[0]), abs(k[1])))
        best = (dx, dy, grid[(dx, dy)])
    return {"px": (best[0], best[1]), "score": best[2], "zero": zero,
            "gain": (best[2] / zero) if zero else 0.0,
            "max_gain": (top / zero) if zero else 0.0, "n": n_in,
            "at_edge": abs(best[0]) >= search_px - step or abs(best[1]) >= search_px - step,
            "search_px": search_px}


def estimate(scene_key, footprints_px, *, search_px=None, verbose=False):
    """(dx, dy, 점수, 이득) — footprint 경계가 영상 엣지에 가장 잘 얹히는 정수 편이."""
    from PIL import Image, ImageDraw
    res = _res(scene_key)
    if search_px is None:
        search_px = _px(SEARCH_M, res, 8)
    step = _px(STEP_M, res)
    line_w = _px(LINE_M, res)
    max_shift_px = _px(MAX_SHIFT_M, res)
    rings = _rings(footprints_px)
    if len(rings) < MIN_RINGS:
        if verbose:
            print(f"  [영상정합] {scene_key} footprint {len(rings)}동 — 표본 부족")
        return 0, 0, 0.0, 0.0
    E = _edge_map(config.SCENES[scene_key]["dir"].resolve())
    H, W = E.shape
    xs = np.concatenate([r[:, 0] for r in rings])
    ys = np.concatenate([r[:, 1] for r in rings])
    bx0, by0 = int(xs.min()) - search_px - 4, int(ys.min()) - search_px - 4
    bw = int(xs.max()) - bx0 + search_px + 4
    bh = int(ys.max()) - by0 + search_px + 4
    if bw < 8 or bh < 8 or bw * bh > 120_000_000:
        return 0, 0, 0.0, 0.0
    im = Image.new("1", (bw, bh), 0)
    d = ImageDraw.Draw(im)
    for r in rings:
        pts = [(x - bx0, y - by0) for x, y in r]
        if len(pts) >= 2:
            d.line(pts, fill=1, width=line_w)
    M = np.asarray(im, bool)
    if not M.any():
        return 0, 0, 0.0, 0.0

    best, zero = (0, 0, -1.0), None
    for dy in range(-search_px, search_px + 1, step):
        for dx in range(-search_px, search_px + 1, step):
            sy0, sx0 = by0 + dy, bx0 + dx
            sy1, sx1 = sy0 + bh, sx0 + bw
            if sx0 < 0 or sy0 < 0 or sx1 > W or sy1 > H:
                continue
            v = float(E[sy0:sy1, sx0:sx1][M].mean())
            if dx == 0 and dy == 0:
                zero = v
            if v > best[2]:
                best = (dx, dy, v)
    gain = (best[2] / zero) if zero else 0.0
    at_edge = abs(best[0]) >= search_px - step or abs(best[1]) >= search_px - step
    too_far = (best[0] ** 2 + best[1] ** 2) ** 0.5 > max_shift_px
    if zero is None or at_edge or too_far or gain < MIN_GAIN:
        if verbose:
            why = "탐색 경계" if at_edge else "과대 편이" if too_far else f"이득 {gain:.3f}"
            print(f"  [영상정합] {scene_key} 보정 안 함 — ({best[0]:+d},{best[1]:+d}) {why}")
        return 0, 0, (zero or 0.0), gain
    if verbose:
        print(f"  [영상정합] {scene_key} ({best[0]:+d},{best[1]:+d}) px "
              f"({best[0] * res:+.1f},{best[1] * res:+.1f} m) 이득 {gain:.3f}")
    return best[0], best[1], best[2], gain


def shift_for(scene_key, footprints_px=None, *, force=False, verbose=False):
    """장면별 벡터 보정 편이(px). 검수값이 있으면 그것을 쓴다."""
    if scene_key in VERIFIED and not force:
        return VERIFIED[scene_key]
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"image_shift_{scene_key}.json"
    if f.exists() and not force:
        d = json.loads(f.read_text("utf-8"))
        return int(d["dx"]), int(d["dy"])
    dx, dy, sc, gain = estimate(scene_key, footprints_px or [], verbose=verbose)
    # **실패한 추정은 캐시하지 않는다.** 예전에는 (0,0) 도 그대로 적었는데, 그러면 다음
    # 실행이 그 파일을 읽어 '편이 없음'으로 굳는다 — 새 장면에서 조용히 보정을 끄는
    # 결과가 된다(실측: 표본을 안 넘겨 부른 daegu2 가 0 으로 굳었다).
    if gain >= MIN_GAIN and sc > 0:
        f.write_text(json.dumps({"scene": scene_key, "dx": dx, "dy": dy,
                                 "score": round(sc, 4), "gain": round(gain, 4)},
                                ensure_ascii=False, indent=1), "utf-8")
    elif verbose:
        print(f"  [영상정합] {scene_key} 추정 실패 — 캐시에 적지 않는다(다음에 다시 잰다)")
    return dx, dy
