"""단계 4 — 건축물대장 대조 (A3).

대는 것은 **건축면적** 하나다. 위성이 재는 값은 지붕의 수평투영면적이므로 대장의
건축면적과 단위가 같다(연면적은 층수가 곱해져 비교 대상이 아니다).

**대장에는 위치가 없다.** 동별 건축면적·층수는 있지만 그 동이 어느 건물인지 좌표가 없다.
그래서 어느 건물이 어느 동인지 아는 유일한 길은 GIS건물통합정보(SHP) footprint 인데,
이건 누락이 흔하다(실측 커버리지 70 %, 시험한 구미 필지는 23 %). 따라서 판정을 두 층으로
나눈다.

  · **필지 총량 판정** — Σ실측 건축면적 vs Σ대장 건축면적.
    footprint 가 없어도 성립하고, 동 대응이 틀려도 흔들리지 않는다. **이게 정본이다.**
  · **동별 판정** — footprint 로 등록 여부를 가를 수 있을 때만 낸다.
    가를 수 없으면 개별 건물에는 판정을 붙이지 않고 그렇게 적는다.

없는 정보로 동별 판정을 지어내면 「14동 미등록」 같은 답이 나온다. 실제로는 큰 공장 하나가
대장에 1동으로 등록되고 모델이 15조각으로 나눈 것뿐인데도.
"""
from __future__ import annotations

from sitecheck import settings as config
from sitecheck import rules
from sitecheck import schema


def _to_utm():
    from pyproj import Transformer
    return (Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True),
            Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True))


def load_footprint_records(site):
    """**이 지번(PNU)의** GIS건물통합정보 행. (행목록, 사유) 를 돌려준다.

    예전에는 "필지 폴리곤과 겹치는가"로 골랐다. 그러면 공단처럼 필지가 작고 빽빽한 곳에서
    옆 지번 건물이 죄다 딸려 와 GIS 합계가 대장의 몇 배가 된다(실측 대구 호산동 700-9:
    대장 634㎡ 인데 겹침 기준 5,158㎡). 등록 여부를 그 값으로 가렸으니 동별 대조가 틀렸다.
    이 자산에는 PNU 가 들어 있으므로 그걸로 고른다 — 대장과 같은 출처라 건축면적이
    대장 값과 그대로 맞는다.

    좌표는 **조회한 그대로**다 — 영상 편이는 영상 쪽에서 고치므로([[georef.py]]) 이 기하를
    옮길 이유가 없다. 예전에는 여기서 footprint 를 영상 쪽으로 끌어왔다.
    """
    if not site.get("parcel"):
        return [], "필지가 없어 footprint 를 조회할 수 없다"
    if not config.GIS_BUILDINGS.exists():
        return [], f"GIS건물통합정보 없음: {config.GIS_BUILDINGS}"
    try:
        from shapely.geometry import shape
        from sitecheck.vendor import gisdb
        par = shape(site["parcel"])
        recs = gisdb.by_pnu(site.get("pnu"), par.buffer(0.0006).bounds)
        if not recs:
            return [], "이 지번으로 등록된 footprint 가 GIS건물통합정보에 없다"
        return recs, None
    except Exception as e:                                    # noqa: BLE001
        return [], f"footprint 조회 실패 — {type(e).__name__}: {e}"


def load_footprints(site):
    """`load_footprint_records` 의 기하만. 예전 호출부(draw_maps 등)를 위해 남긴다."""
    recs, note = load_footprint_records(site)
    return [r["geometry"] for r in recs], note


def parcel_verdict(measured_sum, ledger_sum, n_model, n_ledger):
    """필지 총량 판정 — 근거문서 A3 의 세 구간을 그대로 적용한다.

        초과분 30 ㎡ 미만 또는 10 % 이하 → 증축으로 보지 않음
        30 ~ 85 ㎡                      → 증축
        85 ㎡ 이상                      → 증축 · 현장 확인 대상

    대장에 위치가 없어 동별 대응이 안 되므로 **합계로 잰다.** 건축법 제14조의
    '바닥면적의 합계'도 합계로 쓰인 값이라 단위가 맞는다.
    """
    if not ledger_sum:
        return {"level": "경고", "label": "증축 · 현장 확인 대상",
                "reason": (f"대장에 표제부가 없는데 실측 건축면적 합계 "
                           f"{measured_sum:,.0f} ㎡({n_model}동)가 잡힌다"),
                "basis": "건축법 제14조 제1항 제1호"}
    over = measured_sum - ledger_sum
    ratio = measured_sum / ledger_sum
    basis = "건축법 제14조 제1항 제1호"
    head = (f"대장 합계 {ledger_sum:,.0f} ㎡({n_ledger}동) · "
            f"실측 합계 {measured_sum:,.0f} ㎡({n_model}동) · 초과 {over:+,.0f} ㎡"
            f"({(ratio - 1) * 100:+.0f} %)")
    if over < rules.LEDGER_EXT_MIN_M2 or ratio < rules.LEDGER_EXT_RATIO:
        return {"level": "이상없음", "label": "증축으로 보지 않음",
                "reason": (f"{head} — 초과분이 {rules.LEDGER_EXT_MIN_M2:.0f} ㎡ 미만이거나 "
                           f"{(rules.LEDGER_EXT_RATIO - 1) * 100:.0f} % 이하다"),
                "basis": basis}
    if over < rules.LEDGER_PERMIT_M2:
        return {"level": "주의", "label": "증축",
                "reason": f"{head} — 건축신고로 할 수 있는 규모", "basis": basis}
    return {"level": "경고", "label": "증축 · 현장 확인 대상",
            "reason": f"{head} — 신고 한도 {rules.LEDGER_PERMIT_M2:.0f} ㎡ 이상",
            "basis": basis}


def run(buildings_fc, site):
    """필지 총량 판정(정본) + 가능하면 동별 판정.

    geometry 는 총량 판정이 **필지**, 동별 판정이 **건물 폴리곤**이다. 지도에서 필지 하나가
    한 판정을 이고, 그 안에 동별 판정이 얹힌다.
    """
    from shapely.geometry import shape
    from shapely.ops import transform, unary_union

    feats = list(buildings_fc.get("features") or [])
    ledger = list(site.get("ledger") or [])
    rows = sorted([b for b in ledger if b.get("arch_area_m2")],
                  key=lambda b: -b["arch_area_m2"])
    led_sum = sum(b["arch_area_m2"] for b in rows)

    fwd, _inv = _to_utm()
    fps, fp_note = load_footprints(site)
    fp_list = [transform(fwd.transform, g) for g in fps] if fps else None
    fp_u = unary_union(fp_list) if fp_list else None

    # **기하 신뢰도 게이트.** SHP 가 이 필지의 대장 건축면적을 설명하지 못하면 등록/미등록을
    # 가를 수 없다. 그때 기하 없음을 미등록 근거로 쓰면 등록된 건물이 통째로 미등록이 된다.
    fp_rel = (fp_u.area / led_sum) if (fp_u is not None and led_sum) else None
    reliable = bool(fp_rel is not None and fp_rel >= rules.LEDGER_FP_RELIABLE)

    out = []
    notes = []
    if fp_note:
        notes.append(fp_note)

    # ── ① 필지 총량 판정 — 정본 ──────────────────────────────────────────
    meas_sum = sum(f["properties"].get("arch_area_m2") or 0 for f in feats)
    if site.get("parcel"):
        v = parcel_verdict(meas_sum, led_sum, len(feats), len(rows))
        out.append(schema.feature(site["parcel"], schema.verdict_props(
            v, scope="parcel", pnu=site.get("pnu"),
            measured_sum_m2=round(meas_sum, 1), ledger_sum_m2=round(led_sum, 1),
            n_model=len(feats), n_ledger=len(rows),
            authoritative=True,
            detection_ratio=(round(meas_sum / led_sum, 3) if led_sum else None),
            method=("필지 총량 비교 — 대장에 위치가 없어 동별 대응은 footprint 가 있어야 "
                    "가능하다. 총량은 footprint 없이도 성립한다"),
        ), fid=f"A3:PARCEL:{site.get('pnu')}"))

    # ── ② 동별 판정 — footprint 로 등록 여부를 가를 수 있을 때만 ───────────
    if not feats:
        notes.append("건물 폴리곤이 없어 동별 대조는 하지 않았다")
    elif reliable:
        order = sorted(feats, key=lambda f: -(f["properties"].get("arch_area_m2") or 0))
        rank = -1
        for f in order:
            g = transform(fwd.transform, shape(f["geometry"]))
            # 되짚어 재는 길도 **같은 눈금**이다 — 정수 ㎡([[steps/s1_building]] `_area_m2`).
            # 한쪽만 0.1 자리를 가지면 동별 면적을 더한 값과 합계가 갈린다.
            m2 = f["properties"].get("arch_area_m2") or float(round(g.area))
            cover = 0.0
            for fp in fp_list:
                if not fp.intersects(g):
                    continue
                it = fp.intersection(g).area
                cover = max(cover, it / max(g.area, 1e-9), it / max(fp.area, 1e-9))
            registered = bool(cover >= 0.30)
            attached = None if registered else bool(
                g.distance(fp_u) <= rules.LEDGER_ATTACH_GAP_M)
            row = None
            if registered:
                rank += 1
                row = rows[rank] if rank < len(rows) else None
            v = rules.ledger_verdict(m2, row["arch_area_m2"] if row else None,
                                     attached=attached)
            out.append(schema.feature(f["geometry"], schema.verdict_props(
                v, scope="building", bld_id=f["properties"]["bld_id"],
                measured_m2=m2, ledger_m2=(row or {}).get("arch_area_m2"),
                ledger_dong=(row or {}).get("dong"),
                ledger_struct=(row or {}).get("struct"),
                ledger_roof=(row or {}).get("roof"),
                floors_above=(row or {}).get("floors_above"),
                registered=registered, cover=round(float(cover), 3), attached=attached,
                authoritative=False,
                method="등록 footprint 로 등록 여부 판정 후 면적 순위로 대장 동에 대응",
            ), fid=f"A3:{f['properties']['bld_id']}"))
    else:
        why = (f"등록 footprint 가 대장 건축면적의 {fp_rel * 100:.0f} % 만 설명한다"
               if fp_rel is not None else "이 필지에 등록 footprint 가 없다")
        notes.append(f"{why} — 동별 대응은 하지 않고 필지 총량 판정만 낸다")

    if not ledger:
        notes.append("건축물대장 표제부가 비어 있다")
    tot = sum(b.get("total_area_m2") or 0 for b in ledger)
    if tot >= rules.SPECIAL_BLD_M2:
        notes.append(f"대장 연면적 합계 {tot:,.0f} ㎡ — 특수건물(화보법 시행령 제2조 제1항) 해당 규모")

    out.sort(key=lambda x: (not x["properties"].get("authoritative"),
                            rules.LEVEL_ORDER.get(x["properties"]["level"], 99)))
    return schema.collection(out, "ledger", note=" · ".join(notes) if notes else None)


def round_areas(site):
    """대장 면적을 **정수 ㎡ 로 접는다.** 바꾼 칸 수를 돌려준다.

    보고서는 대장 면적을 처음부터 정수로 적는데(`f"{a:,.0f}"`) 값 파일에는 `1259.16` 이
    남아 있었다. 같은 물건의 두 산출물이 다른 숫자를 말하면 받는 쪽이 어느 쪽이 정본인지
    다시 물어야 한다 — 그 갈림을 없애려고 **내보내는 값 쪽을 종이에 맞춘다.**

    판정 임계값이 30·85 ㎡(`rules.LEDGER_EXT_MIN_M2` · `LEDGER_PERMIT_M2`)라 0.5 ㎡ 아래를
    접어도 판정은 바뀌지 않는다.

    **실측 면적도 같은 눈금이다**(2026-08-23 정정). 예전에는 「접는 것은 대장 면적만 — 실측은
    0.1 ㎡ 자리가 뜻을 가진다」고 적어 두었는데, 그러면 **한 번 접고 더한 값과 더하고 접은
    값이 갈린다**(실측 신당동 1187-2: 동별 판독 862 + 604 = 1,466 인데 합계는 round(861.6 +
    603.9) = 1,465 로 찍혔다 — 종이를 더해 본 사람이 표가 틀렸다고 읽는다). 그래서 실측 쪽도
    정수로 낸다([[steps/s1_building]] `_area_m2`). 잃는 것은 없다 — 이 값의 오차는 0.5 ㎡ 가
    아니라 모델 면적오차 2 % 이고, 판정 임계값은 30 ㎡ · 10 % 다.
    """
    import math
    n = 0
    for b in site.get("ledger") or []:
        for k in ("arch_area_m2", "total_area_m2"):
            v = b.get(k)
            if v is None:
                continue
            r = float(round(float(v)))
            # **접는 것이 분류를 바꾸면 안 된다.** 보고서는 30 ㎡ 미만을 부속으로 보아 표에서
            # 빼는데(`rules.LEDGER_MIN_BLD_M2` · `report/single._ledger_view`), 29.89 ㎡ 인 동을
            # 올려 접으면 30.0 이 되어 본동으로 올라선다 — 그러면 종이는 「30 ㎡ 미만 부속
            # 제외」라 적는데 표에는 30 ㎡ 인 동이 서서 두 말이 된다(실측 고잔동 672-6 「다」동:
            # keep 2동 3,730 ㎡ → 3동 3,760 ㎡). 그 하나만 내려 접는다.
            if float(v) < rules.LEDGER_MIN_BLD_M2 <= r:
                r = float(math.floor(float(v)))
            if r != float(v):
                b[k] = r
                n += 1
    return n
