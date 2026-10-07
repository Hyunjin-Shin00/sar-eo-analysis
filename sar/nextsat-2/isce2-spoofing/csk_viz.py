# csk_viz_csk.py — CSK InSAR 결과 시각화 모듈
# bash 스크립트(isce2_snaphu_환경에서_언래핑까지_한번에_성공.txt)의
# export 단계를 Python 모듈로 구조화한 것

import os, glob, subprocess
import numpy as np
import xml.etree.ElementTree as ET
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize

try:
    import rasterio
except ImportError:
    rasterio = None


def say(msg):
    print(f"[CSK_VIZ] {msg}")


def save_png(arr, outpng, cmap="gray", vmin=None, vmax=None, title="", label="Value"):
    plt.figure(figsize=(10, 6))
    norm = Normalize(vmin, vmax) if (vmin is not None and vmax is not None) else None
    im = plt.imshow(arr, cmap=cmap, norm=norm)
    plt.colorbar(im, fraction=0.046, pad=0.04, label=label)
    plt.title(title)
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(outpng, dpi=200)
    plt.close()


def write_float_geotiff(out_tif, arr, ref_vrt):
    """rasterio로 float32 GeoTIFF 생성"""
    if rasterio is None:
        say("WARN: rasterio 없음 — GeoTIFF 생성 스킵")
        return
    with rasterio.open(ref_vrt) as ref:
        profile = {
            "driver": "GTiff",
            "height": ref.height, "width": ref.width,
            "count": 1, "dtype": "float32",
            "crs": ref.crs, "transform": ref.transform,
            "tiled": True, "compress": "DEFLATE",
            "predictor": 2, "BIGTIFF": "IF_SAFER",
        }
    if os.path.exists(out_tif):
        os.remove(out_tif)
    with rasterio.open(out_tif, "w", **profile) as dst:
        dst.write(arr.astype(np.float32), 1)


# ─────────────────────────────────────────────
# 0. 단계별 중간 산출물 생성 (ISCE2가 자동으로 안 만들어주는 것들)
# ─────────────────────────────────────────────

def _read_isce_xml_dims(xml_path):
    """ISCE XML에서 width, length 읽기"""
    root = ET.parse(xml_path).getroot()
    w = int(root.find(".//property[@name='width']/value").text.strip())
    l = int(root.find(".//property[@name='length']/value").text.strip())
    return w, l


def _load_complex_slc(slc_path, xml_path):
    """SLC 바이너리를 complex64로 읽기"""
    w, l = _read_isce_xml_dims(xml_path)
    data = np.fromfile(slc_path, dtype=np.complex64)
    if data.size != w * l:
        say(f"WARN: SLC size mismatch {slc_path}: {data.size} vs {w}x{l}")
        return None, w, l
    return data.reshape((l, w)), w, l


def generate_multilook(base_dir, out_dir, rlooks=4, alooks=4):
    """
    Reference / Secondary SLC에 multi-look 적용 (amplitude)
    - rlooks: range 방향 look 수
    - alooks: azimuth 방향 look 수
    """
    say(f"Multi-look 생성 (range={rlooks}, azimuth={alooks})")

    slc_pairs = [
        ("reference_slc/reference.slc", "reference_slc/reference.slc.xml", "reference_multilook"),
        ("secondary_slc/secondary.slc", "secondary_slc/secondary.slc.xml", "secondary_multilook"),
    ]
    # coregistered secondary도 시도
    coreg_candidates = [
        "coregisteredSlc/refined_coreg.slc",
        "coregisteredSlc/coarse_coreg.slc",
    ]
    for c in coreg_candidates:
        cpath = os.path.join(base_dir, c)
        cxml = cpath + ".xml"
        if os.path.exists(cpath) and os.path.exists(cxml):
            slc_pairs.append((c, c + ".xml", "secondary_coreg_multilook"))
            break

    for slc_rel, xml_rel, out_name in slc_pairs:
        slc_path = os.path.join(base_dir, slc_rel)
        xml_path = os.path.join(base_dir, xml_rel)
        if not (os.path.exists(slc_path) and os.path.exists(xml_path)):
            say(f"  SKIP (파일 없음): {slc_rel}")
            continue

        slc, w, l = _load_complex_slc(slc_path, xml_path)
        if slc is None:
            continue

        amp = np.abs(slc)

        # multi-look: azimuth(행) x range(열) 평균
        nl = (l // alooks) * alooks
        nw = (w // rlooks) * rlooks
        amp_crop = amp[:nl, :nw]
        ml = amp_crop.reshape(nl // alooks, alooks, nw // rlooks, rlooks).mean(axis=(1, 3))

        out_png = os.path.join(out_dir, f"{out_name}_{alooks}x{rlooks}.png")
        finite = ml[np.isfinite(ml)]
        if finite.size:
            vmin, vmax = np.nanpercentile(finite, [2, 98])
            save_png(ml, out_png, "gray", float(vmin), float(vmax),
                     f"{out_name} ({alooks}az x {rlooks}rg)", "Amplitude")
            say(f"  [OK] {out_png}")


def generate_raw_interferogram(base_dir, out_dir):
    """
    Raw interferogram (잡음 전부 포함, flat-earth/topo 제거 없음)
    = ref × conj(sec_coreg), 4×4 multilook 후 저장 (메모리 절약)
    """
    say("Raw interferogram 생성 (모든 잡음 포함)")

    ref_slc = os.path.join(base_dir, "reference_slc/reference.slc")
    ref_xml = ref_slc + ".xml"

    sec_slc = None
    for cand in ["coregisteredSlc/refined_coreg.slc", "coregisteredSlc/coarse_coreg.slc"]:
        p = os.path.join(base_dir, cand)
        if os.path.exists(p) and os.path.exists(p + ".xml"):
            sec_slc = p
            break

    if not sec_slc:
        say("  SKIP: coregistered secondary SLC 없음")
        return
    if not (os.path.exists(ref_slc) and os.path.exists(ref_xml)):
        say("  SKIP: reference SLC 없음")
        return

    w,  l  = _read_isce_xml_dims(ref_xml)
    w2, l2 = _read_isce_xml_dims(sec_slc + ".xml")
    min_l, min_w = min(l, l2), min(w, w2)

    rlooks, alooks = 4, 4
    nl = (min_l // alooks) * alooks
    nw = (min_w // rlooks) * rlooks
    out_l, out_w = nl // alooks, nw // rlooks

    CHUNK = 512 * alooks  # alooks의 배수로 청크 크기 설정
    phase_ml = np.zeros((out_l, out_w), dtype=np.float32)
    out_row = 0

    with open(ref_slc, "rb") as rf, open(sec_slc, "rb") as sf:
        for start in range(0, nl, CHUNK):
            end = min(start + CHUNK, nl)
            n = (end - start) // alooks * alooks  # alooks 배수로 맞춤
            if n == 0:
                continue
            nbytes = n * min_w * 8
            rf.seek(start * min_w * 8)
            sf.seek(start * min_w * 8)
            rc = np.frombuffer(rf.read(nbytes), dtype=np.complex64).reshape(n, min_w)[:, :nw]
            sc = np.frombuffer(sf.read(nbytes), dtype=np.complex64).reshape(n, min_w)[:, :nw]
            ifg = rc * np.conj(sc)
            # complex multilook → 위상
            ml = ifg.reshape(n // alooks, alooks, out_w, rlooks).mean(axis=(1, 3))
            rows = n // alooks
            phase_ml[out_row:out_row + rows] = np.angle(ml).astype(np.float32)
            out_row += rows

    out_png = os.path.join(out_dir, "raw_interferogram_phase.png")
    cmap = plt.get_cmap("jet").copy()
    cmap.set_bad(color="black")
    save_png(np.nan_to_num(phase_ml[:out_row]), out_png, cmap, -np.pi, np.pi,
             "Raw interferogram (all noise included)", "Phase (rad)")
    say(f"  [OK] {out_png}")


def generate_flat_earth_only_interferogram(base_dir, out_dir):
    """
    Flat-earth만 제거한 interferogram (지형 위상은 남아있음)
    = topophase.flat의 위상 + topo phase를 다시 더해줌
    
    ISCE2 stripmapApp에서:
    - topophase.flat = raw - flat_earth - topo_phase
    - geometry/topophase.mph (또는 topo phase를 geometry에서 복원)
    
    실제로는: topophase.flat에 topo phase를 다시 더하면
    flat-earth만 제거된 상태가 됨.
    
    topo phase = 4π/λ × B_perp × h / (R × sin(θ))
    이걸 직접 계산하기보다는 ISCE2의 중간 산출물을 활용함.
    """
    say("Flat-earth-only interferogram 생성 (topo 미제거)")

    # 방법: topophase.flat은 flat+topo 둘 다 제거된 상태
    # ISCE2 geometry 폴더에 los.rdr.full (look angle)과 z.rdr.full (height) 등이 있지만
    # topo phase를 정확히 복원하려면 baseline 정보가 필요
    #
    # 더 현실적인 방법: ISCE2 내부에서 만든 topophase (지형위상)을
    # topophase.flat에 다시 더하는 것
    #
    # ISCE2는 interferogram 생성 시 내부적으로:
    #   1. raw_ifg = ref × conj(sec)
    #   2. flat_ifg = raw_ifg × exp(-j × flat_earth_phase)  → flat earth 제거
    #   3. topophase.flat = flat_ifg × exp(-j × topo_phase)  → topo 제거
    #
    # 따라서: flat_ifg = topophase.flat × exp(+j × topo_phase)
    #
    # topo phase는 직접 파일로 저장되지 않지만,
    # raw_ifg과 topophase.flat의 차이로 구할 수 있음:
    #   raw_phase = angle(raw_ifg)
    #   final_phase = angle(topophase.flat)
    #   removed_phase = raw_phase - final_phase (= flat_earth + topo)
    #
    # 가장 깔끔한 방법: raw와 topophase.flat이 둘 다 있으면
    # flat-earth-only = raw_phase - topo_phase
    # 그런데 topo_phase를 분리하기 어려우므로
    # 다른 접근: ISCE2의 looks.py를 쓰거나, 
    # raw_interferogram에서 flat-earth phase만 빼는 방식

    # 현실적 접근: raw interferogram과 topophase.flat이 둘 다 있으면
    # 1) raw_ifg 위상 구하기
    # 2) topophase.flat 위상 구하기  
    # 3) (raw - topophase.flat)의 위상 = flat_earth + topo
    # 4) flat_earth_only = raw_phase - (위 결과에서 flat_earth만)
    # → 하지만 flat_earth와 topo를 분리 불가
    #
    # 따라서 가장 정확한 방법:
    # ISCE2가 topo phase를 계산할 때 쓴 geometry 정보를 역이용
    # geometry/z.rdr (DEM height in radar coords)에서 topo phase 복원

    ifg_dir = os.path.join(base_dir, "interferogram")
    flat_path = os.path.join(ifg_dir, "topophase.flat")
    flat_xml = flat_path + ".xml"

    if not (os.path.exists(flat_path) and os.path.exists(flat_xml)):
        say("  SKIP: topophase.flat 없음")
        return

    # raw interferogram이 이미 계산됐다면 활용
    ref_slc = os.path.join(base_dir, "reference_slc/reference.slc")
    ref_xml = ref_slc + ".xml"
    sec_slc = None
    for cand in ["coregisteredSlc/refined_coreg.slc", "coregisteredSlc/coarse_coreg.slc"]:
        p = os.path.join(base_dir, cand)
        if os.path.exists(p):
            sec_slc = p
            break

    if not sec_slc or not os.path.exists(ref_slc):
        say("  SKIP: SLC 파일 없음 → flat-earth-only 생성 불가")
        return

    # topophase.flat은 ISCE2가 내부 multilook 적용 후의 해상도
    # SLC는 풀 해상도 → multilook 배수를 맞춰야 비교 가능
    w_f, l_f = _read_isce_xml_dims(flat_xml)
    w2, l2   = _read_isce_xml_dims(sec_slc + ".xml")
    w_r, l_r = _read_isce_xml_dims(ref_xml)

    slc_l = min(l_r, l2)  # SLC 실제 라인 수
    slc_w = min(w_r, w2)  # SLC 실제 샘플 수

    # SLC → flat 해상도 비율로 multilook 배수 계산
    alooks = slc_l // l_f
    rlooks = slc_w // w_f

    # alooks/rlooks 배수에 맞게 SLC 라인/샘플 수 자르기
    nl = l_f * alooks
    nw = w_f * rlooks

    flat_data = np.fromfile(flat_path, dtype=np.complex64).reshape((l_f, w_f))

    # raw interferogram을 청크 단위로 multilook (SLC 실제 폭으로 읽기)
    CHUNK = max(1, 256 // alooks) * alooks
    removed_ml = np.zeros((l_f, w_f), dtype=np.complex64)
    out_row = 0

    with open(ref_slc, "rb") as rf, open(sec_slc, "rb") as sf:
        for start in range(0, nl, CHUNK):
            end = min(start + CHUNK, nl)
            n = (end - start) // alooks * alooks
            if n == 0:
                continue
            rf.seek(start * slc_w * 8)
            sf.seek(start * slc_w * 8)
            nbytes = n * slc_w * 8
            rc = np.frombuffer(rf.read(nbytes), dtype=np.complex64).reshape(n, slc_w)[:, :nw]
            sc = np.frombuffer(sf.read(nbytes), dtype=np.complex64).reshape(n, slc_w)[:, :nw]
            # raw interferogram multilook → flat 해상도에 맞춤
            rows = n // alooks
            raw_ml = (rc * np.conj(sc)).reshape(rows, alooks, w_f, rlooks).mean(axis=(1, 3))
            # removed = raw_ml * conj(flat) → angle = flat_earth + topo phase
            removed_ml[out_row:out_row + rows] = raw_ml * np.conj(flat_data[out_row:out_row + rows])
            out_row += rows

    removed_phase = np.angle(removed_ml[:out_row]).astype(np.float32)

    # flat-earth-only interferogram = raw에서 flat-earth만 제거
    # = topophase.flat에 topo를 다시 더한 것
    # = flat_data × exp(j × topo_phase)
    # topo_phase를 직접 분리할 수 없으므로,
    # 대안: ISCE2의 topo phase를 geometry에서 계산
    #
    # 더 간단한 접근: "지형 제거 전" = topophase.flat + topo_phase인데
    # topo_phase를 정확히 아는 방법이 없으므로
    # 가장 현실적인 산출물 3개는:
    #   (a) raw interferogram (위에서 이미 생성)
    #   (b) topophase.flat (이미 있음 — flat+topo 제거)  
    #   (c) "flat-earth만 제거" ≈ 어려움
    #
    # 실제로 ISCE2에서 접근 가능한 분리:
    # geometry/topophase.mph가 있으면 topo phase를 복원 가능
    # topophase.mph = complex exponential of topo phase

    # topophase.mph 확인
    mph_path = os.path.join(ifg_dir, "topophase.mph")
    if os.path.exists(mph_path):
        say("  topophase.mph 발견 → flat-earth-only 복원 가능")
        mph = np.fromfile(mph_path, dtype=np.complex64)
        if mph.size == l_f * w_f:
            mph = mph.reshape((l_f, w_f))[:min_l, :min_w]
        elif mph.size == min_l * min_w:
            mph = mph.reshape((min_l, min_w))
        else:
            say(f"  WARN: mph size mismatch: {mph.size}")
            mph = None

        if mph is not None:
            # flat_earth_only = topophase.flat × conj(mph 정규화)
            # topophase.flat = flat_earth_removed × exp(-j×topo)
            # flat_earth_removed = topophase.flat × exp(+j×topo)
            # = topophase.flat × mph (mph는 exp(j×topo)의 단위 복소수)
            mph_unit = mph / (np.abs(mph) + 1e-30)  # 단위 복소수화
            flat_earth_only = flat_data * mph_unit
            phase_feo = np.angle(flat_earth_only).astype(np.float32)

            out_png = os.path.join(out_dir, "interferogram_flat_earth_removed_only.png")
            cmap = plt.get_cmap("jet").copy()
            cmap.set_bad(color="black")
            save_png(np.nan_to_num(phase_feo), out_png, cmap, -np.pi, np.pi,
                     "Flat-earth removed (topo remains)", "Phase (rad)")
            say(f"  [OK] {out_png}")
            return

    # topophase.mph가 없으면 근사 방법 사용
    # geometry/z.rdr (full 또는 crop)에서 DEM 높이를 읽어 topo phase 근사 계산은
    # baseline 정보가 필요해서 복잡함.
    # 현실적 대안: raw_phase에서 topophase.flat.phase를 빼면
    # "제거된 위상 전체(flat+topo)"를 볼 수 있음
    say("  topophase.mph 없음 → 제거된 위상(flat+topo) 합산 시각화로 대체")

    out_png = os.path.join(out_dir, "removed_phase_flat_plus_topo.png")
    cmap = plt.get_cmap("hsv").copy()
    save_png(np.nan_to_num(removed_phase[:out_row]), out_png, cmap, -np.pi, np.pi,
             "Removed phase (flat-earth + topo)", "Phase (rad)")
    say(f"  [OK] {out_png}")


# ─────────────────────────────────────────────
# 1. GeoTIFF export (geo.vrt → tif)
# ─────────────────────────────────────────────
def export_geotiffs(base_dir, out_tif_dir):
    say("GeoTIFF export 시작")
    count = 0
    for subdir in ["interferogram", "geometry"]:
        pattern = os.path.join(base_dir, subdir, "*.geo.vrt")
        for v in sorted(glob.glob(pattern)):
            if "full" in v:
                continue
            base = os.path.basename(v).replace(".vrt", "")
            out = os.path.join(out_tif_dir, f"{base}.tif")
            cmd = [
                "gdal_translate", "-of", "GTiff",
                "-co", "TILED=YES", "-co", "COMPRESS=DEFLATE",
                "-co", "PREDICTOR=2", "-co", "BIGTIFF=IF_SAFER",
                v, out,
            ]
            ret = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if ret.returncode != 0:
                say(f"WARN: gdal_translate 실패 — {v}")
            else:
                count += 1
    say(f"GeoTIFF {count}개 생성 완료")


# ─────────────────────────────────────────────
# 2. GEO PNG (complex flat → phase/amp + coherence 등)
# ─────────────────────────────────────────────
def export_geo_png(base_dir, out_tif_dir, out_png_geo):
    if rasterio is None:
        say("WARN: rasterio 없음 — GEO PNG 스킵")
        return

    say("GEO PNG 생성 시작")

    # (A) complex flat.geo → phase/amp GeoTIFF + PNG
    flat_pairs = [
        ("interferogram/topophase.flat.geo", "interferogram/topophase.flat.geo.vrt"),
        ("interferogram/filt_topophase.flat.geo", "interferogram/filt_topophase.flat.geo.vrt"),
    ]
    for bin_rel, vrt_rel in flat_pairs:
        bin_path = os.path.join(base_dir, bin_rel)
        vrt_path = os.path.join(base_dir, vrt_rel)
        if not (os.path.exists(bin_path) and os.path.exists(vrt_path)):
            continue

        with rasterio.open(vrt_path) as ref:
            H, W = ref.height, ref.width

        data = np.fromfile(bin_path, dtype=np.complex64)
        if data.size != H * W:
            say(f"SKIP size mismatch: {bin_rel}")
            continue
        data = data.reshape((H, W))
        ph = np.clip(np.angle(data).astype(np.float32), -np.pi, np.pi)
        amp = np.abs(data).astype(np.float32)
        base = os.path.basename(bin_path)

        # GeoTIFF
        write_float_geotiff(os.path.join(out_tif_dir, f"{base}.phase.tif"), ph, vrt_path)
        write_float_geotiff(os.path.join(out_tif_dir, f"{base}.amp.tif"), amp, vrt_path)

        # PNG — phase (gray + jet)
        ph2 = np.nan_to_num(ph, nan=0.0)
        save_png(ph2, os.path.join(out_png_geo, f"{base}.phase.gray.png"),
                 "gray", -np.pi, np.pi, f"{base} phase", "Phase (rad)")
        cmap_jet = plt.get_cmap("jet").copy()
        cmap_jet.set_bad(color="black")
        save_png(ph2, os.path.join(out_png_geo, f"{base}.phase.jet.png"),
                 cmap_jet, -np.pi, np.pi, f"{base} phase", "Phase (rad)")

        # PNG — amplitude
        finite = amp[np.isfinite(amp)]
        if finite.size:
            vmin, vmax = np.nanpercentile(finite, [2, 98])
            save_png(amp, os.path.join(out_png_geo, f"{base}.amp.gray.png"),
                     "gray", float(vmin), float(vmax), f"{base} amp", "Amplitude")
        say(f"  [OK] GEO flat: {base}")

    # (B) 나머지 geo tif (coherence 등)
    for tif in sorted(glob.glob(os.path.join(out_tif_dir, "*.geo.tif"))):
        name = os.path.basename(tif).replace(".tif", "")
        if "flat.geo" in name.lower():
            continue
        with rasterio.open(tif) as ds:
            for b in range(1, ds.count + 1):
                arr = ds.read(b).astype(np.float32)
                if ds.nodata is not None:
                    arr = np.where(arr == ds.nodata, np.nan, arr)
                finite = arr[np.isfinite(arr)]
                if finite.size == 0:
                    continue
                suffix = f".b{b}" if ds.count > 1 else ""
                if "cor.geo" in name.lower():
                    save_png(np.clip(arr, 0, 1),
                             os.path.join(out_png_geo, f"{name}{suffix}.coh.gray.png"),
                             "gray", 0.0, 1.0, f"{name}{suffix}", "Coherence (0-1)")
                else:
                    vmin, vmax = np.nanpercentile(finite, [2, 98])
                    save_png(arr,
                             os.path.join(out_png_geo, f"{name}{suffix}.gray.png"),
                             "gray", float(vmin), float(vmax), f"{name}{suffix}", "Value")

    say("GEO PNG 완료")


# ─────────────────────────────────────────────
# 3. RDR PNG (VRT → gdal + complex flat → phase/amp)
# ─────────────────────────────────────────────
def export_rdr_png(base_dir, out_png_rdr):
    say("RDR PNG 생성 시작")

    # (A) VRT → Byte PNG via gdal
    for subdir in ["interferogram", "geometry", "offsets"]:
        pattern = os.path.join(base_dir, subdir, "*.vrt")
        for v in sorted(glob.glob(pattern)):
            bn = os.path.basename(v)
            if "full" in bn or ".geo.vrt" in bn:
                continue
            if "topophase.flat.vrt" in bn or "filt_topophase.flat.vrt" in bn:
                continue
            base = bn.replace(".vrt", "")
            out = os.path.join(out_png_rdr, f"{base}.gray.png")
            subprocess.run(
                ["gdal_translate", "-of", "PNG", "-ot", "Byte", "-scale", v, out],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )

    # (B) complex flat → phase/amp PNG
    vrt_ref = os.path.join(base_dir, "interferogram", "topophase.flat.vrt")
    if rasterio and os.path.exists(vrt_ref):
        with rasterio.open(vrt_ref) as ds:
            W, H = ds.width, ds.height

        targets = [
            os.path.join(base_dir, "interferogram", "topophase.flat"),
            os.path.join(base_dir, "interferogram", "filt_topophase.flat"),
        ]
        for fpath in targets:
            if not os.path.exists(fpath):
                continue
            data = np.fromfile(fpath, dtype=np.complex64)
            if data.size != W * H:
                continue
            data = data.reshape((H, W))
            ph = np.clip(np.angle(data).astype(np.float32), -np.pi, np.pi)
            amp = np.abs(data).astype(np.float32)
            b = os.path.basename(fpath)
            ph2 = np.nan_to_num(ph, nan=0.0)

            save_png(ph2, os.path.join(out_png_rdr, f"{b}.phase.gray.png"),
                     "gray", -np.pi, np.pi, b, "Phase (rad)")
            cmap_jet = plt.get_cmap("jet").copy()
            cmap_jet.set_bad(color="black")
            save_png(ph2, os.path.join(out_png_rdr, f"{b}.phase.jet.png"),
                     cmap_jet, -np.pi, np.pi, b, "Phase (rad)")

            finite = amp[np.isfinite(amp)]
            if finite.size:
                vmin, vmax = np.nanpercentile(finite, [2, 98])
                save_png(amp, os.path.join(out_png_rdr, f"{b}.amp.gray.png"),
                         "gray", float(vmin), float(vmax), b, "Amplitude")

    say("RDR PNG 완료")


# ─────────────────────────────────────────────
# 4. Unwrapped phase 시각화
# ─────────────────────────────────────────────
def export_unwrap_png(ifg_dir):
    """unwrapped phase PNG + wrapped vs unwrapped 비교 PNG 생성"""
    unw_file = os.path.join(ifg_dir, "filt_topophase.unw.phase2")
    cc_file = os.path.join(ifg_dir, "filt_topophase.unw.phase2.conncomp")
    xml_file = os.path.join(ifg_dir, "filt_topophase.flat.xml")

    if not all(os.path.exists(f) for f in [unw_file, cc_file, xml_file]):
        say("unwrap 산출물이 없어서 시각화 스킵")
        return

    root = ET.parse(xml_file).getroot()
    w = int(root.find(".//property[@name='width']/value").text.strip())
    l = int(root.find(".//property[@name='length']/value").text.strip())

    unw = np.fromfile(unw_file, dtype=np.float32).reshape((l, w))
    cc = np.fromfile(cc_file, dtype=np.uint8).reshape((l, w))
    mask = (cc == 0)
    unw_m = np.where(mask, np.nan, unw)

    step = max(1, min(l, w) // 1500)
    u = unw_m[::step, ::step]
    vmin, vmax = np.nanpercentile(u, [2, 98])

    # (A) unwrapped only
    out1 = os.path.join(ifg_dir, "unw_phase2_masked.png")
    plt.figure(figsize=(10, 6))
    im = plt.imshow(u, cmap="jet", vmin=vmin, vmax=vmax)
    plt.colorbar(im, fraction=0.046, pad=0.04, label="Unwrapped phase (rad)")
    plt.title(f"UNW (masked) step={step} v=[{vmin:.2f},{vmax:.2f}]")
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(out1, dpi=200)
    plt.close()
    say(f"  [OK] {out1}")

    # (B) wrapped vs unwrapped 비교
    flat_file = os.path.join(ifg_dir, "filt_topophase.flat")
    if os.path.exists(flat_file):
        z = np.fromfile(flat_file, dtype=np.complex64).reshape((l, w))
        wrapped = np.angle(z).astype(np.float32)
        wrapped_m = np.where(mask, np.nan, wrapped)
        W_ds = wrapped_m[::step, ::step]

        out2 = os.path.join(ifg_dir, "compare_wrapped_unwrapped.png")
        plt.figure(figsize=(14, 6))
        plt.subplot(1, 2, 1)
        im1 = plt.imshow(W_ds, cmap="jet", vmin=-np.pi, vmax=np.pi)
        plt.colorbar(im1, fraction=0.046, pad=0.04, label="Wrapped phase (rad)")
        plt.title(f"Wrapped (filtered) step={step}")
        plt.axis("off")

        plt.subplot(1, 2, 2)
        im2 = plt.imshow(u, cmap="jet", vmin=vmin, vmax=vmax)
        plt.colorbar(im2, fraction=0.046, pad=0.04, label="Unwrapped phase (rad)")
        plt.title(f"Unwrapped (masked) step={step} v=[{vmin:.2f},{vmax:.2f}]")
        plt.axis("off")

        plt.tight_layout()
        plt.savefig(out2, dpi=200)
        plt.close()
        say(f"  [OK] {out2}")


# ─────────────────────────────────────────────
# 통합 실행 함수
# ─────────────────────────────────────────────
def run_visualization(base_dir):
    """CSK InSAR 전체 시각화 (export + unwrap PNG)"""
    say(f"시각화 시작: {base_dir}")

    out_dir = os.path.join(base_dir, "export")
    out_tif = os.path.join(out_dir, "tif")
    out_png_geo = os.path.join(out_dir, "png", "geo")
    out_png_rdr = os.path.join(out_dir, "png", "rdr")
    out_png_stages = os.path.join(out_dir, "png", "stages")
    for d in [out_tif, out_png_geo, out_png_rdr, out_png_stages]:
        os.makedirs(d, exist_ok=True)

    # 단계별 중간 산출물 (ISCE2가 자동 생성하지 않는 것들)
    generate_multilook(base_dir, out_png_stages, rlooks=4, alooks=4)
    generate_raw_interferogram(base_dir, out_png_stages)
    generate_flat_earth_only_interferogram(base_dir, out_png_stages)

    # 기존 export
    export_geotiffs(base_dir, out_tif)
    export_geo_png(base_dir, out_tif, out_png_geo)
    export_rdr_png(base_dir, out_png_rdr)

    ifg_dir = os.path.join(base_dir, "interferogram")
    export_unwrap_png(ifg_dir)

    say("전체 시각화 완료")
