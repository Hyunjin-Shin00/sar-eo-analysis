import os, glob, subprocess
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize

try: import rasterio
except ImportError: rasterio = None

def say(msg): print(f"[VIZ] {msg}")

def run_gdal_translate(input_vrt, output_path, options=None):
    cmd = ["gdal_translate"]
    if options: cmd.extend(options)
    cmd.extend([input_vrt, output_path])
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

def save_png(arr, outpng, cmap="gray", vmin=None, vmax=None, title=""):
    plt.figure(figsize=(10,6))
    norm = Normalize(vmin, vmax) if (vmin is not None and vmax is not None) else None
    plt.imshow(arr, cmap=cmap, norm=norm)
    plt.colorbar(fraction=0.046, pad=0.04)
    plt.title(title)
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(outpng, dpi=200)
    plt.close()

def run_visualization(base_dir):
    if rasterio is None: say("WARN: rasterio missing. Python plots skipped.")
    
    out_dir = os.path.join(base_dir, "export")
    out_png_geo = os.path.join(out_dir, "png", "geo")
    out_png_rdr = os.path.join(out_dir, "png", "rdr")
    os.makedirs(out_png_geo, exist_ok=True)
    os.makedirs(out_png_rdr, exist_ok=True)

    say(f"Visualizing in: {base_dir}")

    # 1. Python Geo Plots (Phase/Amp)
    if rasterio:
        flat_pairs = [("interferogram/topophase.flat.geo", "interferogram/topophase.flat.geo.vrt"),
                      ("interferogram/filt_topophase.flat.geo", "interferogram/filt_topophase.flat.geo.vrt")]
        for bin_rel, vrt_rel in flat_pairs:
            bin_path = os.path.join(base_dir, bin_rel)
            vrt_path = os.path.join(base_dir, vrt_rel)
            if not (os.path.exists(bin_path) and os.path.exists(vrt_path)): continue

            with rasterio.open(vrt_path) as ref: H, W = ref.height, ref.width
            data = np.fromfile(bin_path, dtype=np.complex64).reshape((H, W))
            
            ph = np.clip(np.angle(data), -np.pi, np.pi)
            base = os.path.basename(bin_path)
            
            save_png(ph, os.path.join(out_png_geo, f"{base}.phase.gray.png"), "gray", -np.pi, np.pi, base)
            cmap = plt.get_cmap("jet"); cmap.set_bad("black")
            save_png(ph, os.path.join(out_png_geo, f"{base}.phase.jet.png"), cmap, -np.pi, np.pi, base)
            print(f"  [OK] {base}")

    # 2. RDR PNGs via GDAL
    for v in glob.glob(os.path.join(base_dir, "interferogram", "*.vrt")):
        if "full" in v or ".geo" in v: continue
        base = os.path.basename(v).replace(".vrt", "")
        out = os.path.join(out_png_rdr, f"{base}.gray.png")
        run_gdal_translate(v, out, ["-of", "PNG", "-ot", "Byte", "-scale"])
        print(f"  [PNG] {base}")

    say("DONE.")