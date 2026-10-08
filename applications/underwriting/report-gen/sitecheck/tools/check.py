"""자립성 점검 — 이 폴더만으로 **무엇이 되고 무엇이 안 되는지**.

    python -m sitecheck.tools.check

한 줄로 늘어놓으면 "sitecheck 은 seglab·sam3env 가 있어야 한다"로 읽힌다. 실제로는 쓰임에
따라 필요한 것이 다르다 — 그래서 **묶음별로** 낸다.

    공통          주소 해석 · 대장 · 정사영상 — 무엇을 하든 필요하다
    모델 없이 결과  demo.py · hand_writting.py — GT 와 그림 규칙만 있으면 된다
    모델 추론      run.py 의 1단계 — 서브프로세스로 돌지만 **같은 환경**이면 된다

모델은 **단일**(DINOv3 동결 + Mask2Former · 8대칭 TTA)이고 코드·가중치·절차가 폴더 안에 있다.
따로 깔아야 하는 것은 실행 환경 하나뿐이다(`.venv` · `requirements.txt`) — 2026-08-27 에
둘을 하나로 합쳤다(README 5절). 모델만 다른 환경에서 돌리려면 `SITECHECK_DINOV3_PYTHON` 을
주면 되고, 아래 줄은 **그 파이썬에서 직접** 불러 본 값이다.
"""
from __future__ import annotations

import sys
from pathlib import Path

from sitecheck import settings as config

OK, NO = "  OK  ", "  --  "


def _sz(p):
    p = Path(p)
    if not p.exists():
        return f"{p} (없음)"
    if p.is_file():
        n = p.stat().st_size
        return f"{p.name} {n / 1e9:.1f} GB" if n > 1e8 else f"{p.name} {n / 1e6:.1f} MB"
    tot = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    if tot > 1e9:
        return f"{p.name} {tot / 1e9:.1f} GB"
    # **1 MB 미만을 「0 MB」로 찍지 않는다** — 벤더한 코드가 몇백 KB 라 그렇게 나오면 있는
    # 것이 없는 것처럼 읽힌다(실측: dinov3seg 484 KB → 「0 MB」).
    return f"{p.name} {tot / 1e6:.0f} MB" if tot > 1e6 else f"{p.name} {tot / 1e3:.0f} KB"


def common():
    rows = []
    k = config.keys()
    for n, ko in (("VWORLD_KEY", "V-World(지오코딩·연속지적도)"),
                  ("DATA_GO_KR_KEY", "공공데이터(건축물대장)"),
                  ("OPENAI_API_KEY", "OpenAI(야적 판독)")):
        rows.append((bool(k.get(n)), ko, f"assets/.env.* · {n}"))
    rows.append((config.GIS_BUILDINGS.exists(), "GIS건물통합정보", _sz(config.GIS_BUILDINGS)))
    for _key, v in config.SCENES.items():
        d = v["dir"]
        has = (d / "scene.png").exists() and any(Path(d).glob("*.tif"))
        rows.append((has, f"정사영상 {v['ko']}", _sz(d)))
    # 좌표 프레임 — 판정에는 주소마다 국소로 재므로 이 파일이 없어도 돈다. 있으면 **영상
    # 타일을 결과와 같은 좌표로 띄울 수 있다**(README 7절).
    got = [k for k, v in config.SCENES.items() if (v["dir"] / "georef.json").exists()]
    rows.append((True, "좌표 프레임(결과=지도 좌표)",
                 f"steps/georef.py · 영상 보정 지오트랜스폼 {len(got)}/{len(config.SCENES)} 장면"
                 + ("" if len(got) == len(config.SCENES)
                    else " · 영상을 함께 띄우려면 python -m sitecheck.steps.georef --write")))
    for mod, ko in (("sitecheck.vendor.geoapi", "V-World·대장 API 클라이언트"),
                    ("sitecheck.vendor.yard_vlm", "야적 판독 프롬프트·스키마"),
                    ("sitecheck.vendor.spectral", "분광 지수"),
                    ("sitecheck.vendor.shadow", "태양·그림자")):
        try:
            __import__(mod)
            rows.append((True, ko, mod))
        except Exception as e:                                # noqa: BLE001
            rows.append((False, ko, f"{mod} — {type(e).__name__}: {e}"))
    # 외부 공공데이터 캐시 — 없으면 보고서 5·6면이 「자료에서 찾지 못함」으로 난다.
    # 있으면 **받은 날**까지 보여 준다(갱신주기가 「수시」인 자료라 낡은 것이 문제가 된다).
    try:
        from sitecheck import ext
        if ext.STATIONS.exists():
            m = ext._meta(ext.STATIONS)
            rows.append((True, "외부데이터 소방관서 좌표",
                         f"{ext.STATIONS.name} · {m.get('rows') or '?'}개소 · "
                         f"받은 날 {m.get('fetched') or '?'}"))
        else:
            rows.append((False, "외부데이터 소방관서 좌표",
                         "소방서좌표.csv 없음 — `python -m sitecheck.ext` 로 받는다"))
        # 정적 표는 저장소에 들어 있어야 한다(런타임에 웹을 긁지 않는다).
        for path, ko in ((ext.ASOS_STN, "ASOS 지점 표"), (ext.WIND_TBL, "법정 기본풍속 표")):
            rows.append((path.exists(), f"외부데이터 {ko}",
                         f"{path.name}" + ("" if path.exists() else " 없음 — 저장소에 있어야 한다")))
        # 기후 백분위의 모집단 — 다 차지 않아도 돌지만 순위의 뜻이 좁아진다.
        pop = len(ext._cached_climate())
        rows.append((pop >= 80, "외부데이터 기후 캐시",
                     f"ASOS {pop}/{len(ext.asos_stations())}지점 · "
                     f"{ext.CLIMATE_Y0}~{ext.CLIMATE_Y1}"
                     + ("" if pop >= 80 else " — `python -m sitecheck.ext --climate`")))
    except Exception as e:                                    # noqa: BLE001
        rows.append((False, "외부데이터", f"sitecheck.ext — {type(e).__name__}: {e}"))
    for lst in sorted(config.HERE.glob("addresses*.txt")):
        n = sum(1 for ln in lst.read_text("utf-8").splitlines() if ln.split("#")[0].strip())
        rows.append((True, "예시 주소 목록", f"{lst.name} · {n}개"))
    return rows


def demo():
    """모델을 통과하지 않는 길에 필요한 것 — GT 와 (그림을 낼 때만) 그림 도구."""
    rows = []
    try:
        from sitecheck.gt import gt_file, rings_px
    except Exception as e:                                    # noqa: BLE001
        return [(False, "GT 모듈", f"sitecheck/gt — {type(e).__name__}: {e}")]
    for key, v in config.SCENES.items():
        p = gt_file(key)
        try:
            n = len(rings_px(key)) if p else 0
        except Exception:                                     # noqa: BLE001
            n = 0
        local = bool(p) and str(p).startswith(str(config.ASSETS))
        rows.append((bool(n), f"건물 GT {v['ko']}",
                     (f"{n:,}동 · {'폴더 사본' if local else 'seglab 원본'} · {_sz(p)}"
                      if p else f"assets/gt/{key}.json 없음 — demo.py 가 못 돈다")))
    try:
        import matplotlib                                     # noqa: F401
        from matplotlib import font_manager as fm
        has = any("Noto Sans CJK" in f.name or "Nanum" in f.name for f in fm.fontManager.ttflist)
        rows.append((True, "그림·문서 도구(matplotlib · 선택)", matplotlib.__version__))
        rows.append((has, "한글 글꼴", "Noto Sans CJK / Nanum" if has else "글자가 □ 로 나온다"))
    except Exception as e:                                    # noqa: BLE001
        rows.append((False, "그림·문서 도구(matplotlib · 선택)", f"{type(e).__name__}: {e}"))
    try:
        from sitecheck import draw
        rows.append((True, "그림 규칙", f"sitecheck/draw.py — 레이어 "
                     f"{'·'.join(n for n in ('sep_draw', 'yard_draw', 'ledger_draw') if hasattr(draw, n))}"))
    except Exception as e:                                    # noqa: BLE001
        rows.append((False, "그림 규칙", f"sitecheck/draw.py — {type(e).__name__}: {e}"))
    return rows


# 모델 종류마다 「코드가 폴더에 있나」와 「환경이 되나」를 보는 자리가 다르다. 한 곳에
# 적어 두면 모델을 갈 때 이 파일이 조용히 옛 모델을 가리킨다 — 그것이 점검 도구에서 가장
# 나쁜 실패다(초록불이 뜨는데 다른 것을 봤다).
_KIND = {
    "dinov3": {"ko": "DINOv3+Mask2Former",
               "code": ("vendor/dinov3seg", "infer.py"),
               "runner": "vendor/dinov3seg_run.py",
               "python": lambda: config.DINOV3_PYTHON,
               "req": "requirements.txt",
               "need": ("torch", "transformers", "cv2"),
               "note": "폴더 안 · 원본은 building_seg/dinov3_v2 (run4)"},
}


def _env_row(kind, spec):
    """그 모델을 돌릴 **그 파이썬**에서 필요한 것을 실제로 불러 본다.

    지금 돌고 있는 파이썬에서 `import torch` 를 해 보면 안 된다 — 모델은 서브프로세스로 도는데,
    `SITECHECK_DINOV3_PYTHON` 으로 다른 환경을 가리켜 두면 그 환경이 비어 있어도 여기서는
    초록불이 뜬다(실측: 환경이 둘이던 때 본체 .venv 의 torch 2.0 을 보고 「추론 환경 OK」를
    찍는데 정작 모델은 .venv-dinov3 에서 돌았다). 환경이 하나여도 재는 방법은 그대로 둔다 —
    가리키는 곳이 어디든 **그곳에서** 확인하는 것이 이 함수의 계약이다.
    """
    import subprocess
    py = spec["python"]()
    if not Path(py).exists():
        return (False, f"추론 환경 {spec['ko']}",
                f"{py} 가 없다 — uv pip install -r {spec['req']} (README 5절)")
    src = ("import json,importlib;"
           "d={};"
           f"[d.__setitem__(m, getattr(importlib.import_module(m), '__version__', '?')) for m in {list(spec['need'])!r}];"
           "import torch;d['cuda']=torch.cuda.is_available();print(json.dumps(d))")
    try:
        r = subprocess.run([str(py), "-c", src], capture_output=True, text=True, timeout=180)
        if r.returncode:
            tail = (r.stderr or "").strip().splitlines()[-1:] or ["알 수 없는 오류"]
            return (False, f"추론 환경 {spec['ko']}", f"{Path(py).parents[1].name} — {tail[0][:90]}")
        import json as _json
        d = _json.loads(r.stdout.strip().splitlines()[-1])
        cuda = "CUDA 됨" if d.pop("cuda", False) else "CPU 뿐 — 이 모델에는 너무 느리다"
        return (True, f"추론 환경 {spec['ko']}",
                " · ".join(f"{k} {v}" for k, v in d.items()) + f" · {cuda}")
    except Exception as e:                                    # noqa: BLE001
        return (False, f"추론 환경 {spec['ko']}", f"{type(e).__name__}: {e}")


def infer():
    """모델 추론(run.py 1단계)에만 필요한 것 — 코드·가중치는 폴더 안, 환경은 전용 venv."""
    rows = []
    avail = {m["tag"] for m in config.available_models()}
    kinds = []
    for m in config.BUILDING_MODELS:
        ok = m["tag"] in avail
        sz = (f"{Path(m['ckpt']).stat().st_size / 1e6:.0f} MB"
              if Path(m["ckpt"]).exists() else "가중치 없음")
        spec = _KIND.get(m.get("kind"))
        rows.append((ok, f"건물 모델 {m['tag']}{' (기하)' if m.get('geom') else ''}",
                     f"{(spec or {}).get('ko', m.get('kind'))} · tta{m['tta']} · {sz} · "
                     f"운용 임계값 {config.SCORE_THRESHOLD}"))
        if spec and m.get("kind") not in kinds:
            kinds.append(m.get("kind"))
    for kind in kinds or ["dinov3"]:
        spec = _KIND[kind]
        code = config.PKG / spec["code"][0]
        rows.append(((code / spec["code"][1]).exists(), f"모델 코드({spec['ko']})",
                     f"{_sz(code)} · {spec['note']}" if code.exists()
                     else f"sitecheck/{spec['code'][0]} 없음"))
        runner = config.PKG / spec["runner"]
        rows.append((runner.exists(), "추론 절차(타일·TTA·중복제거·폴리곤화)",
                     f"sitecheck/{spec['runner']} · 폴더 안"))
        rows.append(_env_row(kind, spec))
        rows.append((Path(spec["python"]()).exists(), "모델을 돌릴 파이썬",
                     str(spec["python"]())))
    return rows


GROUPS = (("공통 — 무엇을 하든 필요", common, None),
          ("모델 없이 결과 — demo.py · hand_writting.py", demo,
           "GT(assets/gt)로 바로 판정을 낸다 — 모델 추론 묶음이 없어도 돈다"),
          ("모델 추론 — run.py 의 1단계만", infer,
           "코드·절차·가중치가 폴더 안에 있다. **환경은 하나다**(`.venv` · requirements.txt · "
           "2026-08-27 에 합쳤다). 모델은 서브프로세스로 도므로, 아래는 그 파이썬에서 직접 "
           "불러 본 것이다 — `SITECHECK_DINOV3_PYTHON` 으로 다른 환경을 줄 수도 있다"))


def main():
    print("sitecheck 점검 — 쓰임별로\n")
    bad, tot = [], 0
    blocks = []
    for title, fn, tail in GROUPS:
        rows = fn()
        blocks.append((title, rows, tail))
        tot += len(rows)
        bad += [(title, r) for r in rows if not r[0]]
    w = max(len(r[1]) for _t, rows, _x in blocks for r in rows)
    for title, rows, tail in blocks:
        good = sum(1 for r in rows if r[0])
        print(f"■ {title}   {good}/{len(rows)}")
        if tail:
            print(f"   ({tail})")
        for ok, name, detail in rows:
            print(f"  [{OK if ok else NO}] {name:<{w}}  {detail}")
        print()
    print(f"{tot - len(bad)}/{tot} 준비됨")
    if bad:
        print("\n안 되는 것:")
        for title, (_o, name, detail) in bad:
            print(f"  · [{title.split(' —')[0]}] {name} — {detail}")
        print("\n  저장소가 담는 것: 코드 · 가중치 1개 · 건물 GT · 정사영상 3장 · "
              "GIS건물통합정보(LFS 6.5 GB).")
        print("  운영자가 넣는 것: API 키(assets/.env.*) · 실행 환경"
              "(uv pip install -r requirements.txt · README 5절).")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
