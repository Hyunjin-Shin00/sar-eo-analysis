# main_n2.py 수정본
import os, sys, shutil, subprocess, datetime
from n2_patch import PATCH_CONTENT
import n2_viz                    

BASE_ROOT = "/home/hyunjin/nas/nationalpark_SAR"
# output는 해당 경로에 타임스탬프 폴더(N2_INSAR_YYYYMMDD_HHMMSS)로 자동 생성
XML_FILE_PATH = "/home/hyunjin/nas/nationalpark_SAR/input_n2.xml" 
STRIPMAP_APP_SUB = "/home/hyunjin/miniconda3/envs/isce2_snaphu/lib/python3.10/site-packages/isce/applications/stripmapApp.py"

def main():
    print("--- [Start] N2 to CSK SPOOFING: Dynamic Multi-File Support ---")
    
    # 1. 작업 디렉토리 생성
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    work_dir = os.path.join(BASE_ROOT, f"N2_INSAR_{ts}")
    os.makedirs(work_dir, exist_ok=True)
    shutil.copy(XML_FILE_PATH, os.path.join(work_dir, "stripmapApp.xml"))
    
    # 2. 만능 패치 생성 (어떤 파일이든 동적 대응)
    ovr_dir = os.path.expanduser("~/isce_n2_spoof")
    os.makedirs(ovr_dir, exist_ok=True)
    site_file = os.path.join(ovr_dir, "sitecustomize.py")
    with open(site_file, "w") as f:
        f.write(PATCH_CONTENT)
    print(f"[OK] Universal Patch created at {site_file}")
    
    # 3. 환경 변수 설정 (ISCE가 실행될 때 패치를 가장 먼저 읽도록 함)
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{ovr_dir}:{env.get('PYTHONPATH','')}"
    env["REQUIRE_DOPPLER"] = "1"
    
    # 4. stripmapApp.py 실행
    app = shutil.which("stripmapApp.py") or STRIPMAP_APP_SUB
    with open(os.path.join(work_dir, "run.log"), "w") as log:
        p = subprocess.Popen([sys.executable, app, "stripmapApp.xml"], 
                             cwd=work_dir, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in p.stdout:
            print(line, end="")
            log.write(line)
            
    # 5. 시각화
    print("\n--- [Viz] Generating PNGs ---")
    try: n2_viz.run_visualization(work_dir)
    except Exception as e: print(f"Viz Error: {e}")

if __name__ == "__main__":
    main()