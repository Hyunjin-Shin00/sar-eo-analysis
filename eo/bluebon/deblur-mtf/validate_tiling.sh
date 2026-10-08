#!/bin/bash
# 실행 중인 단일프로세스 deconv 가 끝나기를 기다린 뒤,
# 타일 방식으로 MS1 alpha=1000 을 다시 계산해 전체이미지 결과와 비교한다.
set -u
cd <WORK_ROOT>/working/debulr

echo "== 기존 작업 대기 =="
while pgrep -f "deblur-l0/deconv " > /dev/null; do sleep 15; done
echo "완료 $(date +%T)"
ls -la output/*.tiff

echo "== 타일 방식 실행 (검증용) =="
TILE_TMP=<WORK_ROOT>/working/debulr/.tiletmp \
python3 tile_deconv.py input/MS1_DN_dark_rc_p.tiff output/k31_ms1_i5.tif \
    output/_val_ms1_a1000_tiled.tiff --alpha=1000 2>&1 | grep -v Warning

echo "== 전체이미지 결과와 차이 비교 =="
python3 - <<'PY'
import numpy as np, rasterio, warnings
warnings.filterwarnings("ignore")
def rd(p):
    with rasterio.open(p) as s: return s.read(1)
a = rd("output/de_ms1_k31_i5_a1000.tiff")      # 전체 이미지 1회 처리
b = rd("output/_val_ms1_a1000_tiled.tiff")     # 타일 분할 처리
d = np.abs(a.astype(np.float64) - b.astype(np.float64))
rng = float(a.max() - a.min())
print(f"DN range            : {a.min():.1f} ~ {a.max():.1f}")
print(f"mean |diff|         : {d.mean():.4f} DN  ({d.mean()/rng*100:.4f}% of range)")
print(f"p99.9 |diff|        : {np.percentile(d,99.9):.4f} DN")
print(f"max  |diff|         : {d.max():.4f} DN  ({d.max()/rng*100:.4f}%)")
# 타일 경계 부근만 따로 (이음선 확인)
seam = np.zeros(a.shape, bool)
for y in range(2048, a.shape[0], 2048): seam[y-2:y+2,:] = True
for x in range(2048, a.shape[1], 2048): seam[:,x-2:x+2] = True
print(f"경계 2px 대역 mean  : {d[seam].mean():.4f} DN / max {d[seam].max():.4f}")
print(f"경계 외 mean        : {d[~seam].mean():.4f} DN / max {d[~seam].max():.4f}")
PY
