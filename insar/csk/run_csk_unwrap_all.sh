#!/usr/bin/env bash
set -e
set -o pipefail

########################################
# 0) 작업 디렉토리
########################################
BASE=/home/hyunjin/nas/nationalpark_SAR/CSK/20200712_20200713_interferogram_pyps
mkdir -p "$BASE"
cd "$BASE"

########################################
# 1) conda env + HDF5 락 방지
########################################
conda activate pyps
export HDF5_USE_FILE_LOCKING=FALSE

# snaphu는 StaMPS_Python/bin 우선 사용 (매뉴얼대로 빌드한 것)
export PATH="$HOME/StaMPS_Python/bin:$PATH"

echo "[ENV] python=$(which python)"
echo "[ENV] snaphu=$(which snaphu)"

########################################
# 2) 입력 H5 선택
########################################
REF=$(ls -1 /home/hyunjin/nas/nationalpark_SAR/CSK/20200712/CSKS4_*.h5 | head -n 1)
SEC=$(ls -1 /home/hyunjin/nas/nationalpark_SAR/CSK/20200713/CSKS2_*.h5 | head -n 1)

echo "[REF] $REF"
echo "[SEC] $SEC"
[ -f "$REF" ] || { echo "REF not found"; exit 1; }
[ -f "$SEC" ] || { echo "SEC not found"; exit 1; }

########################################
# (선택) 재실행 시 이전 산출물 삭제
########################################
# rm -rf interferogram geometry offsets coregisteredSlc reference_slc secondary_slc misreg *.log *.xml dem.crop* demLat_*.dem* export || true

########################################
# 3) stripmapApp.xml 생성 (성공했던 구조)
########################################
cat > stripmapApp.xml <<EOF
<stripmapApp>
  <component name="insar">
    <property name="sensor name">COSMO_SKYMED_SLC</property>

    <component name="reference">
      <property name="HDF5"><value>$REF</value></property>
      <property name="OUTPUT"><value>reference</value></property>
    </component>

    <component name="secondary">
      <property name="HDF5"><value>$SEC</value></property>
      <property name="OUTPUT"><value>secondary</value></property>
    </component>

    <property name="doUnwrap">False</property>
  </component>
</stripmapApp>
EOF

########################################
# 4) ISCE2 실행 (wrapped interferogram까지)
########################################
export HDF5_USE_FILE_LOCKING=FALSE
stripmapApp.py stripmapApp.xml 2>&1 | tee stripmapApp.log
echo "[OK] stripmapApp finished"

########################################
# 5) snaphu 언래핑 (pyps에서 수행)
########################################
cd "$BASE/interferogram"

# (A) width/length 읽기
WIDTH=$(python - <<'PY' | tr -d '[:space:]'
import xml.etree.ElementTree as ET
root=ET.parse("filt_topophase.flat.xml").getroot()
print(root.find(".//property[@name='width']/value").text)
PY
)
LENGTH=$(python - <<'PY' | tr -d '[:space:]'
import xml.etree.ElementTree as ET
root=ET.parse("filt_topophase.flat.xml").getroot()
print(root.find(".//property[@name='length']/value").text)
PY
)
echo "[INFO] WIDTH=$WIDTH LENGTH=$LENGTH"

# (B) snaphu 입력용 wrapped phase(float32) 생성
# filt_topophase.flat (complex64) -> angle -> filt_topophase.phase (float32)
python - <<'PY'
import numpy as np, xml.etree.ElementTree as ET, os
root=ET.parse("filt_topophase.flat.xml").getroot()
w=int(root.find(".//property[@name='width']/value").text)
l=int(root.find(".//property[@name='length']/value").text)
N=w*l

z=np.fromfile("filt_topophase.flat", dtype=np.complex64)
assert z.size==N, (z.size, N)

ph=np.angle(z).astype(np.float32)  # wrapped phase [-pi, pi]
ph.tofile("filt_topophase.phase")

print("[OK] wrote filt_topophase.phase (float32), bytes=", os.path.getsize("filt_topophase.phase"))
PY

# (C) snaphu config (실제 인식되는 옵션만)
cat > snaphu_float.conf <<'EOF'
INFILEFORMAT  FLOAT_DATA
OUTFILEFORMAT FLOAT_DATA
EOF

# (D) snaphu 실행: deformation mode + coherence 반영 (네가 성공한 조합)
# output: filt_topophase.unw.phase2 (float32), conncomp: uint8
snaphu -f snaphu_float.conf -d filt_topophase.phase "$WIDTH" \
  -c topophase.cor \
  -o filt_topophase.unw.phase2 \
  -g filt_topophase.unw.phase2.conncomp \
  --mcf -v

echo "[OK] snaphu finished"

# (E) 출력 크기/마스크 상태 sanity check
python - <<'PY'
import numpy as np, xml.etree.ElementTree as ET, os
root=ET.parse("filt_topophase.flat.xml").getroot()
w=int(root.find(".//property[@name='width']/value").text)
l=int(root.find(".//property[@name='length']/value").text)
N=w*l

unw=np.fromfile("filt_topophase.unw.phase2", dtype=np.float32)
cc =np.fromfile("filt_topophase.unw.phase2.conncomp", dtype=np.uint8)

print("[CHECK] expected N:", N)
print("[CHECK] unw size:", unw.size, "bytes:", os.path.getsize("filt_topophase.unw.phase2"), "expected bytes:", N*4)
print("[CHECK] cc  size:", cc.size,  "bytes:", os.path.getsize("filt_topophase.unw.phase2.conncomp"), "expected bytes:", N)

cc=cc.reshape((l,w))
vals, counts = np.unique(cc, return_counts=True)
print("[CHECK] conncomp unique:", vals[:10])
print("[CHECK] counts:", counts[:10])
print("[CHECK] zero_fraction:", float((cc==0).mean()))
print("[CHECK] unw min/max:", float(np.nanmin(unw)), float(np.nanmax(unw)))
PY

########################################
# 6) EXPORT 폴더 재생성 + (기존) GeoTIFF/PNG 생성
########################################
cd "$BASE"

OUT=export
rm -rf "$OUT"
mkdir -p "$OUT/tif" "$OUT/png/geo" "$OUT/png/rdr"

echo "=== [6-1] GeoTIFF (geo.vrt -> export/tif) ==="
for v in interferogram/*.geo.vrt geometry/*.geo.vrt; do
  [ -f "$v" ] || continue
  case "$v" in *full* ) continue;; esac

  base=$(basename "$v" .vrt)
  out="$OUT/tif/${base}.tif"
  echo "[TIF] $v -> $out"

  gdal_translate -of GTiff \
    -co TILED=YES -co COMPRESS=DEFLATE -co PREDICTOR=2 -co BIGTIFF=IF_SAFER \
    "$v" "$out" >/dev/null
done

echo "=== [6-2] PNG GEO (safe) ==="
python - <<'PY'
import os, glob, numpy as np, rasterio
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize

OUT="export"
os.makedirs(f"{OUT}/png/geo", exist_ok=True)
os.makedirs(f"{OUT}/tif", exist_ok=True)

def save_png(arr, outpng, cmap="gray", vmin=None, vmax=None, title="", label="Value"):
    plt.figure(figsize=(10,6))
    norm = Normalize(vmin, vmax) if (vmin is not None and vmax is not None) else None
    im = plt.imshow(arr, cmap=cmap, norm=norm)
    plt.colorbar(im, fraction=0.046, pad=0.04, label=label)
    plt.title(title)
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(outpng, dpi=200)
    plt.close()

def write_float_geotiff(out_tif, arr, ref_vrt):
    with rasterio.open(ref_vrt) as ref:
        profile = {
            "driver": "GTiff",
            "height": ref.height,
            "width": ref.width,
            "count": 1,
            "dtype": "float32",
            "crs": ref.crs,
            "transform": ref.transform,
            "tiled": True,
            "compress": "DEFLATE",
            "predictor": 2,
            "BIGTIFF": "IF_SAFER",
        }
    if os.path.exists(out_tif):
        os.remove(out_tif)
    with rasterio.open(out_tif, "w", **profile) as dst:
        dst.write(arr.astype(np.float32), 1)

# ---- (A) flat.geo : complex -> phase/amp ----
flat_pairs = [
    ("interferogram/topophase.flat.geo",      "interferogram/topophase.flat.geo.vrt"),
    ("interferogram/filt_topophase.flat.geo", "interferogram/filt_topophase.flat.geo.vrt"),
]
for bin_path, ref_vrt in flat_pairs:
    if not (os.path.exists(bin_path) and os.path.exists(ref_vrt)):
        continue
    with rasterio.open(ref_vrt) as ref:
        H, W = ref.height, ref.width
    data = np.fromfile(bin_path, dtype=np.complex64)
    if data.size != H*W:
        print(f"[SKIP] size mismatch: {bin_path} size={data.size} vs {H}x{W}")
        continue
    data = data.reshape((H, W))
    ph  = np.clip(np.angle(data).astype(np.float32), -np.pi, np.pi)
    amp = np.abs(data).astype(np.float32)
    base = os.path.basename(bin_path)

    ph_tif  = f"{OUT}/tif/{base}.phase.tif"
    amp_tif = f"{OUT}/tif/{base}.amp.tif"
    write_float_geotiff(ph_tif,  ph,  ref_vrt)
    write_float_geotiff(amp_tif, amp, ref_vrt)

    ph2 = np.nan_to_num(ph, nan=0.0)
    save_png(ph2, f"{OUT}/png/geo/{base}.phase.jet.png", "jet", -np.pi, np.pi, base+" phase", "Phase (rad)")

    finite = amp[np.isfinite(amp)]
    if finite.size:
        vmin, vmax = np.nanpercentile(finite, [2, 98])
        save_png(amp, f"{OUT}/png/geo/{base}.amp.gray.png", "gray", float(vmin), float(vmax), base+" amp", "Amplitude")

# ---- (B) 나머지 geo tif들 ----
for tif in sorted(glob.glob(f"{OUT}/tif/*.geo.tif")):
    name = os.path.basename(tif).replace(".tif","")
    lower = name.lower()
    if "flat.geo" in lower:
        continue
    with rasterio.open(tif) as ds:
        nb = ds.count
        nodata = ds.nodata
        for b in range(1, nb+1):
            arr = ds.read(b).astype(np.float32)
            if nodata is not None:
                arr = np.where(arr==nodata, np.nan, arr)
            finite = arr[np.isfinite(arr)]
            if finite.size == 0:
                continue
            suffix = f".b{b}" if nb > 1 else ""
            if "cor.geo" in lower:
                arr2 = np.clip(arr, 0.0, 1.0)
                save_png(arr2, f"{OUT}/png/geo/{name}{suffix}.coh.gray.png", "gray", 0.0, 1.0, f"{name}{suffix}", "Coherence (0-1)")
            else:
                vmin, vmax = np.nanpercentile(finite, [2, 98])
                save_png(arr, f"{OUT}/png/geo/{name}{suffix}.gray.png", "gray", float(vmin), float(vmax), f"{name}{suffix}", "Value")

print("DONE: export/png/geo")
PY

########################################
# 7) 언랩 PNG 생성 (RDR 기준, conncomp 마스크 적용)
########################################
echo "=== [7] PNG RDR (Unwrapped phase masked) ==="
cd "$BASE/interferogram"

python - <<'PY'
import numpy as np, xml.etree.ElementTree as ET
import matplotlib.pyplot as plt

root=ET.parse("filt_topophase.flat.xml").getroot()
w=int(root.find(".//property[@name='width']/value").text)
l=int(root.find(".//property[@name='length']/value").text)

unw=np.fromfile("filt_topophase.unw.phase2", dtype=np.float32).reshape((l,w))
cc =np.fromfile("filt_topophase.unw.phase2.conncomp", dtype=np.uint8).reshape((l,w))

# mask 적용
unw = np.where(cc==0, np.nan, unw)

# 다운샘플
step=max(1, min(l,w)//1500)
u=unw[::step,::step]

# 보기 좋은 범위
vmin, vmax = np.nanpercentile(u, [2, 98])

plt.figure(figsize=(10,6))
im=plt.imshow(u, cmap="jet", vmin=vmin, vmax=vmax)
plt.colorbar(im, fraction=0.046, pad=0.04, label="Unwrapped phase (rad)")
plt.title(f"CSK Unwrapped phase (masked) step={step} v=[{vmin:.2f},{vmax:.2f}]")
plt.axis("off")
plt.tight_layout()
plt.savefig("../export/png/rdr/unw_phase2_masked.png", dpi=200)
print("Wrote ../export/png/rdr/unw_phase2_masked.png")
PY

echo "=== DONE ALL ==="
cd "$BASE"
if command -v tree >/dev/null 2>&1; then
  tree export | head -n 200
else
  find export -maxdepth 3 -type f | sort | head -n 200
fi
