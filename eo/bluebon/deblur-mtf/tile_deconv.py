#!/usr/bin/env python3
"""deconv 를 타일 분할 + 프로세스 병렬로 실행해 전체 해상도 결과를 만든다.

deconv 자체는 단일 스레드이고 (FFTW 멀티스레드는 플랜이 작아 오히려 느림),
비용은 픽셀 수에 거의 선형이므로 타일을 나눠 코어 수만큼 동시에 돌리는 것이
가장 효율적이다.

이음선 방지를 위해 두 가지를 지킨다:
  1) overlap 만큼 넓게 잘라 deconv 하고 중심부만 취한다 (기본 128px,
     커널 31px / 실제 blur 지지 ~6px 대비 충분).
  2) 모든 타일에 --input-max 로 동일한 전역 최대값을 넘긴다. deconv 는
     이미지를 자기 최대값으로 정규화한 뒤 alpha 를 적용하므로, 이 값을
     고정하지 않으면 타일마다 실효 정규화 강도가 달라진다.

usage:
  python3 tile_deconv.py <in.tiff> <kernel.tif> <out.tiff> --alpha=1000
                         [--tile=2048] [--overlap=128] [--jobs=N]
"""
import os
import subprocess
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import rasterio
from rasterio.windows import Window

warnings.filterwarnings("ignore", module="rasterio")

ROOT = os.path.dirname(os.path.abspath(__file__))
DECONV = f"{ROOT}/deblur-l0/deconv-mt"
ENV = dict(os.environ, LD_LIBRARY_PATH=f"{ROOT}/libs", DECONV_THREADS="1")


def run_tile(job):
    """한 타일을 잘라 deconv 하고 중심부만 배열로 돌려준다."""
    (src_path, kernel, alpha, imax, tmpdir, idx,
     rx, ry, rw, rh, cx, cy, cw, ch) = job

    tin = f"{tmpdir}/t{idx}_in.tif"
    tout = f"{tmpdir}/t{idx}_out.tif"

    with rasterio.open(src_path) as src:
        data = src.read(1, window=Window(rx, ry, rw, rh))
        prof = src.profile
    prof.update(driver="GTiff", height=rh, width=rw, count=1,
                dtype=prof["dtype"], compress=None)
    prof.pop("predictor", None)
    with rasterio.open(tin, "w", **prof) as dst:
        dst.write(data, 1)

    subprocess.run(
        [DECONV, tin, kernel, tout, f"--alpha={alpha}", f"--input-max={imax}"],
        env=ENV, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    with rasterio.open(tout) as s:
        full = s.read(1)
    # 중심부(유효 영역)만 추출
    ox, oy = cx - rx, cy - ry
    out = full[oy:oy + ch, ox:ox + cw].copy()
    os.remove(tin)
    os.remove(tout)
    return idx, cx, cy, out


def main():
    pos = [a for a in sys.argv[1:] if not a.startswith("--")]
    opt = {}
    for a in sys.argv[1:]:
        if a.startswith("--"):
            k, _, v = a[2:].partition("=")
            opt[k] = v
    if len(pos) != 3:
        print(__doc__)
        sys.exit(1)
    src_path, kernel, out_path = pos
    alpha = opt.get("alpha", "3000")
    tile = int(opt.get("tile", 2048))
    ov = int(opt.get("overlap", 128))
    jobs = int(opt.get("jobs", 0)) or min(os.cpu_count() or 4, 14)

    with rasterio.open(src_path) as src:
        W, H, prof = src.width, src.height, src.profile
        # 전역 최대값: 원본 전체 스캔 (deconv 단일 실행과 동일한 정규화 상수)
        imax = 0.0
        for _, win in src.block_windows(1):
            imax = max(imax, float(src.read(1, window=win).max()))

    tmpdir = os.environ.get(
        "TILE_TMP", f"/tmp/claude-1000/tile_{os.getpid()}")
    os.makedirs(tmpdir, exist_ok=True)

    jl = []
    idx = 0
    for cy in range(0, H, tile):
        for cx in range(0, W, tile):
            cw, ch = min(tile, W - cx), min(tile, H - cy)
            rx, ry = max(0, cx - ov), max(0, cy - ov)
            rw = min(W, cx + cw + ov) - rx
            rh = min(H, cy + ch + ov) - ry
            jl.append((src_path, kernel, alpha, imax, tmpdir, idx,
                       rx, ry, rw, rh, cx, cy, cw, ch))
            idx += 1

    print(f"{os.path.basename(src_path)}: {W}x{H} -> {len(jl)} tiles "
          f"({tile}px, overlap {ov}px), {jobs} parallel, input-max={imax:g}")

    # 압축 striped GeoTIFF 는 임의 위치 쓰기가 안 되므로 메모리에 모아 한 번에 쓴다
    # (float32 전체가 약 250MB 로 부담 없음)
    canvas = np.empty((H, W), dtype=np.float32)
    t0 = time.time()
    done = 0
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        for _, cx, cy, arr in ex.map(run_tile, jl):
            canvas[cy:cy + arr.shape[0], cx:cx + arr.shape[1]] = arr
            done += 1
            print(f"\r  {done}/{len(jl)} tiles  {time.time()-t0:.0f}s",
                  end="", flush=True)

    prof.update(driver="GTiff", dtype="float32", count=1,
                compress="deflate", predictor=2)
    with rasterio.open(out_path, "w", **prof) as dst:
        dst.write(canvas, 1)
    print(f"\n  -> {out_path}  ({time.time()-t0:.0f}s)")
    os.rmdir(tmpdir)


if __name__ == "__main__":
    main()
