"""네 결과물의 **공통 출력 형식**.

건물·야적·이격·대장은 서로 다른 것을 재지만 소비자(리포트·웹·API)는 하나의 파일만 읽는다.
그래서 넷 다 **GeoJSON FeatureCollection** 으로 내고, 판정은 모두 같은 이름의 property
(`level`·`label`·`reason`·`basis`)에 담는다. 레이어가 늘어도 소비자 코드는 그대로다.

    result.json
    ├ request      무엇을 물었나 (주소·시각)
    ├ site         어디인가 (PNU·필지·영상·해상도) — 모든 좌표의 기준
    ├ layers       무엇이 나왔나
    │   ├ buildings   Polygon   건물 지붕 외곽선          (모델)
    │   ├ ledger      Polygon   건물별 대장 대조 결과      A3
    │   ├ separation  Polygon   두 건물 사이 간극 구역     A1
    │   └ yard        Polygon   야외 적재 구역             A4·A5
    ├ context      바탕 (필지 · 옆 지번 건물) — 판정이 아니라 그리기·참조용
    ├ summary      한 줄 요약 (판정 수준별 개수)
    └ provenance   무엇으로 냈나 (모델·영상·규칙 버전) — 재현에 필요한 최소값

레이어별 파일은 넷 + **바탕 둘**로 나간다(`context`). 바탕은 판정이 없어 `layers` 에
들어가지 않지만, 그리는 쪽이 geojson 만 받아 같은 그림을 만들려면 필요하다.

    parcel.geojson          대상 필지 · 인접 필지 — 그림의 바탕이자 대지경계선 이격의 기준선
    buildings_near.geojson  옆 지번 건물 — 이격 결과 `pair` 가 가리키는 상대

건물 id 는 `B0001`(이 지번) · `N0001`(옆 지번)이고 **북→남·서→동 순**으로 매긴다. 매기는
곳은 [[steps/s1_building.label_features]] 하나이며, 사람이 읽는 이름(`dong` = 「A동」)도
거기서 정해 값에 담는다 — 그림이 따로 계산하면 표와 그림이 갈린다.

좌표
----
전부 **EPSG:4326 (경도, 위도)** 이고, **지도 좌표**다 — 받은 geojson 을 지도에 그대로 얹으면
맞는다. 위성영상의 절대측위 편이(실측 구미 2~5 m · 대구 4~5 m · 남동공단 9 m)는 영상 쪽에서
이미 되돌렸으므로([[steps/georef.py]]) 받는 쪽이 보정을 조합할 일이 없다.

그래서 프레임을 **파일마다 적는다**(`frame: "map"`). 예전 결과는 같은 EPSG:4326 이면서 영상
프레임이었는데(그때 값을 지도에 얹으면 어긋났다) 좌표계 이름만으로는 그 둘을 구분할 수
없었다. 값을 읽는 쪽이 무엇을 받았는지 파일만 보고 알아야 한다.

되돌린 양과 근거는 `site.georef` 에 남는다 — 재현·감사용이고, 그리는 데는 필요 없다.

픽셀 좌표를 그대로 내면 영상이 바뀔 때 값이 무의미해지고 다른 레이어와 겹칠 수 없다.

판정 수준(level)
----------------
표시 문구는 `level` 이 정본이고, 같은 자리에 `level_rank`(0 이 가장 먼저 볼 것)를 같이 담는다
— 받는 쪽이 「나쁜 것부터」를 하려고 한글 7개를 다시 늘어놓지 않아도 되게.

경고 / 해당    법정선 미달 — 현장 확인 대상
주의           법정선 + 측정오차 이내 — 판정이 오차에 걸린다
참고           법정선은 충족하나 협회 권장선 아래
기록 / 이상없음 기준선 충족
정보없음        재지 못했다 (없다는 뜻이 아니다)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sitecheck import rules

# **모양이 바뀌면 올린다.** 저장된 결과를 재사용할지 말지가 이 값으로 갈리므로(`is_current`),
# 올리지 않고 모양을 바꾸면 옛 모양과 새 모양이 같은 번호를 달고 섞인다 — 실제로 그렇게
# `demo_cmp` 가 옛 id 로 만든 결과를 재사용했다.
#   1.0 → 1.1  좌표가 영상 프레임에서 지도 프레임으로 (steps/georef.py)
#   1.1 → 1.2  건물 id 규약(B/N·기하 순) · context(필지·옆 지번 건물) · level_rank
#   1.2 → 1.3  owner 가 PNU 로만 (`par:3` 색인 유출 제거) · owner_by · floors_src
#   1.3 → 1.4  이격에서 **무엇을 한 쌍으로 세나**가 바뀌었다(rules.SEP_REACH_M · 필지 밖은
#              대지경계선 구간마다 하나) — run_id·front_m·front_d_m·arc_m 이 붙고, 옛
#              결과와 줄 수가 다르다. 섞이면 같은 물건의 판정 개수가 갈린다.
SCHEMA_VERSION = "1.4"
CRS = "EPSG:4326"
FRAME = "map"               # 지도 좌표. 영상 프레임 결과는 1.0 이고 `frame` 키가 없다
LAYERS = ("buildings", "ledger", "separation", "yard")


def feature(geometry, props, fid=None):
    """GeoJSON Feature 한 건. geometry 는 __geo_interface__ 를 가진 shapely 객체도 받는다."""
    if hasattr(geometry, "__geo_interface__"):
        geometry = geometry.__geo_interface__
    f = {"type": "Feature", "geometry": geometry, "properties": dict(props)}
    if fid is not None:
        f["id"] = fid
    return f


def verdict_props(v, **extra):
    """`rules.*_verdict()` 반환값 → 공통 property 5종 + 레이어별 추가 항목.

    판정을 내는 곳과 담는 곳을 하나로 묶어 두면 레이어마다 키 이름이 갈라지지 않는다.

    `level_rank` 를 같이 담는다 — `rules.LEVELS` 안의 자리(0 이 가장 먼저 볼 것)다. 받는
    쪽이 제일 먼저 하는 일이 「나쁜 것부터 보여 주기」인데, 그걸 하려고 한글 문자열 7개를
    저쪽에서 다시 늘어놓으면 순서가 두 곳에 살게 되어 언젠가 갈라진다. 정렬 기준은 그것을
    정한 곳(`rules`)에서 나가야 한다. **표시 문구는 `level` 이 정본**이고, 순위는
    정렬·비교용이며 등급 이름이 아니다.
    """
    lv = v.get("level")
    p = {"level": lv, "level_rank": rules.LEVEL_ORDER.get(lv),
         "label": v.get("label"), "reason": v.get("reason"), "basis": v.get("basis")}
    p.update(extra)
    return p


def collection(features, layer, note=None):
    fc = {"type": "FeatureCollection", "layer": layer, "frame": FRAME,
          "count": len(features), "features": list(features)}
    if note:
        fc["note"] = note
    return fc


def layer_geojson(fc):
    """레이어 하나를 **혼자 서는 geojson** 으로. 그리는 쪽은 이 파일만 받아도 된다.

    `frame` 과 `crs` 를 같이 담는다. GeoJSON 은 모르는 최상위 키를 무시하므로(RFC 7946
    foreign members) 어떤 뷰어에서도 그대로 열리고, 값을 검사하는 쪽은 무엇을 받았는지
    알 수 있다. `count`·`note` 는 넣지 않는다 — 파일을 고쳐 쓰는 쪽에서 실제 개수와
    갈라지기 때문이다.
    """
    return {"type": "FeatureCollection", "frame": FRAME, "crs_name": CRS,
            "layer": fc.get("layer"), "features": fc.get("features") or []}


def empty(layer, note):
    """레이어를 내지 못했을 때. **키를 빼지 않는다** — 소비자가 '없음'과 '실패'를 구분해야 한다."""
    return collection([], layer, note=note)


def parcel_geojson(site):
    """`parcel.geojson` — **대상 필지 + 인접 필지.** 판정 레이어가 아니라 바탕이다.

    네 레이어에는 필지가 온전히 들어 있지 않다. 대상 필지는 `ledger` 안에 `scope:"parcel"`
    한 건으로 섞여 있고 인접 필지는 아예 없다. 그런데 그림마다 필지 외곽선이 바탕으로
    깔리고 대지경계선 이격(A1)의 기준선이 그것이다 — **그리는 쪽이 geojson 만 받아서 같은
    그림을 만들려면** 이 파일이 있어야 한다.

    `LAYERS` 에 넣지 않는다. 판정(`level`)이 없는 것을 판정 레이어에 끼우면 `summarize` ·
    `validate` 가 매번 예외를 달고 다녀야 한다. 바탕은 바탕으로 둔다.
    """
    feats = []
    if site.get("parcel"):
        shift = [round(a + b, 2) for a, b in zip(site.get("parcel_bias_m") or [0.0, 0.0],
                                                 site.get("parcel_fix_m") or [0.0, 0.0])]
        feats.append(feature(site["parcel"], {
            "role": "subject",                 # 이 지번 — 판정의 대상
            "pnu": site.get("pnu"),
            "address": site.get("address"),
            "area_m2": site.get("parcel_m2"),
            # 조회한 좌표에서 옮긴 양(m, 동·북). 0 이 아니면 고객 지적도와 그만큼 어긋난다.
            "shifted_m": shift if any(abs(v) > 1e-6 for v in shift) else None,
        }, fid=site.get("pnu")))
    for n in site.get("neighbors") or []:
        if not n.get("geometry"):
            continue
        feats.append(feature(n["geometry"], {
            "role": "neighbor",                # 옆 지번 — 이격 상대의 층수 출처
            "pnu": n.get("pnu"),
            "address": None,
            "area_m2": None,
            "shifted_m": None,
            "ledger_dongs": len(n.get("ledger") or []),
        }, fid=n.get("pnu")))
    return {"type": "FeatureCollection", "frame": FRAME, "crs_name": CRS,
            "layer": "parcel", "features": feats}


def near_geojson(near):
    """`buildings_near.geojson` — **옆 지번 건물.** 판정이 아니라 바탕이다.

    담는 이유는 **참조 무결성**이다. 이격 결과의 `pair` 는 `["B0001","N0003"]` 처럼 나오는데
    `N0003` 이 어느 파일에도 없으면 받는 쪽이 그 쌍을 그릴 수 없다. 예전에는 이 목록을
    저장하지 않아서, 보고서가 id 를 되찾으려고 **추론을 다시 돌리고** 중심점으로 걸러 내야
    했다(같은 자리에 두 번 그리는 일이 실제로 있었다).

    판정(`level`)이 없으므로 `layers` 에는 넣지 않는다 — `parcel.geojson` 과 같은 자리다.
    """
    return {"type": "FeatureCollection", "frame": FRAME, "crs_name": CRS,
            "layer": "buildings_near", "features": list(near or [])}


def context_block(site, near):
    """판정이 아닌 **바탕** — 필지와 옆 지번 건물. 파일로도 나가고 result.json 에도 담긴다.

    result.json 에 같이 담는 이유는 보고서·비교분석이 이것을 **다시 만들지 않게** 하려는
    것이다. 다시 만들면 그때의 정합·모델 상태에 따라 저장된 값과 어긋난다.
    """
    return {"parcel": parcel_geojson(site), "buildings_near": near_geojson(near)}


def frame_block(site):
    """좌표가 어느 기준인지 **한 곳에 모아** 적는다 — 받는 쪽이 물어볼 것을 미리 답한다.

    셋을 담는다.

      image_offset_m   원본 위성영상이 실제보다 밀려 있던 양(동, 북 m). 이미 되돌렸으므로
                       받는 쪽이 쓸 일은 없고, 값이 크면 그 장면의 절대측위가 나빴다는 뜻이다.
      parcel_shift_m   연속지적도 필지를 옮긴 양. **지도 쪽에서 유일하게 옮긴 것**이라
                       따로 적는다 — 고객 지적도 레이어와 이만큼 어긋나 보인다(대구 24 m).
      residual_m       마지막으로 확인한 잔차. 0 에 가까우면 정합이 맞았다는 증거다.
    """
    g = site.get("georef") or {}
    par = [round(a + b, 2) for a, b in zip(site.get("parcel_bias_m") or [0.0, 0.0],
                                           site.get("parcel_fix_m") or [0.0, 0.0])]
    return {
        "name": FRAME,
        "crs": CRS,
        "note": ("좌표는 지도 좌표다 — 그대로 지도에 얹으면 맞는다. 위성영상의 절대측위 "
                 "편이는 영상 쪽에서 되돌렸고, 필지·건축물대장·GIS건물통합정보는 조회한 "
                 "좌표 그대로다."),
        "image_offset_m": g.get("offset_m"),
        "image_georef_src": g.get("src"),
        "image_georef_applied": bool(g.get("applied")),
        "parcel_shift_m": (par if any(abs(v) > 1e-6 for v in par) else None),
        "parcel_shift_note": ("연속지적도 필지 레이어가 영상·GIS건물통합정보 둘 다에 대해 "
                              "밀려 있어 옮겼다(지적불부합). 야적 영역과 대지경계선 이격이 "
                              "이 필지 위에서 나오므로 옮긴 것을 그대로 낸다 — 고객 지적도 "
                              "레이어와는 그만큼 어긋나 보인다.")
        if any(abs(v) > 1e-6 for v in par) else None,
        "residual_m": site.get("align_residual_m"),
    }


def is_current(result):
    """저장된 결과를 **다시 써도 되는가.** 모양이 지금과 같아야 한다.

    프레임만 보면 안 된다 — 좌표계가 같아도 id 규약이나 담는 것이 달라지면 새 결과와 섞였을
    때 조용히 어긋난다(옛 id 를 가리키는 `pair`, 없는 `context`). 그래서 판 번호를 본다.
    """
    return result.get("schema_version") == SCHEMA_VERSION and is_map_frame(result)


def is_map_frame(result):
    """저장된 결과가 **지도 프레임**인가. 옛 결과(1.0)를 새 것과 섞지 않으려고 묻는다.

    옛 결과는 값과 그림이 서로 맞지만 좌표가 영상 프레임이다. 그것을 재사용하면 새 프레임
    결과와 한 화면에 섞이거나(비교분석) 새 site 로 다시 그려져(보고서) 몇 m 어긋난다.
    """
    return (result.get("frame") or {}).get("name") == FRAME


def envelope(request, site, layers, provenance, *, near=()):
    """최종 result.json. summary 는 여기서 한 번만 계산한다.

    `site.scene.bbox` 도 여기서 마지막으로 다시 쓴다 — 2차 정합까지 끝난 뒤의 보정 상태를
    담아야 출력 안의 좌표가 하나도 예외 없이 지도 좌표가 된다([[steps/georef.scene_bbox]]).
    """
    for k in LAYERS:
        layers.setdefault(k, empty(k, "생성되지 않음"))
    try:
        from sitecheck.steps import georef
        georef.refresh_scene_bbox(site)
    except Exception:                                        # noqa: BLE001
        pass
    return {
        "schema_version": SCHEMA_VERSION,
        "crs": CRS,
        "frame": frame_block(site),
        "request": request,
        "site": site,
        "context": context_block(site, near),
        "layers": {k: layers[k] for k in LAYERS},
        "summary": summarize(layers),
        "provenance": provenance,
    }


def summarize(layers):
    """레이어별 판정 수준 집계 + 가장 높은 수준. 리포트 첫 줄에 쓴다."""
    out = {}
    worst = None
    for name in LAYERS:
        fc = layers.get(name) or {}
        cnt = {}
        for f in fc.get("features", []):
            lv = (f.get("properties") or {}).get("level")
            if lv:
                cnt[lv] = cnt.get(lv, 0) + 1
                if worst is None or rules.LEVEL_ORDER.get(lv, 99) < rules.LEVEL_ORDER.get(worst, 99):
                    worst = lv
        out[name] = {"count": fc.get("count", 0), "by_level": cnt,
                     "note": fc.get("note")}
    out["worst_level"] = worst
    return out


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def write(result, out_dir):
    """result.json + 레이어별 .geojson. 레이어를 따로 내는 건 QGIS 에 바로 얹기 위해서다."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    for name in LAYERS:
        (out / f"{name}.geojson").write_text(
            json.dumps(layer_geojson(result["layers"][name]), ensure_ascii=False),
            encoding="utf-8")
    for name, fc in context_files(result).items():
        (out / name).write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    return out / "result.json"


def context_files(result):
    """{파일이름: FeatureCollection} — 바탕 파일들. 저장하는 곳이 둘이라 여기서 모은다."""
    ctx = result.get("context") or context_block(result.get("site") or {}, ())
    return {"parcel.geojson": ctx.get("parcel") or parcel_geojson(result.get("site") or {}),
            "buildings_near.geojson": ctx.get("buildings_near") or near_geojson(())}


def near_features(result):
    """옆 지번 건물 Feature 목록 — 없으면 빈 목록(옛 결과)."""
    return (((result.get("context") or {}).get("buildings_near") or {}).get("features")) or []


def known_ids(result):
    """결과가 이름을 아는 건물 id 전부 — 대상 + 옆 지번."""
    feats = (((result.get("layers") or {}).get("buildings") or {}).get("features") or []) \
        + list(near_features(result))
    return {i for i in ((f.get("properties") or {}).get("bld_id") for f in feats) if i}


def validate(result):
    """형식 점검 — 빠진 키·좌표계 불일치·판정 누락을 잡는다. 문제 목록을 돌려준다."""
    errs = []
    for k in ("schema_version", "crs", "frame", "request", "site", "context", "layers",
              "summary", "provenance"):
        if k not in result:
            errs.append(f"최상위 키 없음: {k}")
    if result.get("crs") != CRS:
        errs.append(f"좌표계가 {CRS} 가 아니다: {result.get('crs')}")
    if (result.get("frame") or {}).get("name") != FRAME:
        errs.append(f"좌표 프레임이 {FRAME} 이 아니다: {(result.get('frame') or {}).get('name')}")
    # **영상이 있는데 보정이 없으면 짚어 준다.** 좌표는 그대로 나가지만 몇 m 밀려 있고,
    # 그 사실이 notes 에만 있으면 값만 보는 쪽은 모른다.
    site = result.get("site") or {}
    if site.get("scene") and not (site.get("georef") or {}).get("applied"):
        errs.append("영상 지오레퍼런스 보정이 적용되지 않았다 — 좌표가 지도와 몇 m "
                    "어긋날 수 있다(site.georef 확인)")
    # **가리키는 id 가 결과 안에 있는지 본다.** 이격 결과의 `pair[1]` 은 옆 지번 건물일 수
    # 있는데, 예전에는 그 목록을 저장하지 않아 받는 쪽이 풀 수 없는 참조가 나갔다.
    ids = known_ids(result)
    if ids:
        for name in LAYERS:
            for i, f in enumerate((result.get("layers") or {}).get(name, {}).get("features") or []):
                p = f.get("properties") or {}
                refs = list(p.get("pair") or [])
                for k in ("bld_id", "near_bld_id"):
                    if p.get(k):
                        refs.append(p[k])
                for ref in refs:
                    if ref not in ids:
                        errs.append(f"{name}[{i}] 가 결과에 없는 건물을 가리킨다: {ref}")
    # **`owner` 는 PNU 이거나 null 이어야 한다.** 예전에는 필지 지분으로 정한 경우 메모리
    # 목록의 색인(`par:3`)이 그대로 나가서 받는 쪽이 풀 수 없었다.
    import re as _re
    _P = _re.compile(r"^\d{19}$")
    for fname, fc in (("buildings", (result.get("layers") or {}).get("buildings") or {}),
                      ("buildings_near", {"features": near_features(result)})):
        for i, f in enumerate(fc.get("features") or []):
            ow = (f.get("properties") or {}).get("owner")
            if ow is not None and not _P.match(str(ow)):
                errs.append(f"{fname}[{i}] owner 가 PNU 가 아니다: {ow}")
    for name in LAYERS:
        fc = (result.get("layers") or {}).get(name)
        if fc is None:
            errs.append(f"레이어 없음: {name}")
            continue
        for i, f in enumerate(fc.get("features", [])):
            p = f.get("properties") or {}
            if f.get("geometry") is None:
                errs.append(f"{name}[{i}] geometry 없음")
            if p.get("level") not in rules.LEVELS and name != "buildings":
                errs.append(f"{name}[{i}] level 이 규칙 밖: {p.get('level')}")
    return errs
