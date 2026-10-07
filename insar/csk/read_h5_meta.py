#!/usr/bin/env python3
import h5py
import numpy as np
import sys

# ==========================
# 입력 CSK HDF5 파일
# ==========================
p = "/home/hyunjin/nas/nationalpark_SAR/CSK/20200712/CSKS4_SCS_B_HI_01_HH_RA_SF_20200712212827_20200712212835.h5"
# p = "/home/hyunjin/nas/nationalpark_SAR/CSK/20200713/CSKS2_SCS_B_HI_01_HH_RA_SF_20200713212826_20200713212834.h5"

# ==========================
# 값 출력 보조 함수
# ==========================
def show(v):
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8")
        except Exception:
            return repr(v)

    if isinstance(v, np.ndarray):
        if v.size <= 20:
            return v.tolist()
        return f"ndarray(shape={v.shape}, dtype={v.dtype})"

    return v

# ==========================
# 메타데이터 덤프
# ==========================
with h5py.File(p, "r") as f:
    print("CSK FILE :", p)
    print("=" * 80)

    # ----------------------
    # ROOT
    # ----------------------
    print("\n[ROOT]")
    print("TOP KEYS :", list(f.keys()))
    print("ROOT ATTRS:", len(f.attrs))
    for k in sorted(f.attrs.keys()):
        print(" ", k, "=", show(f.attrs[k]))

    # ----------------------
    # GROUP / DATASET 순회
    # ----------------------
    def visit(name, obj):
        if isinstance(obj, h5py.Group):
            print(f"\n[GROUP] {name}")
        elif isinstance(obj, h5py.Dataset):
            print(f"\n[DATASET] {name}")
            try:
                print("  shape =", obj.shape, "dtype =", obj.dtype)
            except Exception as e:
                print("  shape/dtype unreadable:", e)

        # attrs만 출력 (데이터는 절대 안 읽음)
        for ak in sorted(obj.attrs.keys()):
            try:
                print(" ", ak, "=", show(obj.attrs[ak]))
            except Exception as e:
                print(" ", ak, "= <ERROR reading attr>", e)

    f.visititems(visit)

print("\n[DONE] CSK metadata dump completed safely.")

# 실행법
# PYTHONPATH= python /home/hyunjin/nas/nationalpark_SAR/code/read_h5_meta.py \
# > /home/hyunjin/nas/nationalpark_SAR/CSK/20200713/csk_20200713_metadata.txt