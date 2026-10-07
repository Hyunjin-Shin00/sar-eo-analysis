import h5py, numpy as np, sys, os

def ensure_bytes(v):
    if isinstance(v, bytes): return v
    if isinstance(v, str): return v.encode('utf-8')
    return np.bytes_(str(v))

def create_sbi_from_iq(gS01, dsIQ, chunk_rows=2048):
    L, C, _ = dsIQ.shape
    # 새 데이터셋 준비
    if "SBI_new" in gS01: del gS01["SBI_new"]
    sbi = gS01.create_dataset(
        "SBI_new",
        shape=(L, C, 2),
        dtype=np.int16,
        chunks=(min(chunk_rows, L), min(1024, C), 2),
        compression="gzip"
    )
    # IQ -> SBI(int16)
    for r0 in range(0, L, chunk_rows):
        r1 = min(L, r0 + chunk_rows)
        block = dsIQ[r0:r1, :, :]                     # float/int, (r, c, 2)
        # 그대로 int16로 캐스팅(원래가 int16이면 손실 없음)
        sbi[r0:r1, :, 0] = block[..., 0].astype(np.int16)
        sbi[r0:r1, :, 1] = block[..., 1].astype(np.int16)
    return sbi

def create_sbi_from_2d(gS01, ds2d, interleave="rows", chunk_rows=2048):
    H, W = ds2d.shape
    if interleave == "rows":
        if H % 2 != 0:
            raise RuntimeError(f"SBI(rows) 높이 짝수 아님: {H}")
        L, C = H // 2, W
        if "SBI_new" in gS01: del gS01["SBI_new"]
        sbi = gS01.create_dataset(
            "SBI_new",
            shape=(L, C, 2),
            dtype=np.int16,
            chunks=(min(chunk_rows, L), min(1024, C), 2),
            compression="gzip"
        )
        # 2행 단위(I/Q)
        step = max(2, (chunk_rows // 2) * 2)
        for r0 in range(0, H, step):
            r1 = min(H, r0 + step)
            blk = ds2d[r0:r1, :]              # (rr, C)
            i_part = blk[0::2, :].astype(np.int16)
            q_part = blk[1::2, :].astype(np.int16)
            out_r0 = r0 // 2
            out_r1 = out_r0 + i_part.shape[0]
            sbi[out_r0:out_r1, :, 0] = i_part
            sbi[out_r0:out_r1, :, 1] = q_part
        return sbi

    else:  # interleave == "cols"
        if W % 2 != 0:
            raise RuntimeError(f"SBI(cols) 너비 짝수 아님: {W}")
        L, C = H, W // 2
        if "SBI_new" in gS01: del gS01["SBI_new"]
        sbi = gS01.create_dataset(
            "SBI_new",
            shape=(L, C, 2),
            dtype=np.int16,
            chunks=(min(chunk_rows, L), min(1024, C), 2),
            compression="gzip"
        )
        for r0 in range(0, H, chunk_rows):
            r1 = min(H, r0 + chunk_rows)
            blk = ds2d[r0:r1, :]              # (rr, 2C)
            sbi[r0:r1, :, 0] = blk[:, 0::2].astype(np.int16)
            sbi[r0:r1, :, 1] = blk[:, 1::2].astype(np.int16)
        return sbi

def copy_sbi_attrs(src, dst):
    # 최소한 CSK 리더가 헷갈리지 않게 컬럼/라인 순서 등 보강(있으면 유지)
    for k, v in src.attrs.items():
        try:
            dst.attrs[k] = v
        except Exception:
            dst.attrs[k] = ensure_bytes(v)
    # 합리적 기본값
    if "Columns Order" not in dst.attrs:
        dst.attrs["Columns Order"] = ensure_bytes(src.attrs.get("Columns Order", "NEAR-FAR"))
    if "Lines Order" not in dst.attrs:
        dst.attrs["Lines Order"] = ensure_bytes(src.attrs.get("Lines Order", "EARLY-LATE"))
    if "Sample Type" not in dst.attrs:
        dst.attrs["Sample Type"] = ensure_bytes("INT16")
    if "Polarisation" in src.parent.attrs and "Polarisation" not in dst.parent.attrs:
        dst.parent.attrs["Polarisation"] = src.parent.attrs["Polarisation"]

def main(path, prefer_rows=True):
    interleave_guess = "rows" if prefer_rows else "cols"
    with h5py.File(path, "r+") as f:
        if "S01" not in f:
            print(f"[ERR] {path}: /S01 없음"); return 1
        g = f["S01"]

        dsIQ = g.get("IQ", None)
        dsSBI = g.get("SBI", None)

        # 상황 1) IQ 정상이면 그걸 기준으로 SBI 재생성
        if (dsIQ is not None) and (dsIQ.ndim == 3) and (dsIQ.shape[-1] == 2):
            print("[INFO] Using /S01/IQ → rebuild /S01/SBI (L,C,2)")
            sbi_new = create_sbi_from_iq(g, dsIQ)
            if dsSBI is not None:
                src_for_attrs = dsSBI
                del g["SBI"]
            else:
                src_for_attrs = dsIQ
            g.move("SBI_new", "SBI")
            copy_sbi_attrs(src_for_attrs, g["SBI"])
            print("[OK] SBI rebuilt from IQ:", g["SBI"].shape, g["SBI"].dtype)
            return 0

        # 상황 2) SBI가 있음
        if dsSBI is not None:
            if dsSBI.ndim == 3:
                if dsSBI.shape[-1] == 2 and dsSBI.shape[0] > 0 and dsSBI.shape[1] > 0:
                    print("[OK] /S01/SBI already (L,C,2) → 패치 불필요")
                    return 0
                else:
                    print(f"[WARN] /S01/SBI 3D but last dim={dsSBI.shape[-1]} → 재작성")
                    # 삭제 후 재작성 시도(IQ 있으면 IQ로, 없으면 2D 해석 필요)
                    del g["SBI"]
                    # IQ가 없다면 여기까지 도달하지 않음(위에서 처리)
                    print("[ERR] IQ 없음, 2D 원본도 없음 → 재작성 불가")
                    return 2

            elif dsSBI.ndim == 2:
                H, W = dsSBI.shape
                # 행 인터리브로 먼저 시도
                try:
                    print(f"[INFO] Rebuild 2D SBI as 3D using interleave={interleave_guess}")
                    sbi_new = create_sbi_from_2d(g, dsSBI, interleave_guess)
                except Exception as e:
                    # 반대 가정으로 재시도
                    alt = "cols" if interleave_guess == "rows" else "rows"
                    print(f"[WARN] rows 가정 실패({e}) → {alt}로 재시도")
                    sbi_new = create_sbi_from_2d(g, dsSBI, alt)

                # 교체
                src_for_attrs = dsSBI
                del g["SBI"]
                g.move("SBI_new", "SBI")
                copy_sbi_attrs(src_for_attrs, g["SBI"])
                print("[OK] SBI rebuilt from 2D:", g["SBI"].shape, g["SBI"].dtype)
                return 0

        print("[ERR] /S01/IQ 또는 /S01/SBI를 찾지 못했습니다.")
        return 3

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python fix_sbi_layout.py <converted.h5>")
        sys.exit(1)
    sys.exit(main(sys.argv[1]))
