# n2_main.py 이식(portable) 버전 — 하드코딩 경로 제거
#
# 원본 n2_main.py는 사내 절대경로 3개가 하드코딩돼 있어 다른 PC에서 그대로 안 돈다.
# 이 버전은:
#   - BASE_ROOT       = 환경변수 N2_ROOT, 없으면 이 스크립트가 있는 폴더의 부모(=프로젝트 루트)
#   - XML_FILE_PATH   = BASE_ROOT/input_n2.xml (환경변수 N2_XML로 덮어쓰기 가능)
#   - stripmapApp.py  = PATH에서 자동 검색(conda 활성화돼 있으면 잡힘)
# 즉 code/ 옆에 input_n2.xml, SLC/ 만 있으면 어디에 두든 실행된다.
#
# 사용:  conda activate isce2_snaphu &&  python n2_main_portable.py
import os, sys, shutil, subprocess, datetime

# code/ 폴더를 import 경로에 추가 (n2_patch, n2_viz가 code/ 안에 있을 때 대비)
_HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (_HERE, os.path.join(_HERE, "code"), os.path.join(os.path.dirname(_HERE), "code")):
    if os.path.isfile(os.path.join(cand, "n2_patch.py")) and cand not in sys.path:
        sys.path.insert(0, cand)

from n2_patch import PATCH_CONTENT
import n2_viz

# --- 경로 결정 (환경변수 > 자동추정) ---
BASE_ROOT = os.environ.get("N2_ROOT") or os.path.dirname(_HERE)
XML_FILE_PATH = os.environ.get("N2_XML") or os.path.join(BASE_ROOT, "input_n2.xml")


def main():
    print("--- [Start] N2 -> CSK SPOOFING (portable) ---")
    print(f"[cfg] BASE_ROOT = {BASE_ROOT}")
    print(f"[cfg] XML       = {XML_FILE_PATH}")
    if not os.path.isfile(XML_FILE_PATH):
        sys.exit(f"[FATAL] input xml not found: {XML_FILE_PATH}")

    # 1. 타임스탬프 작업 폴더
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    work_dir = os.path.join(BASE_ROOT, f"N2_INSAR_{ts}")
    os.makedirs(work_dir, exist_ok=True)
    shutil.copy(XML_FILE_PATH, os.path.join(work_dir, "stripmapApp.xml"))

    # 2. sitecustomize spoof 패치 배포 (~/isce_n2_spoof/)
    ovr_dir = os.path.expanduser("~/isce_n2_spoof")
    os.makedirs(ovr_dir, exist_ok=True)
    site_file = os.path.join(ovr_dir, "sitecustomize.py")
    with open(site_file, "w") as f:
        f.write(PATCH_CONTENT)
    print(f"[OK] patch -> {site_file}")

    # 3. 환경변수: 패치가 가장 먼저 로드되도록 PYTHONPATH 선두 삽입
    env = os.environ.copy()
    env["PYTHONPATH"] = ovr_dir + os.pathsep + env.get("PYTHONPATH", "")
    env["REQUIRE_DOPPLER"] = "1"

    # 4. stripmapApp.py 실행 (PATH에서 자동 검색)
    app = shutil.which("stripmapApp.py")
    if not app:
        sys.exit("[FATAL] stripmapApp.py not on PATH — 'conda activate isce2_snaphu' 했는지 확인")
    print(f"[OK] app = {app}")
    with open(os.path.join(work_dir, "run.log"), "w") as log:
        p = subprocess.Popen([sys.executable, app, "stripmapApp.xml"],
                             cwd=work_dir, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in p.stdout:
            print(line, end="")
            log.write(line)
        p.wait()
    print(f"[done] rc={p.returncode}  work_dir={work_dir}")

    # 5. 시각화
    print("\n--- [Viz] PNG 생성 ---")
    try:
        n2_viz.run_visualization(work_dir)
    except Exception as e:
        print(f"Viz Error: {e}")


if __name__ == "__main__":
    main()
