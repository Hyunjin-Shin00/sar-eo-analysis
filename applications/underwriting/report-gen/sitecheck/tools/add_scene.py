"""새 정사영상 TIF → 이 폴더가 바로 쓰는 장면.

    python -m sitecheck.tools.add_scene --tif /경로/새영상.tif --key ulsan --ko 울산

`assets/scenes/<key>/` 에 원본 tif(심볼릭) · scene.png · meta.json 을 만든다. 만들고 나면
`settings._discover()` 가 자동으로 잡으므로 **소스를 고칠 필요가 없다**.

TelePIX SSC pansharpened 4밴드(uint16)의 물리 순서는 **B,G,R,NIR** 인데 colorinterp 태그는
R,G,B 로 잘못 붙어 있다 — 그대로 [1,2,3] 을 읽으면 R↔B 가 뒤바뀐 그림이 나온다. 그래서
기본 밴드 순서가 `3,2,1` 이다. 다른 센서면 `--bands` 로 맞춘다(3밴드 RGB 는 `1,2,3`).

    python -m sitecheck.tools.add_scene --tif rgb.tif --key sejong --bands 1,2,3
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np

from sitecheck import settings as config


def stretch(arr3, lo_pct=2.0, hi_pct=98.0, decim=4000):
    """(3,H,W) → (H,W,3) uint8. 채널별 nonzero 퍼센타일 스트레치. nodata(전채널 0)=검정 유지.

    검정을 지키는 것이 중요하다 — 정합도 야적 판독도 nodata 를 `g > 6` 으로 걸러 낸다.
    """
    H, W = arr3.shape[1:]
    s = max(1, W // decim)
    sub = arr3[:, ::s, ::s]
    valid = arr3.sum(0) > 0
    out = np.zeros((H, W, 3), np.uint8)
    for c in range(3):
        v = sub[c].ravel()
        nz = v[v > 0]
        lo, hi = (np.percentile(nz, [lo_pct, hi_pct]) if nz.size else (0.0, 1.0))
        hi = hi + (hi <= lo)
        ch = (arr3[c].astype(np.float32) - lo) / (hi - lo)
        out[..., c] = np.clip(ch * 255.0, 0, 255).astype(np.uint8)
    out[~valid] = 0
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="새 정사영상 TIF 를 sitecheck 장면으로 등록")
    ap.add_argument("--tif", required=True, help="입력 정사영상(GeoTIFF, CRS 필요)")
    ap.add_argument("--key", required=True, help="장면 key — 영문 소문자 권장(폴더 이름이 된다)")
    ap.add_argument("--ko", default=None, help="표시용 한글 이름(기본 key)")
    ap.add_argument("--bands", default="3,2,1", help="R,G,B ← 소스 밴드 (B,G,R,NIR → 3,2,1)")
    ap.add_argument("--copy", action="store_true", help="tif 를 심볼릭 대신 사본으로")
    ap.add_argument("--preview-w", type=int, default=2400)
    a = ap.parse_args(argv)

    import rasterio
    from rasterio.warp import transform_bounds
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None

    tif = Path(a.tif).resolve()
    if not tif.exists():
        raise SystemExit(f"tif 없음: {tif}")
    if a.key in config.EXCLUDED_SCENES:
        raise SystemExit(f"'{a.key}' 는 settings.EXCLUDED_SCENES 에 있다 — 이유를 먼저 읽으세요")
    dst = config.ASSETS / "scenes" / a.key
    bands = [int(x) for x in a.bands.split(",")]

    with rasterio.open(tif) as ds:
        W, H, res = ds.width, ds.height, ds.res
        if ds.crs is None:
            raise SystemExit("CRS 가 없는 tif 다 — 벡터↔픽셀 변환을 만들 수 없다")
        if max(bands) > ds.count:
            raise SystemExit(f"밴드 {bands} 인데 tif 는 {ds.count}밴드다 — --bands 를 맞추세요")
        print(f"[read] {tif.name} {W}x{H} bands={ds.count} crs={ds.crs} res={res}")
        rgb16 = ds.read(bands)
        west, south, east, north = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)

    rgb = stretch(rgb16.astype(np.uint16))
    del rgb16
    dst.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgb, "RGB").save(dst / "scene.png", compress_level=1)
    print(f"[save] {dst/'scene.png'}")
    if W > a.preview_w:
        ph = int(H * a.preview_w / W)
        Image.fromarray(rgb, "RGB").resize((a.preview_w, ph), Image.BILINEAR).save(dst / "preview.png")

    link = dst / tif.name
    if not link.exists():
        if a.copy:
            shutil.copy2(tif, link)
        else:
            link.symlink_to(tif)
    json.dump({"area": a.ko or a.key, "bbox": [west, south, east, north],
               "m2_per_px": round(float(res[0]) * float(res[1]), 4),
               "res_m": float(res[0]), "width": W, "height": H,
               "src_tif": str(tif), "rgb_from_bands": bands},
              open(dst / "meta.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[save] {dst/'meta.json'}  bbox(4326)={[round(v, 5) for v in (west, south, east, north)]}")

    if a.ko:                       # 한글 이름은 settings 에서만 읽는다 — 안내만 한다
        print(f"\n한글 이름을 고정하려면 settings.SCENE_NAMES 에 \"{a.key}\": \"{a.ko}\" 를 넣으세요.")
    import importlib
    importlib.reload(config)
    ok = a.key in config._discover()
    print(f"\n등록 {'성공' if ok else '실패'} — python -m sitecheck.tools.check 로 확인하세요.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
