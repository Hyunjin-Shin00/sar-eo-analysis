#!/usr/bin/env python3
"""
가상환경 설정 스크립트 (플랫폼 독립적)
Python 3.8 이상 필요
"""

import os
import sys
import subprocess
import platform
from pathlib import Path
import shutil

def run_command(cmd, check=True, shell=False):
    """명령어 실행"""
    if isinstance(cmd, str) and platform.system() == "Windows":
        shell = True
    try:
        result = subprocess.run(
            cmd, 
            shell=shell, 
            check=check, 
            capture_output=True, 
            text=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"❌ 오류: {e.stderr}")
        if check:
            raise
        return None

def check_python_version():
    """Python 버전 확인"""
    version = sys.version_info
    print(f"📌 Python 버전: {version.major}.{version.minor}.{version.micro}")
    
    if version < (3, 8):
        print("❌ Python 3.8 이상이 필요합니다.")
        sys.exit(1)
    
    # Python 3.12 이상은 일부 패키지와 호환성 문제가 있을 수 있음
    if version >= (3, 12):
        print("⚠️  Python 3.12 이상은 일부 패키지와 호환성 문제가 있을 수 있습니다.")
        print("   Python 3.9-3.11 사용을 권장합니다.")
        response = input("   계속 진행하시겠습니까? (y/n): ")
        if response.lower() != 'y':
            print("   설치가 취소되었습니다.")
            print("\n   Python 3.9-3.11 설치 방법:")
            print("   - pyenv 사용: pyenv install 3.11.9")
            print("   - conda 사용: conda create -n geometric_correction python=3.11")
            sys.exit(1)
    
    print("✅ Python 버전 확인 완료")
    return True

def check_gdal():
    """GDAL 설치 확인"""
    print("\n🔍 GDAL 설치 확인 중...")
    
    # gdal-config 명령어 확인
    try:
        if platform.system() == "Windows":
            result = run_command("where gdal-config", check=False, shell=True)
        else:
            result = run_command("which gdal-config", check=False)
        
        if result:
            gdal_version = run_command(["gdal-config", "--version"], check=False)
            print(f"   ✅ GDAL이 설치되어 있습니다 (버전: {gdal_version})")
            return gdal_version
    except:
        pass
    
    print("   ⚠️  GDAL이 시스템에 설치되어 있지 않습니다.")
    print("\n   설치 방법:")
    
    if platform.system() == "Darwin":  # macOS
        print("      brew install gdal")
    elif platform.system() == "Linux":
        print("      sudo apt-get update")
        print("      sudo apt-get install gdal-bin libgdal-dev")
    elif platform.system() == "Windows":
        print("      1. OSGeo4W 설치: https://trac.osgeo.org/osgeo4w/")
        print("      2. 또는 conda: conda install -c conda-forge gdal")
    
    print("\n   또는 conda 사용:")
    print("      conda install -c conda-forge gdal")
    
    response = input("\n   계속 진행하시겠습니까? (y/n): ")
    if response.lower() != 'y':
        print("   설치가 취소되었습니다.")
        sys.exit(1)
    
    return None

def setup_venv():
    """가상환경 설정"""
    venv_name = "venv"
    venv_path = Path(venv_name)
    
    print("\n" + "="*50)
    print("기하보정 파이프라인 가상환경 설정")
    print("="*50)
    
    # Python 버전 확인
    check_python_version()
    
    # 기존 가상환경 확인
    if venv_path.exists():
        print(f"\n⚠️  가상환경 '{venv_name}'가 이미 존재합니다.")
        response = input("   삭제하고 다시 만들까요? (y/n): ")
        if response.lower() == 'y':
            print("   기존 가상환경 삭제 중...")
            import shutil
            shutil.rmtree(venv_path)
        else:
            print("   기존 가상환경을 사용합니다.")
            print("\n✅ 가상환경 설정 완료!")
            print(f"\n가상환경 활성화:")
            if platform.system() == "Windows":
                print(f"   {venv_name}\\Scripts\\activate.bat")
            else:
                print(f"   source {venv_name}/bin/activate")
            return
    
    # 가상환경 생성
    print(f"\n📦 가상환경 생성 중...")
    run_command([sys.executable, "-m", "venv", venv_name])
    
    # 가상환경 활성화 경로 설정
    if platform.system() == "Windows":
        python_exe = venv_path / "Scripts" / "python.exe"
        pip_exe = venv_path / "Scripts" / "pip.exe"
    else:
        python_exe = venv_path / "bin" / "python"
        pip_exe = venv_path / "bin" / "pip"
    
    # pip 업그레이드 (에러 무시 모드로)
    print("⬆️  pip 업그레이드 중...")
    try:
        run_command([str(pip_exe), "install", "--upgrade", "pip", "setuptools", "wheel"], check=False)
    except:
        # pip 업그레이드 실패해도 계속 진행
        print("   ⚠️  pip 업그레이드에 경고가 있지만 계속 진행합니다...")
    
    # pip 재설치로 문제 해결 시도
    print("🔧 pip 재설치 중...")
    try:
        run_command([str(python_exe), "-m", "pip", "install", "--upgrade", "--force-reinstall", "pip"], check=False)
    except:
        pass
    
    # GDAL 확인 및 설치
    gdal_version = check_gdal()
    if gdal_version:
        print(f"\n📥 GDAL Python 바인딩 설치 중... (버전: {gdal_version})")
        run_command([str(pip_exe), "install", f"gdal=={gdal_version}"])
    
    # requirements.txt 설치
    requirements_file = Path("requirements.txt")
    if not requirements_file.exists():
        print("❌ requirements.txt 파일을 찾을 수 없습니다.")
        sys.exit(1)
    
    # 패키지 설치 (에러 발생 시 개별 설치 시도)
    print("\n📥 패키지 설치 중...")
    print("   이 과정은 몇 분이 소요될 수 있습니다...")
    
    try:
        run_command([str(pip_exe), "install", "-r", str(requirements_file)])
    except subprocess.CalledProcessError as e:
        print("\n⚠️  일부 패키지 설치에 실패했습니다.")
        print("   개별 패키지 설치를 시도합니다...")
        
        # requirements.txt 읽기
        with open(requirements_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        failed_packages = []
        for line in lines:
            line = line.strip()
            # 주석이나 빈 줄 건너뛰기
            if not line or line.startswith('#'):
                continue
            
            # 버전 제약이 있으면 그대로, 없으면 최신 버전 설치
            package = line.split('#')[0].strip()  # 인라인 주석 제거
            
            try:
                print(f"   📦 {package} 설치 중...")
                run_command([str(pip_exe), "install", package], check=True)
            except subprocess.CalledProcessError:
                print(f"   ❌ {package} 설치 실패")
                failed_packages.append(package)
        
        if failed_packages:
            print("\n⚠️  다음 패키지 설치에 실패했습니다:")
            for pkg in failed_packages:
                print(f"   - {pkg}")
            print("\n수동으로 설치하세요:")
            for pkg in failed_packages:
                print(f"   pip install {pkg}")
            
            # lightglue 같은 경우 GitHub에서 설치 시도
            if any('lightglue' in pkg.lower() for pkg in failed_packages):
                print("\n💡 lightglue는 GitHub에서 설치할 수 있습니다:")
                print("   pip install git+https://github.com/cvg/LightGlue.git")
                response = input("   지금 설치하시겠습니까? (y/n): ")
                if response.lower() == 'y':
                    try:
                        run_command([str(pip_exe), "install", "git+https://github.com/cvg/LightGlue.git"], check=False)
                    except:
                        pass
    
    print("\n" + "="*50)
    print("✅ 가상환경 설정 완료!")
    print("="*50)
    print("\n가상환경 활성화:")
    if platform.system() == "Windows":
        print(f"   {venv_name}\\Scripts\\activate.bat")
    else:
        print(f"   source {venv_name}/bin/activate")
    
    print("\nGUI 앱 실행:")
    print("   python gui_app.py")
    
    print("\n파이프라인 직접 실행:")
    print("   python geometric_correction.py")
    
    print("\n가상환경 비활성화:")
    print("   deactivate")
    print()

if __name__ == "__main__":
    try:
        setup_venv()
    except KeyboardInterrupt:
        print("\n\n⚠️  사용자가 취소했습니다.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

