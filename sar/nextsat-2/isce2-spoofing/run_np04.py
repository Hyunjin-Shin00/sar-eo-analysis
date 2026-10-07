# NP04 runner — n2_main_portable.py 와 동일 로직, 단 /mnt/c(DrvFs)에서 chmod 실패를
# 피하려고 shutil.copy -> shutil.copyfile 로 교체. 번들 원본은 건드리지 않음.
import os, sys, shutil, subprocess, datetime

HANDOFF = "/mnt/c/N2_InSAR/N2_USB_BUNDLE/handoff"
CODE    = "/mnt/c/N2_InSAR/N2_USB_BUNDLE/code"
for cand in (HANDOFF, CODE):
    if os.path.isfile(os.path.join(cand, "n2_patch.py")) and cand not in sys.path:
        sys.path.insert(0, cand)

from n2_patch import PATCH_CONTENT
import n2_viz

BASE_ROOT     = os.environ["N2_ROOT"]
XML_FILE_PATH = os.environ["N2_XML"]

def main():
    print("--- [Start] N2 -> CSK SPOOFING (NP04 runner) ---", flush=True)
    print(f"[cfg] BASE_ROOT = {BASE_ROOT}", flush=True)
    print(f"[cfg] XML       = {XML_FILE_PATH}", flush=True)
    assert os.path.isfile(XML_FILE_PATH), XML_FILE_PATH

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    work_dir = os.path.join(BASE_ROOT, f"N2_INSAR_{ts}")
    os.makedirs(work_dir, exist_ok=True)
    shutil.copyfile(XML_FILE_PATH, os.path.join(work_dir, "stripmapApp.xml"))  # copyfile: no chmod

    ovr_dir = os.path.expanduser("~/isce_n2_spoof")
    os.makedirs(ovr_dir, exist_ok=True)
    site_file = os.path.join(ovr_dir, "sitecustomize.py")
    with open(site_file, "w") as f:
        f.write(PATCH_CONTENT)
    print(f"[OK] patch -> {site_file}", flush=True)

    env = os.environ.copy()
    env["PYTHONPATH"] = ovr_dir + os.pathsep + env.get("PYTHONPATH", "")
    env["REQUIRE_DOPPLER"] = "1"

    app = shutil.which("stripmapApp.py")
    assert app, "stripmapApp.py not on PATH"
    print(f"[OK] app = {app}", flush=True)
    print(f"[OK] work_dir = {work_dir}", flush=True)
    with open(os.path.join(work_dir, "run.log"), "w") as log:
        p = subprocess.Popen([sys.executable, app, "stripmapApp.xml"],
                             cwd=work_dir, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in p.stdout:
            print(line, end="", flush=True)
            log.write(line); log.flush()
        p.wait()
    print(f"[done] rc={p.returncode}  work_dir={work_dir}", flush=True)

    print("\n--- [Viz] PNG 생성 ---", flush=True)
    try:
        n2_viz.run_visualization(work_dir)
    except Exception as e:
        print(f"Viz Error: {e}", flush=True)
    print(f"[ALLDONE] work_dir={work_dir}", flush=True)

if __name__ == "__main__":
    main()
