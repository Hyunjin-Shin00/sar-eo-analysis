"""건물 출처 ② — **GT(사람이 그린 정답).** 모델을 통과하지 않는 길.

파이프라인에서 건물 폴리곤이 나오는 곳은 둘뿐이고, 그 둘이 [[analyze.py]] 가 가르는
유일한 갈림이다.

    모델   [[steps/s1_building.py]] `predict` → `attribute`      run.py
    GT     이 파일        `polygons` → `buildings`               demo.py · hand_writting.py

왜 그런 길이 필요한가 — 판정이 **어떤 근거로 나오는지** 보여야 할 때 건물 폴리곤이 흔들리면
설명하려는 것이 가려진다. 모델 성능은 따로 재고(seglab 벤치), 여기서는 이격·야적·미등록
판정의 절차와 숫자만 보이게 한다. GT 는 학습·평가에 쓴 그 파일이고(장면 픽셀 좌표), 장면
전체에 있으므로(대구 2,651 · 구미 6,443 · 남동공단 4,748동) 주소는 영상 안이면 아무 곳이나
된다.

**id·역할·이름은 모델 경로와 같은 함수가 붙인다**([[steps/s1_building]] `label_features`) —
같은 건물이 두 길에서 같은 번호를 받아야 결과를 나란히 놓고 볼 수 있다.
"""
from __future__ import annotations

import json
from pathlib import Path

from sitecheck import schema
from sitecheck import settings as config
from sitecheck.steps import s1_building, s2_yard


def local_file(scene_key):
    """폴더 안 사본(`assets/gt/<장면>.json`) 또는 None."""
    p = config.ASSETS / "gt" / f"{scene_key}.json"
    return p if p.exists() else None


def seglab_file(scene_key):
    """seglab 원본(`regions/<지역>/gt/polygons.json`) 또는 None. **정본은 이쪽이다.**

    어느 seglab 지역에서 왔는지는 `meta.json` 의 `src_tif` 가 말해 준다 — 지역 이름을 여기
    적어 두면 장면이 늘 때마다 이 파일을 고쳐야 한다. `src_tif` 가 seglab 밖을 가리키면
    같은 이름의 tif 를 가진 지역을 찾는다.

    사본을 다시 맞추는 도구([[tools/sync_gt.py]])도 이 함수로 원본을 찾는다 — 찾는 법이
    두 곳에 있으면 사본과 원본의 짝이 도구마다 달라진다.
    """
    m = config.scene_meta(scene_key) or {}
    src = Path(m.get("src_tif") or "")
    if "regions" in src.parts:
        p = (config.SEGLAB / "regions" / src.parts[src.parts.index("regions") + 1]
             / "gt" / "polygons.json")
        if p.exists():
            return p
    name = src.name or next((t.name for t in sorted(config.SCENES[scene_key]["dir"].glob("*.tif"))),
                            "")
    for p in sorted((config.SEGLAB / "regions").glob("*/gt/polygons.json")):
        if name and (p.parent.parent / name).exists():
            return p
    return None


def gt_file(scene_key):
    """장면 → GT 파일. **폴더 안 사본을 먼저 본다**(`assets/gt/<장면>.json`).

    GT 는 네 장면 합쳐 2.3 MB 라 폴더에 담을 수 있다 — 담아 두면 데모·보고서가 seglab 없이
    돈다(남는 외부 의존은 모델 추론기 하나뿐이다). 없으면 원본을 찾는다.

    사본이 먼저인 대가는 **seglab 에서 GT 를 손으로 고치면 사본이 뒤처진다**는 것이다 —
    그때 다시 맞추는 것이 `python -m sitecheck.tools.sync_gt` 다.
    """
    return local_file(scene_key) or seglab_file(scene_key)


_CACHE = {}


def rings_px(scene_key):
    """GT 폴리곤 — 장면 픽셀 좌표 그대로. 한 파일을 여러 주소가 쓰므로 캐시한다."""
    if scene_key not in _CACHE:
        p = gt_file(scene_key)
        rings = json.loads(Path(p).read_text("utf-8")).get("polys") if p else []
        _CACHE[scene_key] = [r for r in (rings or []) if len(r) >= 4]
    return _CACHE[scene_key]


def rings_in_window(site, *, margin_m=80.0):
    """(창 안 GT 링, 창) — 둘 다 **장면 픽셀** 좌표.

    여유(margin)를 두는 이유는 이격 판정이 옆 필지 건물을 봐야 하기 때문이다 — 필지에
    딱 맞춰 자르면 경계 너머 건물이 사라져 A1 이 과소평가된다.

    창을 함께 돌려주는 이유는 확인 도구가 이 함수만 불러 같은 표본을 다시 만들 수 있게
    하기 위해서다(`python -m sitecheck.steps.gt_parallax demo_cmp/t2/*/`).
    """
    from shapely.geometry import shape
    from sitecheck.steps import georef
    sc = site["scene"]
    T, crs, _W, _H = georef.xform(site)
    par = s2_yard._lonlat_to_px(T, crs, shape(site["parcel"]))
    m = margin_m / float(sc.get("res_m") or 0.5)
    wx0, wy0, wx1, wy1 = par.bounds
    wx0 -= m; wy0 -= m; wx1 += m; wy1 += m
    keep = []
    for r in rings_px(sc["key"]):
        xs = [p[0] for p in r]
        ys = [p[1] for p in r]
        if max(xs) < wx0 or min(xs) > wx1 or max(ys) < wy0 or min(ys) > wy1:
            continue
        keep.append(r)
    return keep, (wx0, wy0, wx1, wy1)


def polygons(site, *, margin_m=80.0, verbose=False):
    """창 안의 GT → 경위도 폴리곤 목록. **모델을 부르지 않는다.**

    이식해 온 GT 면(2차 영상) 경위도로 올리기 전에 **지붕 시차만큼 옮긴다** — 픽셀 단계에서
    옮겨야 두 장면의 봉우리를 같은 자로 뺀 값을 그대로 쓸 수 있다([[steps/gt_parallax.py]]).
    """
    from shapely.geometry import Polygon
    from sitecheck.steps import gt_parallax
    keep, _win = rings_in_window(site, margin_m=margin_m)
    keep = gt_parallax.apply(site, keep, verbose=verbose)
    out = []
    for ringll in (s1_building._px_to_lonlat(site, keep) if keep else []):
        g = Polygon(ringll)
        if not g.is_valid:
            g = g.buffer(0)
        if not g.is_empty and g.geom_type == "Polygon":
            out.append(g)
    return out


def buildings(site, polys, *, hand=None):
    """GT 폴리곤 → (buildings FC, 옆 지번 건물 목록).

    `s1_building.attribute` 를 그대로 쓰지 않는 이유는 **합치기** 때문이다. 모델은 큰
    공장동을 여러 조각으로 쪼개 내므로 붙은 것을 되돌려 합쳐야 하지만, GT 는 사람이 한 동씩
    그린 것이라 합치면 대장의 동수와 어긋난다. 임자 판정(`owner_index`)은 그대로 쓴다 —
    GIS건물통합정보가 어느 건물이 어느 지번인지 직접 말해 주기 때문이다.
    """
    from shapely.geometry import shape
    from sitecheck import hand as H
    hand = hand or H.NONE
    if not polys:
        return schema.empty("buildings", "이 창 안에 GT 폴리곤이 없다"), []
    parcel = shape(site["parcel"]) if site.get("parcel") else None
    nb = []
    for n in site.get("neighbors") or []:
        try:
            g = shape(n["geometry"])
            if g.is_valid and not g.is_empty:
                nb.append(g)
        except Exception:                                    # noqa: BLE001
            pass
    owner = s1_building.owner_index(site, parcel, nb)
    mine, other = [], []
    for g in polys:
        pnu_of, how, is_subject = owner(g)
        a = max(g.area, 1e-12)
        frac = (g.intersection(parcel).area / a) if parcel is not None else 1.0
        # id·역할·이름은 [[steps/s1_building.label_features]] 가 붙인다 — 모델 경로와 같은
        # 함수를 써야 같은 건물이 두 길에서 같은 번호를 받는다.
        props = {"score": 1.0, "source": "gt", "merged_from": 1,
                 "arch_area_m2": s1_building._area_m2(g),
                 "in_parcel_frac": round(float(frac), 3),
                 "owner": pnu_of,               # **PNU 그대로** — 색인을 내보내지 않는다
                 "owner_by": how,               # footprint / parcel
                 "registered": (how == "footprint"),
                 "level": None, "label": None, "reason": None, "basis": None}
        f = schema.feature(g, props)
        # 「이 지번인가」는 `owner_index` 가 같이 돌려준다(모델 경로와 같은 규칙).
        is_mine = True if parcel is None else bool(is_subject)
        (mine if is_mine else other).append(f)
    mine, other = s1_building.label_features(mine, other, site, drop=hand.neighbor_drop,
                                             shift=hand.neighbor_shift,
                                             grow=hand.neighbor_grow)
    note = f"GT {len(polys)}동 중 이 지번 {len(mine)}동 · 옆 지번 {len(other)}동"
    # **뺀 것을 note 에도 적는다** — 안 적으면 「GT 38동 중 2 + 34」로 둘이 비어 보이는데
    # 그 둘이 어디 갔는지 종이·요약에 아무 말이 없다([[hand.py]] `neighbor_drop`).
    if site.get("neighbor_drop"):
        note += (f" · 사람이 확인해 뺀 옆 지번 "
                 f"{len(site['neighbor_drop'])}동({' · '.join(site['neighbor_drop'])})")
    # 옮긴 것도 같은 이유로 적는다 — 이격 표의 그 줄이 GT 그대로가 아니라는 사실은 값 파일
    # 안쪽(`shift_m`)만 아니라 **레이어 note 에도** 있어야 요약·종이에서 보인다.
    if site.get("neighbor_shift"):
        note += (" · 사람이 확인해 옮긴 옆 지번 "
                 + " · ".join(f"{k} ({v[0]:+.1f},{v[1]:+.1f}) m"
                              for k, v in site["neighbor_shift"].items()))
    if site.get("neighbor_grow"):
        note += (" · 사람이 확인해 늘린 옆 지번 "
                 + " · ".join(f"{k} ({v[0]:+.1f},{v[1]:+.1f}) m"
                              for k, v in site["neighbor_grow"].items()))
    return schema.collection(mine, "buildings", note=note), other
