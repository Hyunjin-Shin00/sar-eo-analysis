# main_csk.py — CSK InSAR 구조화 실행 스크립트
# isce2_snaphu_환경에서_언래핑까지_한번에_성공.txt를 Python으로 구조화
# 실행: conda activate isce2_snaphu && python main_csk.py

import os, sys, subprocess, datetime
import numpy as np
import xml.etree.ElementTree as ET
import csk_viz

# ================= USER CONFIG =================
BASE_ROOT = "<DATA_ROOT>/nationalpark_SAR/CSK"

# 출력 저장 경로 (None이면 BASE_ROOT 아래 자동 생성)
OUTPUT_DIR = "<DATA_ROOT>/nationalpark_SAR/CSK/20200712_20200713_interferogram_test"

# reference / secondary HDF5 경로 (glob 패턴)
REF_PATTERN = "<DATA_ROOT>/nationalpark_SAR/CSK/20200712/CSKS4_*.h5"
SEC_PATTERN = "<DATA_ROOT>/nationalpark_SAR/CSK/20200713/CSKS2_*.h5"

# DEM 경로 (None이면 ISCE2가 자동 다운로드)
DEM_PATH = "<DATA_ROOT>/nationalpark_SAR/CSK/DEM/output_hh.wgs84.dem"

# SNAPHU 경로
SNAPHU_BIN = "<WORK_ROOT>/StaMPS_Python/bin/snaphu"

# stripmapApp.py 경로 (which로 못 찾을 때 fallback)
STRIPMAP_APP_SUB = "$CONDA_PREFIX/lib/python3.10/site-packages/isce/applications/stripmapApp.py"

# 실행 옵션
RUN_EXPORT = True    # export(GeoTIFF/PNG) 생성 여부
RUN_UNWRAP = True    # SNAPHU 언래핑 실행 여부
CLEAN_PREV = False   # True면 이전 산출물 삭제 후 재실행
# ===============================================


def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def find_first_h5(pattern):
    """glob 패턴으로 첫 번째 H5 파일 찾기"""
    import glob
    files = sorted(glob.glob(pattern))
    return files[0] if files else None


def create_stripmap_xml(work_dir, ref_path, sec_path):
    """stripmapApp.xml 생성"""
    dem_line = ""
    if DEM_PATH and os.path.exists(DEM_PATH):
        dem_line = f"\n    <property name='demFilename'><value>{DEM_PATH}</value></property>"
        log(f"DEM 지정: {DEM_PATH}")
    else:
        log("DEM_PATH 미지정 — ISCE2 자동 다운로드")

    xml_content = f"""<stripmapApp>
  <component name="insar">
    <property name="sensor name">COSMO_SKYMED_SLC</property>

    <component name="reference">
      <property name="HDF5"><value>{ref_path}</value></property>
      <property name="OUTPUT"><value>reference</value></property>
    </component>

    <component name="secondary">
      <property name="HDF5"><value>{sec_path}</value></property>
      <property name="OUTPUT"><value>secondary</value></property>
    </component>
{dem_line}
    <property name="doUnwrap">False</property>
  </component>
</stripmapApp>"""
    xml_path = os.path.join(work_dir, "stripmapApp.xml")
    with open(xml_path, "w") as f:
        f.write(xml_content)
    return xml_path


def run_stripmap(work_dir):
    """stripmapApp.py 실행 (wrapped interferogram까지)"""
    app = subprocess.shutil.which("stripmapApp.py") if hasattr(subprocess, 'shutil') else None
    if app is None:
        import shutil
        app = shutil.which("stripmapApp.py") or STRIPMAP_APP_SUB

    log(f"stripmapApp 실행: {app}")
    env = os.environ.copy()
    env["HDF5_USE_FILE_LOCKING"] = "FALSE"

    log_path = os.path.join(work_dir, "stripmapApp.log")
    with open(log_path, "w") as logf:
        p = subprocess.Popen(
            [sys.executable, app, "stripmapApp.xml"],
            cwd=work_dir, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        for line in p.stdout:
            print(line, end="")
            logf.write(line)
        p.wait()

    if p.returncode != 0:
        log(f"WARNING: stripmapApp 종료 코드 {p.returncode}")
    else:
        log("stripmapApp 완료")
    return p.returncode


def run_snaphu(work_dir):
    """SNAPHU 언래핑 실행"""
    ifg_dir = os.path.join(work_dir, "interferogram")

    # 필수 파일 체크
    required = ["filt_topophase.flat", "filt_topophase.flat.xml",
                "topophase.cor", "topophase.cor.xml"]
    for f in required:
        if not os.path.exists(os.path.join(ifg_dir, f)):
            log(f"ERROR: 필수 파일 없음 — {f}")
            return 1

    # width/length 읽기
    xml_path = os.path.join(ifg_dir, "filt_topophase.flat.xml")
    root = ET.parse(xml_path).getroot()
    width = int(root.find(".//property[@name='width']/value").text.strip())
    length = int(root.find(".//property[@name='length']/value").text.strip())
    log(f"영상 크기: {width} x {length}")

    # wrapped phase(float32) 생성 — filt_topophase.flat에서 항상 재추출
    phase_file = os.path.join(ifg_dir, "filt_topophase.phase")
    flat_file = os.path.join(ifg_dir, "filt_topophase.flat")
    log("wrapped phase 추출 중...")
    z = np.fromfile(flat_file, dtype=np.complex64)
    assert z.size == width * length, f"size mismatch: {z.size} vs {width * length}"
    np.angle(z).astype(np.float32).tofile(phase_file)
    log(f"  → {phase_file} ({os.path.getsize(phase_file)} bytes)")

    # snaphu config 생성
    conf_path = os.path.join(ifg_dir, "snaphu_float.conf")
    with open(conf_path, "w") as f:
        f.write("INFILEFORMAT  FLOAT_DATA\nOUTFILEFORMAT FLOAT_DATA\n")

    # snaphu 실행
    out_unw = os.path.join(ifg_dir, "filt_topophase.unw.phase2")
    out_cc = os.path.join(ifg_dir, "filt_topophase.unw.phase2.conncomp")
    log_file = os.path.join(ifg_dir, "snaphu_phase2.log")

    snaphu = SNAPHU_BIN
    if not os.path.exists(snaphu):
        import shutil
        snaphu = shutil.which("snaphu") or SNAPHU_BIN

    log(f"SNAPHU 실행: {snaphu}")
    cmd = [
        snaphu, "-f", "snaphu_float.conf",
        "-d", "filt_topophase.phase", str(width),
        "-c", "topophase.cor",
        "-o", "filt_topophase.unw.phase2",
        "-g", "filt_topophase.unw.phase2.conncomp",
        "--mcf", "-v",
    ]

    with open(log_file, "w") as lf:
        p = subprocess.run(cmd, cwd=ifg_dir, stdout=lf, stderr=subprocess.STDOUT)

    if p.returncode != 0:
        log(f"ERROR: SNAPHU 실패 (RC={p.returncode})")
        # 마지막 로그 출력
        with open(log_file) as lf:
            lines = lf.readlines()
            for line in lines[-30:]:
                print(line, end="")
        return p.returncode

    log(f"SNAPHU 완료")
    log(f"  UNW: {os.path.getsize(out_unw)} bytes")
    log(f"  CC:  {os.path.getsize(out_cc)} bytes")
    return 0


def main():
    log("=" * 50)
    log("CSK InSAR 파이프라인 시작")
    log("=" * 50)

    # 1. 입력 파일 확인
    ref_path = find_first_h5(REF_PATTERN)
    sec_path = find_first_h5(SEC_PATTERN)

    if not ref_path or not os.path.exists(ref_path):
        log(f"ERROR: Reference H5 없음 — {REF_PATTERN}")
        sys.exit(1)
    if not sec_path or not os.path.exists(sec_path):
        log(f"ERROR: Secondary H5 없음 — {SEC_PATTERN}")
        sys.exit(1)

    log(f"REF: {ref_path}")
    log(f"SEC: {sec_path}")

    # 2. 작업 디렉토리 생성
    ref_date = os.path.basename(os.path.dirname(ref_path))   # 20200712
    sec_date = os.path.basename(os.path.dirname(sec_path))   # 20200713
    work_dir = OUTPUT_DIR if OUTPUT_DIR else os.path.join(BASE_ROOT, f"{ref_date}_{sec_date}_interferogram_isce2_snaphu")
    os.makedirs(work_dir, exist_ok=True)
    log(f"작업 디렉토리: {work_dir}")

    # 3. (선택) 이전 산출물 삭제
    if CLEAN_PREV:
        import shutil
        for d in ["interferogram", "geometry", "offsets", "coregisteredSlc",
                   "reference", "secondary", "misreg", "export"]:
            target = os.path.join(work_dir, d)
            if os.path.exists(target):
                shutil.rmtree(target)
        for pattern in ["*.log", "*.xml", "dem.crop*", "demLat_*"]:
            import glob
            for f in glob.glob(os.path.join(work_dir, pattern)):
                os.remove(f)
        log("이전 산출물 삭제 완료")

    # 4. stripmapApp.xml 생성
    create_stripmap_xml(work_dir, ref_path, sec_path)
    log("stripmapApp.xml 생성 완료")

    # 5. stripmapApp 실행
    rc = run_stripmap(work_dir)
    if rc != 0:
        log("WARNING: stripmapApp 비정상 종료. 계속 진행 시도.")

    # 6. Export (GeoTIFF/PNG)
    if RUN_EXPORT:
        log("Export 시작 (GeoTIFF + PNG)")
        csk_viz.run_visualization(work_dir)

    # 7. SNAPHU 언래핑
    if RUN_UNWRAP:
        log("SNAPHU 언래핑 시작")
        rc = run_snaphu(work_dir)
        if rc == 0:
            # 언래핑 결과 시각화
            ifg_dir = os.path.join(work_dir, "interferogram")
            csk_viz.export_unwrap_png(ifg_dir)

    log("=" * 50)
    log("CSK InSAR 파이프라인 완료")
    log(f"결과 위치: {work_dir}")
    log("=" * 50)


if __name__ == "__main__":
    main()
