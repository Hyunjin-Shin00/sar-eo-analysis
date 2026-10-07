import h5py
import numpy as np

p="/tmp/n2.h5"        # N2 데이터 

def show(v):
    if isinstance(v, (bytes, bytearray)):
        try: return v.decode("utf-8")
        except: return repr(v)
    if isinstance(v, np.ndarray):
        if v.size <= 20:
            return v.tolist()
        return f"ndarray(shape={v.shape}, dtype={v.dtype})"
    return v

with h5py.File(p,"r") as f:
    print("TOP KEYS:", list(f.keys()))
    print("ROOT ATTRS:", len(f.attrs))
    for k in sorted(f.attrs.keys()):
        print("  ", k, "=", show(f.attrs[k]))

    def visit(name, obj):
        kind = "GROUP" if isinstance(obj, h5py.Group) else "DATASET"
        print(f"\n[{kind}] {name}")
        if kind=="DATASET":
            print("  shape=", obj.shape, "dtype=", obj.dtype)
        for ak in sorted(obj.attrs.keys()):
            print("  ", ak, "=", show(obj.attrs[ak]))

    f.visititems(visit)

# 실행법
# conda run -n isce2 python /tmp/read_n2_meta.py \
# > /home/hyunjin/nas/nationalpark_SAR/SLC/n2_metadata.txt

