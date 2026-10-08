"""단계 1 — 건물 지붕 폴리곤 (모델).

**나머지 셋이 전부 이 결과 위에 선다.** 야적은 「필지 − 건물」에서 찾고, 이격은 건물 간
거리이며, 대장 대조는 건물별 면적 비교다. 그래서 여기가 틀리면 뒤가 전부 틀린다.

**단일 모델이다**(`settings.BUILDING_MODELS` — 왜 앙상블을 접었는지 그 측정표가 거기 있다).
멤버가 둘 이상이면 `vendor.ensemble.fuse` 로 합의 재점수하고, 하나면 **합치지 않는다** —
백분위 정규화가 점수의 뜻을 바꿔 버려 운용 임계값을 설명할 수 없게 된다.

추론은 **이 폴더 안에서** 돈다 — 모델 코드는 `vendor/dinov3seg/`(DINOv3 동결 + Mask2Former ·
원본 `building_seg/dinov3_v2` 의 run4), 창 자르기·8대칭 TTA·경계 인스턴스 제거·전역 중복제거·
청소·폴리곤화는 `vendor/dinov3seg_run.py` 다. 실행 환경(torch 2.13 · transformers 5.15 가 든
venv)는 `requirements.txt` 하나로 만들어진다 — 2026-08-27 에 파이프라인 환경과 하나로 합쳤다
(막고 있던 mmcv 를 SAMPolyBuild 와 함께 걷어 냈다). 인터프리터를 따로 줄 자리는 남아 있다
(`settings.DINOV3_PYTHON`).

바꿔 끼우기
-----------
**모델이 갈리는 자리는 `_run_model` 하나다.** `settings.BUILDING_MODELS` 의 멤버에 `kind` 를
적으면 그것으로 갈리고, 어느 쪽이든 돌려주는 것은 같은 파일이다 —
`out/<tag>_poly.json` 의 `polys`(장면 픽셀 좌표) · `scores`. 그래서 이 아래(임계값 · 경위도
변환 · 합치기 · 귀속 · id · 그림 · 보고서)는 모델이 무엇인지 알 필요가 없고, 2026-08-26 에
SAMPolyBuild → DINOv3+Mask2Former 로 갈 때도 한 줄도 바뀌지 않았다.

가중치가 없는 멤버는 `available_models()` 가 걸러 내고, 몇으로 합쳤는지는 결과 note 에
적힌다. 새 종류를 더할 때 필요한 것은 셋이다: 벤더한 코드 · `run()` 이 있는 절차 파일(계약은
위와 같다) · `settings` 의 설정 dict 하나.
"""
from __future__ import annotations

import json

from sitecheck import settings as config
from sitecheck import schema


def _px_to_lonlat(site, rings_px):
    """영상 픽셀 폴리곤 → **지도 좌표**. 보정된 지오트랜스폼을 쓴다([[georef.py]]).

    두 가지를 같이 고친다.

      · `loader.ll2px` 의 역변환을 쓰면 안 된다 — meta.bbox 는 UTM 사각형의 경위도 외접
        사각형이라 자오선 수렴만큼 넓고, 선형으로 되돌리면 장면 안에서 위치의존 오차가
        난다(실측 대구 27 m · 구미 42 m · 남동공단 109 m).
      · 원본 지오트랜스폼 그대로 되돌리면 **영상 자신의 절대측위 편이**가 좌표에 남는다
        (실측 구미 2~5 m · 대구 4~5 m · 남동공단 9 m). 그래서 보정된 것을 쓴다 — 그러면
        여기서 나오는 좌표를 지도에 그대로 얹을 수 있다.
    """
    from sitecheck.steps import georef
    return georef.px_rings_to_ll(site, rings_px)


def region_px(site, scene_dir, margin_m=80.0):
    """필지 bbox + 여유 → 영상 픽셀창 "x0,y0,x1,y1". 필지가 없으면 None(전장면).

    주소 하나를 보려고 전장면(구미 11900x12612 = 1.5억 픽셀)을 도는 것은 낭비다.
    여유(margin)를 두는 이유는 **이격 판정이 옆 필지 건물을 봐야 하기 때문**이다 —
    필지에 딱 맞춰 자르면 경계 너머 건물이 사라져 A1 이 과소평가된다.
    """
    if not site.get("parcel"):
        return None
    from pyproj import Transformer
    from shapely.geometry import shape
    from sitecheck.steps import georef
    try:
        T, crs, W, H = georef.xform(site)
    except Exception:                                        # noqa: BLE001
        return None
    tr = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    x0, y0, x1, y1 = shape(site["parcel"]).bounds
    xs, ys = tr.transform([x0, x1, x0, x1], [y0, y0, y1, y1])
    ex0, ex1 = min(xs) - margin_m, max(xs) + margin_m
    ny0, ny1 = min(ys) - margin_m, max(ys) + margin_m
    inv = ~T
    corners = [inv * (ex0, ny0), inv * (ex1, ny0), inv * (ex0, ny1), inv * (ex1, ny1)]
    px = [c[0] for c in corners]
    py = [c[1] for c in corners]
    a = max(0, int(min(px))); b = max(0, int(min(py)))
    c = min(W, int(max(px)) + 1); d = min(H, int(max(py)) + 1)
    if c - a < 64 or d - b < 64:          # 너무 작으면 타일 하나도 안 나온다
        return None
    return f"{a},{b},{c},{d}"


def _run_model(member, scene_key, tag, gpu=None, region=None, infer_fix=None):
    """멤버 하나를 돌린다 → out/<tag>_poly.json 경로.

    **이 폴더 안에서 돈다** — 모델 코드도 감싸는 절차도 `vendor/` 에 있다(예전에는 seglab 의
    래퍼를 서브프로세스로 불렀다).

    **모델을 갈아 끼우는 자리는 여기 하나다.** `kind` 로 갈리고, 어느 쪽이든 돌려주는 것은
    같은 파일이다 — `out/<tag>_poly.json` 의 `polys`(장면 픽셀 좌표) · `scores`. 그래서 이
    함수 아래로는(임계값 · 경위도 · 합치기 · 귀속 · id) 모델이 무엇인지 알 필요가 없다.

        dinov3   DINOv3(동결)+Mask2Former  `vendor/dinov3seg_run.py`   torch 2.13 환경

    **지금은 한 종류뿐이다** — SAMPolyBuild(`kind="sampoly"`)는 2026-08-27 에 걷어 냈다.
    새 종류를 더할 때 필요한 것은 셋이다: 벤더한 코드 · `run()` 이 있는 절차 파일(계약은 위와
    같다) · `settings` 의 설정 dict 하나. 설정값을 **모델마다 따로 두는** 이유는 한 dict 를
    나눠 쓰면 이름이 같고 뜻이 다른 값이 생기기 때문이다(`tta` 가 회전 수인지 8대칭인지,
    `score_thr` 이 포화된 신뢰도인지 예측 IoU 인지).
    """
    scene_dir = config.SCENES[scene_key]["dir"].resolve()
    kind = member.get("kind")
    if kind != "dinov3":
        # 조용히 다른 모델로 돌리지 않는다 — 산출물 형식이 같아 알아채기 어렵다.
        raise ValueError(f"모르는 모델 종류 {kind!r} — 지금 있는 것은 'dinov3' 하나다")
    from sitecheck.vendor import dinov3seg_run
    kw, _thr = config.infer_for(scene_key)        # 영상별 덮어쓰기를 얹는다
    kw.update({k: v for k, v in ((infer_fix or {}).get(scene_key) or {}).items()
               if k != "score_threshold"})        # 그 위에 **이 물건**의 손보정
    kw["tta"] = bool(member.get("tta"))           # 멤버의 8 은 몇 방향인지의 메모다
    return dinov3seg_run.run(
        scene_dir, tag, member["ckpt"], python=config.DINOV3_PYTHON,
        region=region, gpu=gpu, verbose=False, **kw)


def _predict(site, scene_key, tag, *, gpu=None, reuse=True, infer_fix=None):
    """멤버를 모두 돌려 합의 재점수한다 → (rings_px, scores, 몇으로 합쳤는지).

    한 멤버가 죽어도 **전체를 버리지 않는다** — 살아남은 멤버로 합치고 몇이었는지 적는다.
    앙상블 점수는 (구성원 점수 합 / 멤버수)라 멤버 수가 곧 점수 스케일이므로, 몇으로
    합쳤는지 모르면 임계값 0.28 이 무슨 뜻인지도 알 수 없다.
    """
    from sitecheck.vendor.ensemble import fuse
    scene_dir = config.SCENES[scene_key]["dir"].resolve()
    members = config.available_models()
    if not members:
        raise FileNotFoundError("건물 모델 가중치를 하나도 찾지 못했다")
    region = region_px(site, scene_dir)
    per, failed = {}, []
    for m in members:
        mt = f"{tag}__{m['tag']}"
        pj = scene_dir / "out" / f"{mt}_poly.json"
        try:
            if not (reuse and pj.exists()):
                pj = _run_model(m, scene_key, mt, gpu=gpu, region=region, infer_fix=infer_fix)
            d = json.load(open(pj, encoding="utf-8"))
            rings = d.get("polys") or []
            per[m["tag"]] = (rings, d.get("scores") or [1.0] * len(rings))
        except Exception as e:                                   # noqa: BLE001
            failed.append(f"{m['tag']}({type(e).__name__})")
    if not per:
        raise RuntimeError(f"추론 실패 — {' · '.join(failed)}")
    geom = next((m["tag"] for m in members if m.get("geom") and m["tag"] in per), None)
    used = " + ".join(f"{t}({len(v[0])})" for t, v in per.items())
    if len(per) == 1:
        # **합치지 않는다.** `fuse` 는 점수를 백분위로 정규화하는데(멤버 간 스케일을 맞추려고)
        # 멤버가 하나면 그것이 점수의 뜻만 지운다 — 운용 임계값(0.85)은 모델 원본 스케일이다.
        _tag_one, (rings, scores) = next(iter(per.items()))
        note = f"단일 모델 [{used}]"
    else:
        rings, scores = fuse(per, config.ENSEMBLE["iou"], config.ENSEMBLE["mode"], geom)
        note = f"{len(per)}-멤버 앙상블 [{used}] · 기하 {geom or '없음'}"
    if failed:
        note += f" · 실패 {' · '.join(failed)}"
    return rings, scores, note


# ── 건물 식별자 ──────────────────────────────────────────────────────────────
# **이름을 정하는 곳은 여기 하나다.** 예전에는 모델 경로(`attribute`)와 GT 경로
# (`gt.buildings`)가 각자 `B0000` 을 붙였고, 옆 지번 건물은 **결과에 담기지도
# 않았다.** 그래서 이격 결과의 `pair[1]` 이 어디에도 없는 id 를 가리켰고, 보고서는 그 id 를
# 되찾으려고 추론을 다시 돌린 뒤 중심점으로 걸러 내야 했다(`report/single._neighbors`).
ID_ORDER = "북→남, 같은 줄이면 서→동"


def id_sort_key(poly):
    """식별자를 매기는 순서 — **기하로만** 정한다.

    폴리곤이 나온 순서로 매기면 모델 출력이 조금 달라질 때 번호가 전부 밀린다(같은 물건을
    두 번 돌려도 다른 id 가 된다). 위에서 아래로, 같은 줄이면 왼쪽부터 — 사람이 도면을 읽는
    순서와 같고, 무엇보다 **같은 입력이면 늘 같은 번호**가 나온다.
    """
    c = poly.centroid
    return (-round(c.y, 7), round(c.x, 7))


_ABC = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _dong_name(i):
    if i < len(_ABC):
        return f"{_ABC[i]}동"
    return f"{_ABC[i // len(_ABC) - 1]}{_ABC[i % len(_ABC)]}동"     # 27동째부터 AA동


def label_features(mine, near, site, *, drop=(), shift=(), grow=()):
    """대상·옆 지번 Feature 에 **id·역할·이름**을 붙인다. 두 경로가 같이 쓴다.

    `drop`·`shift` 는 **사람이 확인한 손보정**이다([[hand.py]]) — 값은 저장소 뿌리의
    `hand_writting.py` 에만 있고, `run.py`·`demo.py` 는 빈 값으로 부른다. **id 를 붙인
    뒤에** 걸리므로 남는 건물의 번호가 밀리지 않는다.

        bld_id   대상 `B0001…` · 옆 지번 `N0001…` — 접두어만 보고 무엇을 가리키는지 안다
        role     "subject" / "neighbor"
        dong     대상 건물의 사람 이름(`A동`) — **건축면적 큰 순**(화면설계서 BR-13 목업)
        az_deg   옆 지번 건물이 필지 중심에서 어느 방향인가(북 0° 시계방향)
        dist_m   옆 지번 건물에서 가장 가까운 대상 건물까지 거리(m)

    뒤 둘을 담는 이유는 그림의 ①②③ 이다. 그 번호는 **북쪽부터 시계방향**으로 붙는데, 어느
    건물에 붙일지는 그림마다 다르다(창 밖이면 배지를 놓을 자리가 없고, 이격 표에 없는 건물은
    번호를 받지 않는다). 그러니 번호 자체를 값에 박으면 그림과 어긋난다 — 대신 **순서의
    근거**를 담아, 무엇을 보여 주든 같은 순서가 나오게 한다.
    """
    from shapely.geometry import shape
    from shapely.ops import transform, unary_union
    from pyproj import Transformer
    fwd = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)

    def order(feats):
        return sorted(feats, key=lambda f: id_sort_key(shape(f["geometry"])))

    mine, near = order(mine), order(near)
    for pre, feats in (("B", mine), ("N", near)):
        for i, f in enumerate(feats, 1):
            f["properties"]["bld_id"] = f"{pre}{i:04d}"
            f["properties"]["role"] = "subject" if pre == "B" else "neighbor"
            f["id"] = f["properties"]["bld_id"]

    # 대상 건물의 사람 이름 — 면적 큰 순. 면적이 같으면 id 로 갈라 늘 같은 이름이 나온다.
    for i, f in enumerate(sorted(mine, key=lambda f: (-(f["properties"].get("arch_area_m2") or 0),
                                                      f["properties"]["bld_id"]))):
        f["properties"]["dong"] = _dong_name(i)

    # **폴리곤을 옮기는 것은 여기까지다.** id 를 붙인 뒤라 번호가 밀리지 않고, 방향·거리를
    # 재기 전이라 아래 값들이 옮긴 자리에서 나온다 — 옮겨 놓고 옛 거리를 적으면 그림과 표가
    # 갈린다.
    shift_neighbors(site, near, shift)
    grow_neighbors(site, near, grow)

    # 옆 지번 건물의 방향·거리 — ①②③ 순서의 근거
    hub = None
    if site.get("parcel"):
        hub = shape(site["parcel"]).centroid
    elif mine:
        hub = unary_union([shape(f["geometry"]) for f in mine]).centroid
    own_m = [transform(fwd.transform, shape(f["geometry"])) for f in mine]
    import math
    for f in near:
        g = shape(f["geometry"])
        c = g.centroid
        f["properties"]["az_deg"] = (round(math.degrees(math.atan2(c.x - hub.x,
                                                                  c.y - hub.y)) % 360.0, 1)
                                     if hub is not None else None)
        gm = transform(fwd.transform, g)
        f["properties"]["dist_m"] = (round(min(gm.distance(o) for o in own_m), 2)
                                     if own_m else None)
        f["properties"]["dong"] = None      # 옆 지번은 동 이름을 받지 않는다(우리 대장이 아니다)
    return mine, drop_neighbors(site, near, drop)


def shift_neighbors(site, near, want=()):
    """사람이 확인한 만큼 옆 지번 건물 폴리곤을 옮긴다([[hand.py]] `neighbor_shift`).

    **왜 옮기나.** GT 는 사람이 그린 지붕선이라 그늘·차양까지 물려 그린 자리가 있고, 그
    폴리곤으로 이격을 재면 바닥을 지붕으로 세어 두 건물이 붙은 것처럼 나온다. 원본 픽셀의
    밝기로 지붕이 시작하는 자리를 짚을 수 있는 경우에만, 그 만큼 옮겨 적어 둔다 — 근거와
    측정값은 값 옆에 적혀 있다([[hand_writting.py]]).

    **지번(PNU)이 함께 맞을 때만 옮긴다** — `drop_neighbors` 와 같은 규약이다. `N####` 는
    창 안 GT 순서로 매기는 번호라 GT 나 창이 바뀌면 같은 번호가 다른 건물을 가리킬 수 있고,
    그때 조용히 엉뚱한 건물을 옮기면 어느 값이 사람 손을 탔는지 알 수 없게 된다.

    면적은 평행이동이라 그대로다. **필지 지분(`in_parcel_frac`)만 다시 잰다** — 그 값은 옮긴
    자리에서 다시 나와야 맞고, 임자(`owner`)는 다시 계산하지 않는다(사람이 「같은 건물을
    제자리로 옮긴다」고 정한 것이므로 임자가 바뀌면 그것은 옮기기가 아니라 다른 건물이다).
    """
    if not want:
        return near
    from shapely.affinity import translate
    from shapely.geometry import shape
    from shapely.ops import transform
    from pyproj import Transformer
    fwd = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    inv = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
    parcel = shape(site["parcel"]) if site.get("parcel") else None
    by_id = {(f.get("properties") or {}).get("bld_id"): f for f in near}
    moved = {}
    for bid, pnu, (dx, dy) in want:
        f = by_id.get(bid)
        if f is None:
            continue
        p = f["properties"] or {}
        if p.get("owner") != pnu:
            print(f"  [!] 옆 지번 건물 이동 {bid} 을 건너뛴다 — 그 id 의 지번이 "
                  f"{p.get('owner')} (적어 둔 값 {pnu})", flush=True)
            continue
        g = transform(inv.transform,
                      translate(transform(fwd.transform, shape(f["geometry"])),
                                float(dx), float(dy)))
        f["geometry"] = g.__geo_interface__
        p["shift_m"] = [float(dx), float(dy)]
        if parcel is not None:
            a = max(g.area, 1e-12)
            p["in_parcel_frac"] = round(float(g.intersection(parcel).area / a), 3)
        moved[bid] = (float(dx), float(dy))
    if not moved:
        return near
    site["neighbor_shift"] = {k: list(v) for k, v in moved.items()}
    site.setdefault("notes", []).append(
        "옆 지번 건물 " + " · ".join(f"{k} ({v[0]:+.1f},{v[1]:+.1f}) m" for k, v in moved.items())
        + " 를 사람이 확인해 옮겼다 — GT 지붕선이 그늘까지 물려 그려져 이격이 실제보다 "
        "가깝게 나오던 것을 원본 픽셀의 밝기로 지붕 자리를 짚어 맞춘 값이다. 이격·그림·표는 "
        "옮긴 폴리곤으로 다시 잰다")
    return near


def grow_neighbors(site, near, want=()):
    """옆 지번 건물 폴리곤을 **한쪽으로 늘린다**([[hand.py]] `neighbor_grow`).

    **`neighbor_shift` 와 다른 것이다.** 옮기기는 지붕선이 통째로 어긋났을 때 제자리로
    되돌리는 것이고, 늘리기는 **지붕의 일부만 잡혔을 때** 못 잡은 쪽을 채우는 것이다. 모델도
    GT 도 그늘에 든 지붕을 자주 놓치는데(실측 호림동 3-10 N0029: 밝은 붉은 지붕만 잡히고
    그 북쪽 14 m 짜리 그늘진 지붕이 통째로 빠졌다), 그때 옮기면 잡힌 쪽이 제자리를 떠나므로
    **잡힌 자리는 그대로 두고 못 잡은 쪽만 더한다.**

    늘리는 방법은 **폴리곤을 그만큼 옮긴 사본과 합치는 것**이다. 직사각에 가까운 지붕에서는
    그 방향으로 그만큼 늘어난 것과 같고, 원래 모양의 꼭짓점을 그대로 두므로 기울어진 지붕도
    기울기가 유지된다. 넓이는 늘어난 만큼 커지고 **`arch_area_m2` 도 다시 잰다** — 값이
    도형과 갈리면 대장 대조가 잡히지 않은 지붕을 세게 된다.

    **지번(PNU)이 함께 맞을 때만 늘린다** — `drop_neighbors`·`shift_neighbors` 와 같은
    규약이다. 늘린 사실은 `grow_m` · `site.notes` 에 남는다.
    """
    if not want:
        return near
    from shapely.affinity import translate
    from shapely.geometry import shape
    from shapely.ops import transform, unary_union
    from pyproj import Transformer
    fwd = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    inv = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
    parcel = shape(site["parcel"]) if site.get("parcel") else None
    by_id = {(f.get("properties") or {}).get("bld_id"): f for f in near}
    done = {}
    for bid, pnu, (dx, dy) in want:
        f = by_id.get(bid)
        if f is None:
            continue
        p = f["properties"] or {}
        if p.get("owner") != pnu:
            print(f"  [!] 옆 지번 건물 늘리기 {bid} 을 건너뛴다 — 그 id 의 지번이 "
                  f"{p.get('owner')} (적어 둔 값 {pnu})", flush=True)
            continue
        m = transform(fwd.transform, shape(f["geometry"]))
        u = unary_union([m, translate(m, float(dx), float(dy))])
        if u.geom_type != "Polygon":                  # 갈라졌으면 늘린 것이 아니다
            print(f"  [!] 옆 지번 건물 늘리기 {bid} 을 건너뛴다 — 도형이 갈라진다", flush=True)
            continue
        g = transform(inv.transform, u)
        f["geometry"] = g.__geo_interface__
        p["grow_m"] = [float(dx), float(dy)]
        p["arch_area_m2"] = round(float(u.area), 1)
        if parcel is not None:
            p["in_parcel_frac"] = round(float(g.intersection(parcel).area / max(g.area, 1e-12)), 3)
        done[bid] = (float(dx), float(dy))
    if not done:
        return near
    site["neighbor_grow"] = {k: list(v) for k, v in done.items()}
    site.setdefault("notes", []).append(
        "옆 지번 건물 " + " · ".join(f"{k} ({v[0]:+.1f},{v[1]:+.1f}) m"
                                   for k, v in done.items())
        + " 를 사람이 확인해 그 방향으로 늘렸다 — 그늘에 든 지붕이 판독에서 빠져 건물이 "
        "실제보다 작게 잡히던 것을 원본 픽셀에서 지붕 끝을 짚어 채운 값이다. 이격·면적·"
        "그림·표는 늘린 폴리곤으로 다시 낸다")
    return near


def drop_neighbors(site, near, want=()):
    """사람이 확인해 뺀 옆 지번 건물을 목록에서 뺀다([[hand.py]] `neighbor_drop`).

    **id 를 붙인 뒤에 뺀다.** 먼저 빼고 번호를 매기면 남는 건물의 `N####` 가 밀려, 설정에
    적어 둔 id 가 다음 실행에서 다른 건물을 가리킨다. 그래서 번호에 비는 자리가 생기는데,
    그 편이 조용히 어긋나는 것보다 낫다 — 빈 자리의 뜻은 `site.notes` 가 적는다.

    **지번(PNU)이 함께 맞을 때만 뺀다.** `N####` 는 창 안 GT 순서로 매겨지는 번호라 GT 나
    창이 바뀌면 같은 번호가 다른 건물을 가리킬 수 있다 — 그때는 빼지 않고 그 사실을 찍는다.

    뺀 것은 이격 상대에서도, `context.buildings_near` 에서도, 그림에서도 사라진다. 「이격에서만
    빼고 회색 점선은 남기기」를 먼저 해 봤는데, 지도에 번호 없는 선이 남아 「이건 뭔데 아무 말도
    없나」가 되었다(2026-08-23). 뺐다고 정한 것은 선까지 지우는 것이 맞다.
    """
    if not want:
        return near
    by_id = {(f.get("properties") or {}).get("bld_id"): f for f in near}
    gone = []
    for bid, pnu in want:
        f = by_id.get(bid)
        if f is None:
            continue
        if (f["properties"] or {}).get("owner") != pnu:
            print(f"  [!] 옆 지번 건물 제외 {bid} 을 건너뛴다 — 그 id 의 지번이 "
                  f"{(f['properties'] or {}).get('owner')} (적어 둔 값 {pnu})", flush=True)
            continue
        gone.append(bid)
    if not gone:
        return near
    site["neighbor_drop"] = gone
    site.setdefault("notes", []).append(
        f"옆 지번 건물 {len(gone)}동({' · '.join(gone)})을 사람이 확인해 뺐다 — 위성에는 "
        f"지붕처럼 보이나 연소확대의 상대가 아니라고 본 것이다. 이격·그림·"
        f"buildings_near 에서 다 빠지고 남는 건물의 번호는 그대로다(그 자리가 빈다)")
    return [f for f in near if (f["properties"] or {}).get("bld_id") not in set(gone)]


MERGE_GAP_M = 0.3   # 이보다 가까운 폴리곤은 붙은 것으로 본다 — 모델 경계오차(0.78 m)
                    #   보다 작은 간극은 '붙음'과 구분되지 않는다
OWN_MIN_FRAC = 0.25  # 이 필지 지분이 이보다 작으면 아무리 최대여도 우리 것으로 세지 않는다
FP_MIN_FRAC = 0.25   # GIS footprint 와 이만큼은 겹쳐야 그 지번 건물로 인정한다


def owner_index(site, parcel, nb_polys):
    """모델 폴리곤 → 임자 열쇠. **GIS건물통합정보를 먼저 믿는다.**

    이 자산은 건축물대장을 도형에 붙여 만든 것이라 **어느 건물이 어느 지번인지 직접**
    말해 준다. 필지 폴리곤과 얼마나 겹치는지로 추측할 이유가 없다 — 추측은 건물이 지번
    경계를 걸칠 때 바로 틀린다.

    **여기 있던 '갱신 주기가 달라서'라는 설명은 틀렸다.** 대구 파호동 93-17 에서 자기 지번
    footprint 가 자기 필지에 42 % 만 들던 것은 **연속지적도 필지 레이어가 영상 대비 26 m
    남쪽에 있었기 때문**이고, 그것을 고치면 99 % 가 된다([[parcel_bias.py]]). 그래도 GIS 를
    먼저 믿는 이 순서는 그대로 맞다 — 필지 편이를 못 재는 주소에서도 귀속이 흔들리지 않는다.

    footprint 가 없는 건물 — 즉 **미등록 건물** — 은 이 자산에 안 나온다. 그래서 그때만
    필지 지분으로 물러난다. A3 가 잡으려는 것이 바로 그 건물들이므로, 없다고 버리면 안 된다.

    돌려주는 것은 **`(PNU, 어떻게 정했나, 이 지번인가)`** 세 값이다. PNU 를 못 정하면 첫
    값이 None 이다.

    **PNU 로만 돌려준다.** 예전에는 필지 지분으로 정한 경우를 `("par", 3)` 으로 돌려주고 그
    3 을 결과의 `owner` 에 그대로 적었는데, 그것은 `[이 필지] + 인접필지` **메모리 목록의
    색인**이라 받는 쪽이 풀 수 없다(실측: 데모의 이웃 581동 중 127동, 대상 60동 중 40동이 그
    형태였다). 색인은 인접필지 순서가 바뀌면 뜻도 바뀌므로 저장해서도 안 된다.
    """
    fps = []                                    # [(PNU, 기하)]
    try:
        from sitecheck.vendor import gisdb
        if parcel is not None:
            # **조회한 좌표 그대로 쓴다** — 영상 편이는 영상 쪽에서 고쳤다([[georef.py]]).
            for r in gisdb.near(parcel.buffer(0.0012).bounds):
                if r.get("pnu"):
                    fps.append((str(r["pnu"]), r["geometry"]))
    except Exception:                                        # noqa: BLE001
        fps = []
    # 필지 목록 — **첫 자리가 이 필지다**(그 자리로 「이 지번인가」를 가른다). PNU 는 같이
    # 들고 다녀 결과에는 색인이 아니라 PNU 가 나가게 한다.
    mine_pnu = str(site.get("pnu")) if site.get("pnu") else None
    pars = ([(mine_pnu, parcel)] if parcel is not None else [])
    nb_pnu = [str(n.get("pnu")) if n.get("pnu") else None
              for n in (site.get("neighbors") or [])]
    for i, g in enumerate(nb_polys):
        pars.append((nb_pnu[i] if i < len(nb_pnu) else None, g))

    def owner(poly):
        a = max(poly.area, 1e-12)
        best, pnu = 0.0, None
        for k, g in fps:
            try:
                v = poly.intersection(g).area
            except Exception:                                # noqa: BLE001
                v = 0.0
            if v > best:
                best, pnu = v, k
        if pnu is not None and best / a >= FP_MIN_FRAC:
            return pnu, "footprint", (mine_pnu is not None and pnu == mine_pnu)
        best, hit = 0.0, None
        for i, (pn, g) in enumerate(pars):
            try:
                v = poly.intersection(g).area
            except Exception:                                # noqa: BLE001
                v = 0.0
            if v > best:
                best, hit = v, (i, pn)
        if hit is None or best / a < OWN_MIN_FRAC:
            return None, None, False
        return hit[1], "parcel", hit[0] == 0        # 첫 자리 = 이 필지

    return owner


def merge_touching(polys, owner=None):
    """서로 닿아 있는(간극 ≤ MERGE_GAP_M) 폴리곤을 한 동으로 합친다.

    모델은 큰 공장동을 여러 조각으로 쪼개 낼 때가 있다. 그대로 두면 (1) 이격(A1)에서
    같은 건물끼리 0.0 m 쌍이 쏟아지고(실측 227쌍 중 19쌍), (2) 대장 대조(A3)에서 한 동이
    여러 건으로 세어진다. 둘 다 실제 위험과 무관한 숫자다.

    **다만 지번을 넘어서 합치면 안 된다.** 공단은 벽을 맞댄 건물이 줄지어 서 있어서,
    간극만 보고 합치면 접촉이 사슬처럼 이어져 블록 하나가 폴리곤 한 개가 된다(실측
    고잔동 716-8: 661㎡ 건물이 옆 블록 덩어리에 먹혀 필지 실측이 893㎡ → 301㎡ 로
    무너졌고, 660-8 은 3,492㎡ 짜리 대각선 덩어리가 나왔다). 합치는 목적은 **한 동이
    쪼개진 것을 되돌리는 것**이지 남의 건물까지 끌어오는 것이 아니다.

    그래서 `owner` 가 주어지면 **임자가 같은 것끼리만** 합친다. 한 동은 한 지번에 속하므로,
    임자가 다르면 애초에 같은 동일 수 없다.
    """
    from pyproj import Transformer
    from shapely.ops import transform, unary_union
    fwd = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    inv = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
    g = [transform(fwd.transform, p) for p in polys]
    n = len(g)
    parent = list(range(n))

    own = [None] * n
    if owner is not None:
        for i, q in enumerate(polys):
            try:
                own[i] = owner(q)
            except Exception:                                # noqa: BLE001
                own[i] = None

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    from shapely.strtree import STRtree
    tree = STRtree(g)
    for i, gi in enumerate(g):
        for j in tree.query(gi.buffer(MERGE_GAP_M)):
            j = int(j)
            if j <= i:
                continue
            if own[i] != own[j]:              # 임자가 다르면 같은 동이 아니다
                continue
            if gi.distance(g[j]) <= MERGE_GAP_M:
                ra, rb = find(i), find(j)
                if ra != rb:
                    parent[ra] = rb
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    out = []
    for idxs in groups.values():
        u = unary_union([g[i] for i in idxs])
        if u.geom_type == "MultiPolygon":                # 닿았다고 봤으나 실제로는 분리
            u = max(u.geoms, key=lambda x: x.area)
        out.append((transform(inv.transform, u), sorted(idxs)))
    return out


def predict(site, *, tag="sitecheck", gpu=None, reuse=True, infer_fix=None):
    """site → [(폴리곤, 점수)] · 앙상블 메모. 좌표는 **지도 좌표**다(1차 보정 반영).

    귀속과 분리한 이유는 **정합** 때문이다. 2차 정합([[align.refine]])이 영상 보정을 조금
    더 손질하면 이 폴리곤의 좌표도 같이 움직인다. 그래서 순서가 `predict → 정합 → 귀속`
    이다 — 귀속을 먼저 하면 아직 덜 맞은 좌표로 임자를 가른 셈이 된다.
    """
    sc = site.get("scene")
    if not sc:
        return [], "정사영상이 없어 건물 폴리곤을 낼 수 없다"
    if not config.available_models():
        return [], f"모델 가중치 없음: {config.MODELS / 'building'}"

    rings_px, scores, ens_note = _predict(site, sc["key"], tag, gpu=gpu, reuse=reuse,
                                          infer_fix=infer_fix)
    # 판정 임계값도 **영상별**이다 — 추론 임계값을 내린 영상에서 여기서 다시 잘라 내면
    # 되살린 검출이 그대로 사라진다([[settings.INFER_DINOV3_BY_SCENE]]).
    _kw, score_thr = config.infer_for(sc["key"])
    score_thr = ((infer_fix or {}).get(sc["key"]) or {}).get("score_threshold", score_thr)
    keep = [(r, s) for r, s in zip(rings_px, scores) if s >= score_thr]
    if not keep:
        return [], f"임계값({score_thr}) 이상 폴리곤이 없다 · {ens_note}"

    lonlat = _px_to_lonlat(site, [r for r, _ in keep])
    from shapely.geometry import Polygon

    raw = []
    for ring, (_, sco) in zip(lonlat, keep):
        poly = Polygon(ring)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if not poly.is_empty and poly.geom_type == "Polygon":
            raw.append((poly, float(sco)))
    return raw, ens_note


def attribute(site, raw, ens_note="", *, drop=(), shift=(), grow=()):
    """[(폴리곤, 점수)] → buildings FeatureCollection (EPSG:4326).

    필지가 있으면 이 지번 것만 남긴다 — 리포트 단위가 '이 지번의 땅'이기 때문이다.
    다만 이격(A1)은 옆 필지 건물까지 봐야 하므로 `neighbors` 로 따로 담아 돌려준다.
    """
    from shapely.geometry import shape
    if not raw:
        return schema.empty("buildings", ens_note or "유효한 폴리곤이 없다"), []

    parcel = shape(site["parcel"]) if site.get("parcel") else None
    # 귀속 판정에 쓸 인접 필지 — "우리가 제일 많이 가졌나"를 물으려면 상대가 있어야 한다.
    nb_polys = []
    for n in site.get("neighbors") or []:
        try:
            g = shape(n["geometry"])
            if g.is_valid and not g.is_empty:
                nb_polys.append(g)
        except Exception:                                    # noqa: BLE001
            pass
    # 합치기와 귀속이 **같은 임자 함수**를 쓴다 — 다른 것을 보면 합친 결과의 임자가
    # 합칠 때의 임자와 달라져 앞뒤가 맞지 않는다.
    owner = owner_index(site, parcel, nb_polys)
    merged = merge_touching([p for p, _ in raw], owner)   # 쪼개진 한 동을 도로 합친다

    feats, neighbors, straddle = [], [], 0
    for poly, idxs in merged:
        sco = max(raw[k][1] for k in idxs)
        m2 = _area_m2(poly)
        # id·역할·이름은 여기서 붙이지 않는다 — 대상·옆 지번을 다 가른 뒤 `label_features`
        # 한 곳에서 정한다(그러지 않으면 두 경로가 서로 다른 번호를 낸다).
        props = {"score": round(sco, 3),
                 "arch_area_m2": m2, "source": "model",
                 "merged_from": len(idxs),
                 "level": None, "label": None, "reason": None, "basis": None}
        # **귀속은 최대 지분으로 가른다.** 건축물대장은 필지(PNU) 단위라 경계에 살짝 걸친
        # 옆 건물을 이 필지 것으로 세면 실측 합계가 부풀려져 A3 가 전부 '증축'으로 나온다
        # (실측: 16곳 중 14곳). 그래서 지분을 본다 — 다만 기준을 **절대 과반(≥0.5)으로
        # 두면 안 된다.** 지번 경계를 걸친 건물은 어느 필지도 과반을 못 가져 전부 버려지기
        # 때문이다(실측 신당동 322: 1,295㎡ 공장동이 0.45 로 탈락해 '건물 0동'이 나왔다).
        #
        # 그래서 **아는 필지들 중 우리가 제일 많이 가졌는가**를 묻는다. 0.45 대 0.53 이면
        # 옆 땅 것이고, 0.45 대 0.25·0.20 이면 우리 것이다. 아무도 과반이 아니어도 임자는
        # 정해진다. 바닥값(OWN_MIN_FRAC)은 스치듯 걸친 건물을 막는다.
        frac, best_other = 1.0, 0.0
        if parcel is not None:
            try:
                a = max(poly.area, 1e-12)
                frac = poly.intersection(parcel).area / a
                best_other = max((poly.intersection(g).area for g in nb_polys), default=0.0) / a
            except Exception:                                # noqa: BLE001
                frac, best_other = 0.0, 1.0
        props["in_parcel_frac"] = round(float(frac), 3)
        props["rival_frac"] = round(float(best_other), 3)
        key = owner(poly)
        pnu_of, how, is_subject = key
        props["owner"] = pnu_of              # **PNU 그대로** — site.neighbors 로 풀 수 있다
        props["owner_by"] = how              # footprint(GIS 가 말했다) / parcel(필지 지분)
        props["registered"] = (how == "footprint")
        f = schema.feature(poly, props)
        # 「이 지번인가」는 `owner_index` 가 같이 돌려준다 — 열쇠 모양을 밖에서 파싱하면
        # 그 규칙이 두 곳(모델·GT 경로)에 살게 된다.
        mine = True if parcel is None else bool(is_subject)
        if mine:
            feats.append(f)
            if frac < 0.9:
                straddle += 1
        else:
            neighbors.append(f)      # 옆 필지 건물 — **결과에도 담는다**(이격 pair 의 상대다)
    feats, neighbors = label_features(feats, neighbors, site, drop=drop, shift=shift,
                                      grow=grow)
    if feats:
        note = ens_note
        if straddle:
            # **조용히 넘어가면 안 된다.** 지번 경계를 걸친 건물은 실측 건축면적이
            # 대장과 어긋나기 쉬운데(대지가 여러 지번일 수 있다), 그 사실이 A3 판정
            # 어디에도 남지 않으면 숫자만 보고 증축으로 읽는다.
            note += f" · 지번 경계를 걸친 건물 {straddle}동"
    elif neighbors:
        note = (f"이 필지에 걸치는 건물은 모두 옆 지번의 지분이 더 크다({len(neighbors)}동) "
                f"· {ens_note}")
    else:
        note = f"필지에 걸치는 건물 폴리곤이 없다 · {ens_note}"
    return schema.collection(feats, "buildings", note=note), neighbors


def detect(site, *, tag="sitecheck", gpu=None, reuse=True):
    """predict + attribute 를 한 번에. 정합을 끼우지 않을 때만 쓴다."""
    raw, note = predict(site, tag=tag, gpu=gpu, reuse=reuse)
    return attribute(site, raw, note)


def _area_m2(poly):
    """경위도 폴리곤 실면적(㎡) — UTM-K(EPSG:5179) 투영. **정수로 낸다.**

    소수 첫째 자리를 버리는 이유는 정밀도가 아니라 **합산**이다(2026-08-23). 종이는 면적을
    정수로 적는데(`f"{a:,.0f}"`) 값이 0.1 자리를 가지고 있으면 **한 번 접고 더한 값과 더하고
    접은 값이 갈린다** — 실측 신당동 1187-2: 동별 판독면적 열이 862 + 604 = 1,466 인데 합계
    행은 `round(861.6 + 603.9)` = **1,465** 로 찍혔다. 종이를 더해 본 사람이 표가 틀렸다고
    읽는다. 고잔동 672-6 도 3,579 + 181 = 3,760 인데 합계는 3,760.5 라 한 발만 어긋나면
    같은 일이 난다.
    **한쪽을 고르는 문제가 아니라 눈금을 하나로 두는 문제다** — 보고하는 값이 정수면 어느
    순서로 더해도 같다. 대장 면적도 같은 눈금이다([[steps/s4_ledger]] `round_areas`).

    잃는 것은 없다. 이 값의 오차는 0.5 ㎡ 가 아니라 **모델 면적오차 2 %**(A동 3,579 ㎡ 에서
    70 ㎡)이고, 판정 임계값은 30 ㎡ · 10 % 다(`rules.LEDGER_EXT_MIN_M2` · `LEDGER_EXT_RATIO`).
    0.5 ㎡ 로 갈리는 판정은 없다.
    """
    from pyproj import Transformer
    from shapely.ops import transform
    tr = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    return float(round(transform(tr.transform, poly).area))
