"""정합 2차 — 모델 폴리곤으로 **영상 지오레퍼런스 보정을 확인하고 마무리한다.**

**옮기는 대상은 영상이다.** 지도 기하(필지 · GIS footprint)는 조회한 좌표 그대로 두고,
어긋난 영상 쪽을 되돌린다([[georef.py]] 에 왜 이 방향인지 적어 두었다). 예전에는 반대로
필지를 옮겼고, 그래서 내보낸 좌표가 지도 좌표가 아니었다.

두 단계로 잰다.

  1차 · 엣지 정합 (`parcel_fit.py` → `georef.apply`)
      footprint 경계 ↔ 영상 그래디언트. **모델이 없어도 돌아간다.** 새 영상이 들어오면
      제일 먼저 이것이 돌아 대략을 맞춘다(등록부에 없는 창원 영상 실측: 3주소 모두
      국소 정합 성공, 이득 1.23~1.48).

  2차 · 모델 정합 (이 파일)
      모델 폴리곤 ↔ GIS footprint 를 IoU 로 짝지어 중심 편차의 중앙값을 낸다.
      **의미로 짝짓는 것**이라 그래디언트 최댓값보다 해석이 분명하고, 픽셀 격자에 묶이지
      않아 미터로 바로 나온다. 모델을 이미 돌린 뒤라 비용이 사실상 없다.

1차만으로도 대개 충분하다(실측 잔차 중앙 동 −0.09 m · 북 +0.26 m). 2차는 그것을
**확인하고** 남은 편이를 마저 없애는 자리다 — 그리고 확인 자체가 값이다. 정합이 틀렸을 때
조용히 틀린 답이 나오는 것이 이 파이프라인에서 가장 위험하기 때문이다.

**한 가지 함정.** GT 경로([[gt.py]])의 GT 가 GIS건물통합정보에서 시딩된
장면에서는(남동공단 · seglab `scripts/seed_ledger_gt.py`) 여기 잔차가 **독립 측정이 아니다**
— 기준선과 재는 대상이 같은 출처라 0 에 가깝게 나오는 것이 당연하다(실측 0.00~0.02 m).
그 장면에서 독립적인 값은 1차 엣지 정합과 모델 경로(`run.py`)의 잔차다. 다행히 보정량의
대부분이 1차에서 나오므로(남동공단 7.2 m 중 6.6 m) 결론은 바뀌지 않지만, 그 0 을 "정합이
완벽하다"로 읽으면 안 된다.

영상을 옮기면 **그 영상에서 나온 폴리곤도 같이 옮겨야 한다** — 그래서 `refine` 은 폴리곤
목록을 돌려준다. 받은 쪽이 그것을 다시 쓰지 않으면 건물만 옛 좌표에 남는다.

    python -m sitecheck.steps.align out/*/     저장된 결과의 정합 잔차를 잰다(추론 안 함)
    python -m sitecheck.steps.align --all      demo/·out/ 에 저장된 전부

**이것이 프레임 검증 도구다.** 「영상보정」칸은 그 주소에서 영상을 얼마나 되돌렸는지고,
「동/북」칸은 되돌린 뒤에 남은 양이다. 뒤 칸이 0 에 가까우면 내보낸 좌표가 지도 좌표라는
뜻이다(실측: 보정 전 2~9 m → 보정 후 0~1 m).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

MIN_PAIRS = 5        # 이보다 적으면 중앙값이 표본 잡음이다
MIN_IOU = 0.35       # 같은 건물로 볼 최소 겹침 — 모델 지붕과 GIS 외곽은 원래 조금 다르다
TOL_M = 0.75         # 이보다 작은 잔차는 고치지 않는다(모델 경계오차 0.78 m 수준)
MAX_M = 25.0         # 이보다 크면 정합이 아니라 다른 문제다 — 손대지 않고 남긴다


def _utm():
    from pyproj import Transformer
    return Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)


def residual(site, model_polys, *, min_pairs=MIN_PAIRS, min_iou=MIN_IOU, min_m2=150.0):
    """(동 m, 북 m, 짝 수, 평균 IoU) — 영상에서 나온 건물이 지도 정본보다 **얼마나 밀려 있나**.

    양수 = 모델 폴리곤이 footprint 보다 동/북에 있다 = 영상을 그만큼 서/남으로 되돌려야
    한다. `georef.add_m` 이 받는 부호와 같다(그 함수가 안에서 뒤집는다).

    짝이 모자라면 None — 없는 정합을 지어내면 조용히 틀린다.
    """
    import numpy as np
    from shapely.geometry import shape
    from shapely.ops import transform
    from sitecheck.vendor import gisdb

    if not site.get("parcel") or not model_polys:
        return None
    tr = _utm()
    par = shape(site["parcel"])
    try:
        recs = gisdb.near(par.buffer(0.0016).bounds)
    except Exception:                                        # noqa: BLE001
        return None
    if not recs:
        return None
    # **footprint 는 조회한 좌표 그대로 쓴다** — 이것이 기준선이다. 예전에는 여기서
    # `shift_geoms` 로 영상 쪽으로 끌어왔는데, 그러면 기준선이 재는 대상과 같이 움직였다.
    fps = [r["geometry"] for r in recs]
    mod = []
    for p in model_polys:
        q = p if p.is_valid else p.buffer(0)
        if q.is_empty or q.geom_type != "Polygon":
            continue
        m = transform(tr.transform, q)
        if m.area >= min_m2:
            mod.append(m)
    if not mod:
        return None

    d = []
    for fp in fps:
        fm = transform(tr.transform, fp)
        if fm.area < min_m2:
            continue
        best = None
        for m in mod:
            i = fm.intersection(m).area
            if i <= 0:
                continue
            iou = i / (fm.area + m.area - i)
            if best is None or iou > best[0]:
                best = (iou, m)
        if best and best[0] >= min_iou:
            d.append((best[1].centroid.x - fm.centroid.x,
                      best[1].centroid.y - fm.centroid.y, best[0]))
    if len(d) < min_pairs:
        return None
    a = np.asarray(d)
    return float(np.median(a[:, 0])), float(np.median(a[:, 1])), len(d), float(a[:, 2].mean())


def refine(site, model_polys, *, tol_m=TOL_M, max_m=MAX_M):
    """잔차만큼 **영상 지오레퍼런스를 더 되돌린다.** 옮긴 폴리곤 목록을 돌려준다.

    영상을 옮기면 그 영상에서 나온 폴리곤의 좌표도 같이 달라진다. 다시 변환하지 않고 같은
    양만큼 평행이동하는 것으로 충분하다 — 보정 자체가 평행이동이다.

    **필지·footprint 는 건드리지 않는다.** 지도에서 조회한 좌표가 정본이다.
    """
    r = residual(site, model_polys)
    if not r:
        # **세 값을 한 벌로 지운다.** 잔차만 지우면 저장본에서 물려받은 옛 `짝 N동 · IoU x`
        # 가 남아, 「못 쟀다」와 「이만큼 맞았다」가 한 결과에 같이 적힌다 — 새로 해석하는
        # 길(`run.py`)은 site 가 매번 새것이라 겪지 않지만, 저장된 site 를 쓰는 길
        # (`demo.py` · `hand_writting.py`)은 겪는다.
        site["align_residual_m"] = None
        site.pop("align_pairs", None)
        site.pop("align_iou", None)
        return list(model_polys)
    dx, dy, n, iou = r
    site["align_residual_m"] = [round(dx, 2), round(dy, 2)]
    site["align_pairs"] = n
    site["align_iou"] = round(iou, 3)
    dist = (dx * dx + dy * dy) ** 0.5
    if dist < tol_m:
        site["notes"].append(f"2차 정합 — 잔차 ({dx:+.2f},{dy:+.2f}) m · 짝 {n}동 · "
                             f"IoU {iou:.2f} · 허용 {tol_m} m 안이라 그대로 둔다")
        return list(model_polys)
    if dist > max_m:
        site["notes"].append(f"2차 정합 보류 — 잔차 {dist:.1f} m 는 평행이동으로 볼 수 없다"
                             f"(짝 {n}동 · IoU {iou:.2f}). 영상을 더 옮기지 않는다")
        return list(model_polys)

    from shapely.affinity import translate
    from shapely.ops import transform
    from pyproj import Transformer
    from sitecheck.steps import georef
    fwd = _utm()
    inv = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)

    georef.add_m(site, dx, dy, src=f"모델정합({n}동 · IoU {iou:.2f})")
    out = []
    for p in model_polys:
        try:
            out.append(transform(inv.transform,
                                 translate(transform(fwd.transform, p), -dx, -dy)))
        except Exception:                                    # noqa: BLE001
            out.append(p)
    g = site.get("georef") or {}
    e, nn = (g.get("offset_m") or [0.0, 0.0])
    site["notes"].append(f"2차 정합 — 모델 폴리곤 {n}동이 GIS footprint 보다 "
                         f"({dx:+.2f},{dy:+.2f}) m 밀려 있어 영상을 그만큼 되돌렸다 · "
                         f"IoU {iou:.2f} · 누적 영상 편이 ({e:+.1f},{nn:+.1f}) m")
    return out


def _report(dirs):
    """저장된 result.json 의 정합 잔차를 다시 잰다 — 추론은 하지 않는다."""
    import json
    from shapely.geometry import shape
    print(f"{'주소':30s} {'영상보정(동,북)':>16s} {'짝':>4s} {'동(m)':>8s} {'북(m)':>8s} "
          f"{'IoU':>6s}  판정")
    print("─" * 96)
    for d in dirs:
        d = Path(d)
        # 모델 결과와 데모 결과 둘 다 본다 — 이름만 갈라 둔 같은 형식이다([[pipeline.py]]).
        f = next((p for p in (d / "result.json", d / "demo.json") if p.exists()), None)
        if f is None:
            continue
        res = json.loads(f.read_text("utf-8"))
        site = res["site"]
        # 옛 결과(영상 프레임)도 읽을 수 있게 한다 — 안 옮기면 `georef.xform` 이 거부한다.
        from sitecheck.steps import georef
        georef.migrate(site)
        # **귀속된 건물(1~3동)만 쓰면 표본이 모자라 중앙값이 잡음이다.** 추론 창 전체
        # (필지 ±80 m, 20~40동)를 쓴다 — 저장된 멤버 결과를 읽는 것이라 추론은 없다.
        polys = []
        try:
            from sitecheck.steps import s1_building
            tag = ((res.get("provenance") or {}).get("tag")
                   or f"sitecheck_{site.get('pnu')}")
            raw, _ = s1_building.predict(site, tag=tag, reuse=True)
            polys = [p for p, _s in raw]
        except Exception:                                    # noqa: BLE001
            polys = []
        if not polys:
            bf = d / "buildings.geojson"
            if bf.exists():
                polys = [shape(ft["geometry"])
                         for ft in json.loads(bf.read_text("utf-8")).get("features") or []]
        g = site.get("georef") or {}
        off = ("(%+.1f,%+.1f)" % tuple(g.get("offset_m") or [0, 0])) if g.get("applied") else "안 함"
        r = residual(site, polys, min_pairs=1)
        if not r:
            print(f"{d.name[:28]:30s} {off:>16s} {'—':>4s} {'—':>8s} {'—':>8s} "
                  f"{'—':>6s}  잴 수 없음")
            continue
        dx, dy, n, iou = r
        dist = (dx * dx + dy * dy) ** 0.5
        v = "맞음" if dist < TOL_M else ("확인" if dist < 3 else "어긋남")
        print(f"{d.name[:28]:30s} {off:>16s} {n:4d} {dx:+8.2f} {dy:+8.2f} {iou:6.3f}  {v}")


if __name__ == "__main__":
    from sitecheck import settings as config
    args = sys.argv[1:]
    if not args or args[0] == "--all":
        # 모델 결과(out/result.json)와 데모 결과(demo/demo.json) 둘 다 본다 — 프레임 검증은
        # 두 길에 같이 걸리는 문제라 한쪽만 보면 절반만 확인한 것이 된다.
        args = [str(p.parent) for pat, name in ((config.OUT, "result.json"),
                                                (config.HERE / "demo", "demo.json"))
                for p in sorted(pat.glob(f"*/{name}"))]
    _report(args)
