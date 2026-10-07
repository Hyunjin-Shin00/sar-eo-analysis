#!/usr/bin/env python3
"""
GUI 앱을 독립 실행 파일로 빌드하는 스크립트
PyInstaller를 사용합니다.
"""

import os
import sys
import subprocess
import platform

def check_pyinstaller():
    """PyInstaller 설치 확인"""
    try:
        import PyInstaller
        print(f"✅ PyInstaller 설치됨 (버전: {PyInstaller.__version__})")
        return True
    except ImportError:
        print("❌ PyInstaller가 설치되어 있지 않습니다.")
        print("\n설치 방법:")
        print("  pip install pyinstaller")
        return False

def build_executable():
    """독립 실행 파일 빌드"""
    print("\n" + "="*60)
    print("GUI 앱 독립 실행 파일 빌드")
    print("="*60)
    
    # PyInstaller 확인
    if not check_pyinstaller():
        response = input("\nPyInstaller를 지금 설치하시겠습니까? (y/n): ")
        if response.lower() == 'y':
            print("\nPyInstaller 설치 중...")
            subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
        else:
            print("빌드를 취소합니다.")
            return
    
    # 빌드 명령어
    spec_file = "build_app.spec"
    
    if not os.path.exists(spec_file):
        print(f"⚠️  {spec_file} 파일이 없습니다.")
        print("PyInstaller 기본 명령어로 빌드를 시도합니다...")
        cmd = [
            "pyinstaller",
            "--name=GeometricCorrectionGUI",
            "--windowed",  # GUI 앱 (콘솔 숨김)
            "--onefile",  # 단일 실행 파일
            "--add-data=geometric_correction.py:.",  # 메인 파일 포함
            "gui_app.py"
        ]
    else:
        print(f"📄 {spec_file} 파일을 사용합니다.")
        cmd = ["pyinstaller", spec_file]
    
    print(f"\n🔨 빌드 시작...")
    print(f"명령어: {' '.join(cmd)}\n")
    
    try:
        subprocess.run(cmd, check=True)
        print("\n" + "="*60)
        print("✅ 빌드 완료!")
        print("="*60)
        
        # 실행 파일 경로
        if platform.system() == "Windows":
            exe_path = "dist/GeometricCorrectionGUI.exe"
        else:
            exe_path = "dist/GeometricCorrectionGUI"
        
        print(f"\n📦 실행 파일 위치: {exe_path}")
        print(f"📁 빌드 파일: build/")
        print(f"\n🚀 실행 방법:")
        print(f"   {exe_path}")
        
        # 파일 크기 확인
        if os.path.exists(exe_path):
            size_mb = os.path.getsize(exe_path) / (1024 * 1024)
            print(f"\n📊 파일 크기: {size_mb:.1f} MB")
            
            if size_mb > 500:
                print("\n⚠️  파일 크기가 큽니다. 다음을 고려해보세요:")
                print("   - UPX 압축 사용")
                print("   - 불필요한 패키지 제외")
                print("   - 별도의 모델 파일 분리")
        
    except subprocess.CalledProcessError as e:
        print(f"\n❌ 빌드 실패: {e}")
        print("\n문제 해결:")
        print("  1. 모든 의존성이 설치되어 있는지 확인")
        print("  2. 가상환경이 활성화되어 있는지 확인")
        print("  3. GDAL이 시스템에 설치되어 있는지 확인")
        return
    
    print("\n" + "="*60)
    print("빌드 완료!")
    print("="*60)

if __name__ == "__main__":
    build_executable()

