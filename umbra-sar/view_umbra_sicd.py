# 아나콘다 프롬프트에서 
# conda activate sarpy
# python 12_umbra\view_umbra_sicd.py

from pathlib import Path
from sarpy.io.complex.sicd import SICDReader
import numpy as np
import matplotlib.pyplot as plt


def get_attr(obj, *names, default=None):
    """Return first existing attribute among names."""
    for n in names:
        if hasattr(obj, n):
            return getattr(obj, n)
    return default


def view_umbra_sicd(sicd_path, tile_half=512):
    sicd_path = Path(sicd_path)
    print(f"\n=== Loading SICD ===\n{sicd_path}")

    if not sicd_path.is_file():
        raise FileNotFoundError(f"Not found: {sicd_path}")

    reader = SICDReader(str(sicd_path))
    sicd = reader.sicd_meta

    print("\n=== Basic Metadata ===")
    print("Collector         :", get_attr(sicd.CollectionInfo, "CollectorName", default="(unknown)"))
    print("Collect start     :", get_attr(sicd.Timeline, "CollectStart", default="(unknown)"))

    print("\n=== Radar / Geometry ===")
    print("Tx/Rx polarization :", get_attr(sicd.ImageFormation, "TxRcvPolarizationProc", default="(unknown)"))
    print("Side of track      :", get_attr(sicd.SCPCOA, "SideOfTrack", default="(unknown)"))

    # Umbra/SICD variants: IncidenceAng vs IncidenceAngle
    inc = get_attr(sicd.SCPCOA, "IncidenceAngle", "IncidenceAng", default="(missing)")
    print("Incidence angle    :", inc)

    print("\n=== Grid spacing ===")
    print("Row spacing (m)    :", get_attr(sicd.Grid.Row, "SS", default="(unknown)"))
    print("Col spacing (m)    :", get_attr(sicd.Grid.Col, "SS", default="(unknown)"))

    rows, cols = reader.data_size
    print("\nImage size (rows, cols):", rows, cols)

    sub = reader[
        rows//2 - tile_half : rows//2 + tile_half,
        cols//2 - tile_half : cols//2 + tile_half
    ]
    print("Sub image:", sub.shape, sub.dtype)

    amp = np.abs(sub)
    phs = np.angle(sub)

    print("Amplitude min/max :", float(amp.min()), float(amp.max()))
    print("Phase min/max     :", float(phs.min()), float(phs.max()))

    plt.figure(figsize=(14, 6))

    plt.subplot(1, 2, 1)
    plt.title("Amplitude (dB)")
    plt.imshow(20*np.log10(amp + 1e-6), cmap="gray")
    plt.colorbar(label="dB")
    plt.axis("off")

    plt.subplot(1, 2, 2)
    plt.title("Phase")
    plt.imshow(phs, cmap="twilight")
    plt.colorbar(label="rad")
    plt.axis("off")

    plt.suptitle(sicd_path.name)
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    sicd_path = r"<DATA_ROOT>\12_umbra\Erebus\2023-11-10_SICD.nitf"
    view_umbra_sicd(sicd_path)
