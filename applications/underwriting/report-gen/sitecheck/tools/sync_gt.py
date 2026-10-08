"""seglab 의 GT 원본 → 폴더 안 사본(`assets/gt/<장면>.json`) **다시 맞추기.**

    python -m sitecheck.tools.sync_gt              # 어긋난 장면을 다 맞춘다
    python -m sitecheck.tools.sync_gt --check      # 무엇이 어긋났는지만 본다(고치지 않는다)
    python -m sitecheck.tools.sync_gt daegu2       # 장면 하나만

**정본은 seglab 이다.** 사람이 GT 를 고치는 곳은 거기(`seglab/annotate`)이고, 이 폴더의
`assets/gt/*.json` 은 사본이다 — 사본을 두는 이유는 [[gt.py]] 에 있다(네 장면 합쳐 2 MB 라
담아 두면 데모·보고서가 seglab 없이 돈다). 그 대가가 **원본을 고치면 사본이 뒤처진다**는
것이고, 이 도구가 그 대가를 치른다. 반대 방향은 없다 — 사본에서 원본으로 되돌리지 않는다.

사본에 더 붙는 것 셋(원본에는 `polys` 뿐이다).
  · `source` — 어느 seglab 지역에서 왔는지. 사본만 손에 든 사람이 원본을 찾을 수 있게.
  · `count` — **지금 이 파일의** 동수. 어긋남을 눈으로 잡는 첫 줄이다.
  · `ported_from` — 이식 내력(원본 옆 `_ported_from.json` + 어느 **장면**에서 왔는지).
    [[steps/gt_parallax.py]] 가 이 블록의 유무로 지붕 시차를 보정할지 정하고 `nudge_px` ·
    `shift_px` 를 그대로 쓴다. **내력이지 지금 동수가 아니다** — 이식한 뒤 사람이 그 장면에서
    손으로 고치면 `n_kept` 와 `count` 는 갈린다(대구2차 2026-08-26: 이식 2,069 → 지금 2,044).
    갈렸다고 고쳐 적지 않는다. 그 값으로 옮겼다는 사실이 시차 보정의 근거다.

좌표는 **손대지 않고** 옮긴다(장면 픽셀 그대로, 원본이 적어 둔 소수점 그대로). 사본과 원본의
`polys` 가 글자까지 같아야 「사본이 원본이다」를 파일 크기만으로도 말할 수 있다.

맞춘 뒤 저장된 산출물(`demo/` · `demo_cmp/` · `out_gt/`)은 **옛 GT 로 낸 것**이다 — 창 안
동수가 바뀐 주소는 다시 돌려야 한다. 어느 주소가 바뀌었는지는 마지막에 찍는다.

표에 찍는 동수는 **파이프라인이 실제로 쓰는 링**(4점 이상 · [[gt.py]] `rings_px` 와 같은
기준)이라 파일의 `count` 보다 한둘 적을 수 있다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sitecheck import gt as GT
from sitecheck import settings as config

CRS_NOTE = "scene pixel (x, y)"      # 원본이 무슨 좌표인지 사본에 적어 둔다
MIN_RING = 4                         # gt.rings_px 가 버리는 것과 같은 기준(3점 이하는 면이 아니다)


def _rel(p):
    """`seglab/regions/…/gt/polygons.json` — seglab 밖이면 절대경로 그대로."""
    p = Path(p)
    try:
        return str(p.relative_to(config.SEGLAB.parent))
    except ValueError:
        return str(p)


def _ported(src_path):
    """원본 옆 `_ported_from.json` + `src_scene`(어느 장면에서 옮겨 왔는지) 또는 None."""
    f = Path(src_path).parent / "_ported_from.json"
    if not f.exists():
        return None
    try:
        d = json.loads(f.read_text("utf-8"))
    except Exception as e:                                       # noqa: BLE001
        print(f"  ! {_rel(f)} 를 못 읽었다 ({type(e).__name__}) — 이식 내력 없이 적는다")
        return None
    from sitecheck.steps.gt_parallax import _region_scene
    sc = _region_scene(str(d.get("src") or ""))
    return dict(d, src_scene=sc) if sc else dict(d)


def wrapped(scene_key, src_path):
    """사본에 쓸 dict. 순서를 고정한다 — 사람이 머리 몇 줄만 보고 무엇인지 알아야 한다."""
    polys = json.loads(Path(src_path).read_text("utf-8")).get("polys") or []
    out = {"scene": scene_key, "source": _rel(src_path), "crs": CRS_NOTE, "count": len(polys)}
    pf = _ported(src_path)
    if pf:
        out["ported_from"] = pf
    out["polys"] = polys
    return out


def _rings(d):
    return [r for r in (d.get("polys") or []) if len(r) >= MIN_RING]


def _key(ring):
    return tuple((round(x, 1), round(y, 1)) for x, y in ring)


def diff(old, new):
    """(빠짐, 생김) — 링 하나라도 점이 움직이면 「빠짐 1 · 생김 1」로 센다."""
    a = [_key(r) for r in _rings(old)]
    b = [_key(r) for r in _rings(new)]
    sa, sb = set(a), set(b)
    return sum(1 for k in sa if k not in sb), sum(1 for k in sb if k not in sa)


def touched(scene_key, old, new):
    """옛·새 GT 로 **저장된 결과의 창**을 다시 떠서 동수가 달라진 것만.

    장면 전체가 몇 동 바뀌었는지는 다시 돌릴 이유가 못 된다 — 고친 자리가 표본 주소의 창
    밖이면 산출물은 그대로다. 창을 뜨는 것은 [[gt.py]] `rings_in_window` 그 함수다(다시
    구현하면 여백·거르기가 갈린다).
    """
    from sitecheck.steps import georef
    out = []
    saved = [(p, p.parent) for pat, name in ((config.HERE / "demo", "demo.json"),
                                             (config.HERE / "demo_cmp" / "t1", "demo.json"),
                                             (config.HERE / "demo_cmp" / "t2", "demo.json"),
                                             (config.HERE / "out_gt", "demo.json"),
                                             (config.OUT, "result.json"))
             for p in sorted(Path(pat).glob(f"*/{name}"))]
    for f, d in saved:
        try:
            site = json.loads(f.read_text("utf-8"))["site"]
            georef.migrate(site)
        except Exception:                                        # noqa: BLE001
            continue
        if ((site.get("scene") or {}).get("key")) != scene_key:
            continue
        got = {}
        for tag, src in (("old", old), ("new", new)):
            GT._CACHE[scene_key] = _rings(src)
            try:
                got[tag], _win = GT.rings_in_window(site)
            except Exception as e:                               # noqa: BLE001
                print(f"  ! {d.name} 의 창을 못 떴다 — {type(e).__name__}: {e}")
                got = {}
                break
        GT._CACHE.pop(scene_key, None)
        if not got:
            continue
        so = {_key(r) for r in got["old"]}
        sn = {_key(r) for r in got["new"]}
        if so != sn:
            out.append((f"{f.parent.parent.name}/{d.name}", len(so), len(sn),
                        len(so - sn), len(sn - so)))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="seglab GT 원본 → assets/gt 사본 동기화")
    ap.add_argument("scenes", nargs="*", help="장면 key (없으면 등록된 장면 전부)")
    ap.add_argument("--check", action="store_true", help="고치지 않고 어긋남만 보고한다")
    a = ap.parse_args(argv)

    keys = a.scenes or list(config.SCENES)
    bad = [k for k in keys if k not in config.SCENES]
    if bad:
        raise SystemExit(f"등록되지 않은 장면: {', '.join(bad)} — 있는 것: "
                         f"{', '.join(config.SCENES)}")
    if not config.SEGLAB.exists():
        raise SystemExit(f"seglab 이 없다({config.SEGLAB}) — 정본이 없으면 맞출 것이 없다. "
                         f"경로는 SITECHECK_SEGLAB 로 바꾼다")

    changed, notes = [], []
    print(f"{'장면':10s} {'사본':>7s} {'원본':>7s} {'빠짐':>5s} {'생김':>5s}  원본")
    print("─" * 92)
    for k in keys:
        src = GT.seglab_file(k)
        if src is None:
            print(f"{k:10s} {'—':>7s} {'—':>7s} {'—':>5s} {'—':>5s}  "
                  f"seglab 에 원본이 없다 — 사본을 그대로 둔다")
            continue
        new = wrapped(k, src)
        loc = GT.local_file(k)
        old = json.loads(loc.read_text("utf-8")) if loc else {}
        gone, born = diff(old, new)
        same = not gone and not born and old.get("ported_from") == new.get("ported_from")
        print(f"{k:10s} {len(_rings(old)):7,d} {len(_rings(new)):7,d} "
              f"{gone:5d} {born:5d}  {new['source']}{'' if not same else '  (같다)'}")
        if same:
            continue
        changed.append(k)
        notes += [(k, *t) for t in touched(k, old, new)]
        if not a.check:
            p = config.ASSETS / "gt" / f"{k}.json"
            p.write_text(json.dumps(new, ensure_ascii=False), "utf-8")
            print(f"           → {p.relative_to(config.HERE)} "
                  f"{p.stat().st_size / 1e6:.2f} MB 로 다시 적었다")

    if not changed:
        print("\n사본이 원본과 같다 — 맞출 것이 없다.")
        return 0
    print(f"\n{'맞출 것' if a.check else '맞춘 장면'}: {', '.join(changed)}")
    if notes:
        # **다시 돌릴 것을 이름으로 찍는다.** 창 안 동수가 바뀌면 이격·야적·대장 표가
        # 다 따라 바뀌므로, 저장된 값·그림·보고서는 옛 GT 의 것이다.
        print("\n저장된 산출물 중 **창 안 GT 가 바뀐 것** — 다시 돌려야 한다:")
        for k, name, n_old, n_new, gone, born in notes:
            print(f"  {name:46s} {k:8s} {n_old:3d} → {n_new:3d}동 (빠짐 {gone} · 생김 {born})")
        print("    demo/ · out_gt/ → demo.py · hand_writting.py, demo_cmp/ → "
              "hand_writting.py --only cmp")
    else:
        print("\n저장된 산출물의 창 안 GT 는 그대로다 — 다시 돌릴 것이 없다.")
    return 1 if a.check else 0


if __name__ == "__main__":
    sys.exit(main())
