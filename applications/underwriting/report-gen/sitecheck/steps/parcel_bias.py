"""연속지적도 필지 **레이어 고유 편이** 보정.

`georef.py` 가 고치는 것은 **영상** 편이다. 그런데 대구에서는 영상을 고쳐도 필지가 맞지
않는다 — GIS건물통합정보 footprint 와 영상이 서로 맞는데 **필지만** 남쪽으로 24 m 밀려
있다(지적불부합). 남의 문제가 아니라 필지 레이어 자신의 편이다.

측정(데모 6주소 · GIS건물통합정보 PNU 짝, 2026-08-18):

    장면      지금 내포율   맞추려면 옮길 양      맞춘 뒤
    대구      0.33~0.54    (−6, +24) m         0.90~0.99
    남동공단  0.61~0.80    (−8,  −6) m         0.95~1.00
    구미      0.85~0.99    (−3,  −1) m         0.89~1.00

대구는 **건물 한 채 크기(24 m)** 가 밀려 있었다. 필지가 그만큼 남쪽에 있으면 그 위에서
내리는 판정이 죄다 남의 땅 위에서 이뤄진다 — 야적 탐지 영역(필지−건물)도, 대지경계선
이격도, 미등록 귀속도. 구미는 거의 0 이라 이 보정이 대구 전용 손질이 아니라는 것도
같은 표가 말해 준다(세 장면 모두 같은 절차로 재고, 이득이 없으면 안 옮긴다).

**어느 쪽이 틀렸는가**는 정해져 있다. GIS건물통합정보 footprint 는 이 지역에서 영상과
맞는다(모델·GT 폴리곤과 짝지어 잰 잔차 중앙값 0.0~0.7 m · IoU 0.88~0.99). 영상과 맞는
레이어가 기준이고, 어긋난 필지가 옮길 대상이다.

무엇으로 재는가 — **PNU 로 짝지은 내포율**
------------------------------------------
GIS건물통합정보의 한 행에는 그 건물이 선 지번(PNU)이 들어 있다. 그러므로 "이 건물은
저 필지 안에 있어야 한다"를 **추측 없이** 말할 수 있다. 필지 레이어를 평행이동하며
`자기 PNU 필지 안에 든 footprint 면적 / footprint 면적` 의 평균이 최대가 되는 점을 찾는다.

'건물이 아무 필지에나 들면 된다'로 재면 안 된다 — 공장은 필지 북측에 붙고 남측에 마당을
두는 배치가 많아 필지를 북으로 밀수록 값이 계속 올라가고 최적점이 없다(seglab
`src/parcel_align.py` 에 그 실측이 있다). PNU 로 묶으면 북으로 너무 밀면 **자기** 건물에서
벗어나므로 내부에 뚜렷한 봉우리가 생긴다(대구 0.33 → 0.99).

필지 경계선 ↔ 영상 엣지로 재는 방법(seglab 의 그 파일)은 장면 전체 342링에서는 되지만
주소 하나 주변 12~75링에서는 담장·연석·장면경계에 최댓값이 걸려 못 쓴다(실측: 같은 구미
장면에서 주소별로 +44 px 과 −6 px 이 나왔다). 그래서 영상을 아예 안 보고 두 벡터
레이어의 관계만으로 잰다 — 싸고, 표본이 주소당 20~90짝이라 안정적이다.

    python -m sitecheck.steps.parcel_bias demo/*/   저장된 결과의 필지 내포율을 잰다
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

SEARCH_M = 40.0      # 탐색 반경(m) — 대구 실측 24 m 의 1.5배
COARSE_M = 4.0       # 굵은 격자
FINE_M = 1.0         # 봉우리 주변만 다시
MIN_PAIRS = 8        # 이보다 적으면 표본 잡음이다
MIN_AREA_M2 = 30.0   # 작은 부속건축물은 경계에 걸려 방향을 흐린다
MIN_FRAC = 0.60      # 맞춘 뒤에도 이만큼 안 들면 짝짓기 자체를 믿을 수 없다
MIN_GAIN = 0.08      # 내포율이 이만큼은 올라야 옮긴다
TOL_M = 1.5          # 이보다 작은 이동은 하지 않는다(필지 경계 표기 오차 수준)
PAD_DEG = 0.0005     # footprint 조회 여유(≈50 m) — 경계에 걸친 건물도 온전히 가져온다


def _utm():
    from pyproj import Transformer
    return Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)


def pairs(site):
    """(footprint, 그 footprint 의 PNU 필지) 짝 — 둘 다 EPSG:5179 미터.

    **둘 다 조회한 좌표 그대로다.** 영상 보정은 영상 쪽에서 하므로([[georef.py]]) 여기
    비교에는 들어오지 않는다 — 그래서 여기서 재는 값은 순수하게 **두 지도 레이어 사이의
    어긋남**이고, 영상을 어떻게 보정했는지와 무관하다(예전에는 footprint 를 영상 쪽으로
    끌어온 뒤에 재서, 영상 보정이 바뀌면 이 값도 흔들렸다).
    """
    from shapely.geometry import shape
    from shapely.ops import transform, unary_union
    from sitecheck.vendor import gisdb

    par_ll = {}
    if site.get("pnu") and site.get("parcel"):
        par_ll[str(site["pnu"])] = shape(site["parcel"])
    for n in site.get("neighbors") or []:
        try:
            par_ll[str(n.get("pnu"))] = shape(n["geometry"])
        except Exception:                                    # noqa: BLE001
            continue
    if not par_ll:
        return []
    try:
        recs = gisdb.near(unary_union(list(par_ll.values())).buffer(PAD_DEG).bounds)
    except Exception:                                        # noqa: BLE001
        return []
    if not recs:
        return []
    tr = _utm()
    par = {}
    for k, g in par_ll.items():
        try:
            par[k] = transform(tr.transform, g)
        except Exception:                                    # noqa: BLE001
            continue
    out = []
    for r in recs:
        g = r["geometry"]
        p = str(r.get("pnu") or "")
        if p not in par or g is None:
            continue
        try:
            fm = transform(tr.transform, g)
        except Exception:                                    # noqa: BLE001
            continue
        if fm.is_valid and fm.area >= MIN_AREA_M2:
            out.append((fm, par[p]))
    return out


def _frac(ps, dx, dy):
    from shapely.affinity import translate
    if dx == 0.0 and dy == 0.0:
        return sum(f.intersection(p).area / f.area for f, p in ps) / len(ps)
    return sum(f.intersection(translate(p, dx, dy)).area / f.area for f, p in ps) / len(ps)


def estimate(site, *, search_m=SEARCH_M, coarse_m=COARSE_M, fine_m=FINE_M,
             min_pairs=MIN_PAIRS):
    """필지 레이어를 얼마나 옮겨야 자기 건물을 담는가 → dict. 못 재면 None.

    부호는 EPSG:5179 미터(동·북 양수)다. 굵게 훑고 봉우리 주변만 다시 본다 — 굵은
    격자만 쓰면 4 m 눈금에 반올림되고, 처음부터 1 m 로 훑으면 6,561 번을 잰다.
    """
    ps = pairs(site)
    if len(ps) < min_pairs:
        return None
    n = int(round(search_m / coarse_m))
    grid = [(i * coarse_m, j * coarse_m) for j in range(-n, n + 1) for i in range(-n, n + 1)]
    at0 = _frac(ps, 0.0, 0.0)
    best = max(grid, key=lambda d: _frac(ps, d[0], d[1]))
    k = int(round(coarse_m / fine_m))
    fine = [(best[0] + i * fine_m, best[1] + j * fine_m)
            for j in range(-k, k + 1) for i in range(-k, k + 1)]
    bx, by = max(fine, key=lambda d: _frac(ps, d[0], d[1]))
    return {"dx": round(bx, 1), "dy": round(by, 1), "pairs": len(ps),
            "frac0": round(at0, 3), "frac": round(_frac(ps, bx, by), 3),
            "at_edge": abs(best[0]) >= search_m - coarse_m or abs(best[1]) >= search_m - coarse_m}


def apply(site, *, force=False, verbose=False):
    """잰 만큼 필지·인접필지를 옮긴다. 옮겼으면 True.

    **footprint 와 영상에는 걸지 않는다** — 이것은 연속지적도 레이어 하나만의 편이다.
    영상 보정([[georef.py]])에 합치면 맞아 있던 footprint 가 그만큼 어긋난다. 그래서 따로
    `parcel_bias_m` 에 담고 여기서 한 번만 적용한다.

    **지도 쪽에서 무언가를 옮기는 것은 이 함수뿐이다.** 그러므로 내보낸 필지 좌표가 조회한
    값과 다를 수 있는 경우도 이것(과 데모의 수동 보정) 하나뿐이고, 얼마나 옮겼는지는
    `parcel_bias_m` 에 남는다.
    """
    if site.get("parcel_bias_m") is not None and not force:
        return False
    if not site.get("parcel") or not site.get("scene"):
        return False
    site.setdefault("notes", [])
    r = estimate(site)
    if not r:
        site["parcel_bias_m"] = [0.0, 0.0]
        site["notes"].append("필지 레이어 편이를 재지 못했다 — 주변 GIS건물통합정보에서 "
                             f"PNU 가 맞는 건물이 {MIN_PAIRS}동 미만이다. 필지가 영상과 "
                             "어긋난 채로 나올 수 있다")
        return False
    site["parcel_bias"] = r
    dist = (r["dx"] ** 2 + r["dy"] ** 2) ** 0.5
    why = None
    if r["at_edge"]:
        why = f"최적점이 탐색 경계({SEARCH_M:.0f} m)에 걸렸다 — 평행이동으로 볼 수 없다"
    elif r["frac"] < MIN_FRAC:
        why = (f"맞춘 뒤 내포율이 {r['frac']:.2f} 뿐이다 — 필지와 건물의 짝짓기를 "
               f"믿을 수 없다(짝 {r['pairs']}동)")
    elif r["frac"] - r["frac0"] < MIN_GAIN:
        why = (f"내포율이 {r['frac0']:.2f} → {r['frac']:.2f} 로 거의 그대로다 — "
               f"이미 맞아 있다")
    elif dist < TOL_M:
        why = f"이동량 {dist:.1f} m 는 필지 경계 표기 오차 수준이라 그대로 둔다"
    if why:
        site["parcel_bias_m"] = [0.0, 0.0]
        site["notes"].append(f"필지 레이어 편이 보정 안 함 — {why}")
        if verbose:
            print(f"  [필지편이] 보정 안 함 — {why}")
        return False

    from pyproj import Transformer
    from shapely.affinity import translate
    from shapely.geometry import shape
    from shapely.ops import transform
    fwd = _utm()
    inv = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)

    def move(g):
        return transform(inv.transform, translate(transform(fwd.transform, g), r["dx"], r["dy"]))

    from sitecheck.steps.s0_locate import _parcel_area_m2
    g = move(shape(site["parcel"]))
    site["parcel"] = g.__geo_interface__
    site["parcel_m2"] = _parcel_area_m2(g)
    for nb in site.get("neighbors") or []:
        try:
            nb["geometry"] = move(shape(nb["geometry"])).__geo_interface__
        except Exception:                                    # noqa: BLE001
            pass
    site["parcel_bias_m"] = [r["dx"], r["dy"]]
    site["notes"].append(
        f"연속지적도 필지 레이어를 ({r['dx']:+.1f},{r['dy']:+.1f}) m 옮겼다 — 자기 PNU "
        f"건물 {r['pairs']}동이 필지 안에 드는 비율 {r['frac0']:.2f} → {r['frac']:.2f}. "
        f"footprint 는 영상과 맞아 있어 건드리지 않았다")
    if verbose:
        print(f"  [필지편이] ({r['dx']:+.1f},{r['dy']:+.1f}) m · 짝 {r['pairs']}동 · "
              f"내포율 {r['frac0']:.2f} → {r['frac']:.2f}")
    return True


def _report(dirs):
    """저장된 result.json · demo.json 의 필지 내포율을 다시 잰다."""
    import json
    print(f"{'주소':30s} {'장면':8s} {'짝':>4s} {'내포율':>7s} {'맞추려면(m)':>14s} {'맞춘 뒤':>7s}")
    print("─" * 80)
    for d in dirs:
        d = Path(d)
        f = next((p for p in (d / "result.json", d / "demo.json") if p.exists()), None)
        if not f:
            continue
        site = json.loads(f.read_text("utf-8"))["site"]
        from sitecheck.steps import georef
        georef.migrate(site)          # 옛 결과(영상 프레임)도 같은 눈으로 본다
        key = (site.get("scene") or {}).get("key") or "—"
        r = estimate(site)
        if not r:
            print(f"{d.name[:28]:30s} {key:8s} {'—':>4s}   잴 수 없음")
            continue
        print(f"{d.name[:28]:30s} {key:8s} {r['pairs']:4d} {r['frac0']:7.3f} "
              f"{('(%+.0f,%+.0f)' % (r['dx'], r['dy'])):>14s} {r['frac']:7.3f}")


if __name__ == "__main__":
    from sitecheck import settings as config
    args = sys.argv[1:]
    if not args or args[0] == "--all":
        args = [str(p) for p in sorted(config.OUT.glob("*")) if (p / "result.json").exists()]
    _report(args)
