"""
빠른 테스트 스크립트

환경 설정이 올바른지 확인하고 기본 기능을 테스트합니다.
"""

import sys
import os

def test_imports():
    """필수 패키지 임포트 테스트"""
    print("="*80)
    print("1. 패키지 임포트 테스트")
    print("="*80)
    
    required_packages = {
        'torch': 'PyTorch',
        'cv2': 'OpenCV',
        'numpy': 'NumPy',
        'rasterio': 'Rasterio',
        'lightglue': 'LightGlue',
    }
    
    failed = []
    for package, name in required_packages.items():
        try:
            __import__(package)
            print(f"✅ {name:20s} - OK")
        except ImportError as e:
            print(f"❌ {name:20s} - 실패: {e}")
            failed.append(name)
    
    if failed:
        print(f"\n⚠️  실패한 패키지: {', '.join(failed)}")
        print("다음 명령어로 설치하세요:")
        print("pip install -r requirements_pipeline.txt")
        return False
    
    print("\n✅ 모든 패키지가 정상적으로 임포트되었습니다.")
    return True

def test_gdal():
    """GDAL 설치 확인"""
    print("\n" + "="*80)
    print("2. GDAL 테스트")
    print("="*80)
    
    import subprocess
    
    commands = ['gdalwarp', 'gdal_translate', 'gdalinfo']
    failed = []
    
    for cmd in commands:
        try:
            result = subprocess.run([cmd, '--version'], 
                                   capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                version = result.stdout.strip().split('\n')[0]
                print(f"✅ {cmd:20s} - {version}")
            else:
                print(f"❌ {cmd:20s} - 실행 실패")
                failed.append(cmd)
        except FileNotFoundError:
            print(f"❌ {cmd:20s} - 명령어를 찾을 수 없음")
            failed.append(cmd)
        except Exception as e:
            print(f"❌ {cmd:20s} - 오류: {e}")
            failed.append(cmd)
    
    if failed:
        print(f"\n⚠️  실패한 명령어: {', '.join(failed)}")
        print("GDAL을 설치하세요:")
        print("sudo apt-get install gdal-bin libgdal-dev")
        return False
    
    print("\n✅ GDAL이 정상적으로 설치되어 있습니다.")
    return True

def test_gpu():
    """GPU 사용 가능 여부 확인"""
    print("\n" + "="*80)
    print("3. GPU 테스트")
    print("="*80)
    
    try:
        import torch
        
        if torch.cuda.is_available():
            print(f"✅ CUDA 사용 가능")
            print(f"   GPU: {torch.cuda.get_device_name(0)}")
            print(f"   CUDA 버전: {torch.version.cuda}")
            print(f"   GPU 메모리: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.2f} GB")
        elif torch.backends.mps.is_available():
            print(f"✅ Apple MPS 사용 가능")
            print(f"   Metal Performance Shaders 활성화")
        else:
            print(f"⚠️  GPU 사용 불가 - CPU 모드로 실행됩니다")
            print(f"   (정상 작동하지만 속도가 느릴 수 있습니다)")
    except Exception as e:
        print(f"❌ GPU 테스트 실패: {e}")
        return False
    
    return True

def test_file_access():
    """파일 접근 권한 테스트"""
    print("\n" + "="*80)
    print("4. 파일 시스템 테스트")
    print("="*80)
    
    # 임시 디렉토리 생성 테스트
    test_dir = "/tmp/geometric_correction_test"
    try:
        os.makedirs(test_dir, exist_ok=True)
        
        # 파일 쓰기 테스트
        test_file = os.path.join(test_dir, "test.txt")
        with open(test_file, 'w') as f:
            f.write("test")
        
        # 파일 읽기 테스트
        with open(test_file, 'r') as f:
            content = f.read()
        
        # 정리
        os.remove(test_file)
        os.rmdir(test_dir)
        
        print(f"✅ 파일 시스템 읽기/쓰기 - OK")
        return True
        
    except Exception as e:
        print(f"❌ 파일 시스템 테스트 실패: {e}")
        return False

def test_sample_matching():
    """간단한 매칭 테스트"""
    print("\n" + "="*80)
    print("5. SuperPoint + LightGlue 매칭 테스트")
    print("="*80)
    
    try:
        import torch
        import numpy as np
        from lightglue import SuperPoint, LightGlue
        from lightglue.utils import rbd
        
        device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        
        print(f"디바이스: {device}")
        print("모델 로딩 중...")
        
        extractor = SuperPoint(max_num_keypoints=1024).eval().to(device)
        matcher = LightGlue(features='superpoint').eval().to(device)
        
        print("✅ 모델 로딩 완료")
        
        # 더미 이미지 생성
        print("더미 이미지로 테스트 중...")
        img1 = torch.rand(1, 1, 256, 256).to(device)
        img2 = torch.rand(1, 1, 256, 256).to(device)
        
        with torch.no_grad():
            feats1 = extractor.extract(img1)
            feats2 = extractor.extract(img2)
            matches = matcher({'image0': feats1, 'image1': feats2})
        
        print(f"✅ 매칭 테스트 성공")
        print(f"   추출된 keypoints: {feats1['keypoints'].shape[1]}개")
        
        return True
        
    except Exception as e:
        print(f"❌ 매칭 테스트 실패: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """전체 테스트 실행"""
    print("\n")
    print("╔" + "="*78 + "╗")
    print("║" + " "*20 + "기하보정 파이프라인 환경 테스트" + " "*25 + "║")
    print("╚" + "="*78 + "╝")
    
    tests = [
        ("패키지 임포트", test_imports),
        ("GDAL", test_gdal),
        ("GPU", test_gpu),
        ("파일 시스템", test_file_access),
        ("AI 매칭", test_sample_matching),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ {name} 테스트 중 예외 발생: {e}")
            results.append((name, False))
    
    # 결과 요약
    print("\n" + "="*80)
    print("테스트 결과 요약")
    print("="*80)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ 통과" if result else "❌ 실패"
        print(f"{name:20s} : {status}")
    
    print("\n" + "-"*80)
    print(f"총 {total}개 테스트 중 {passed}개 통과 ({passed/total*100:.0f}%)")
    print("-"*80)
    
    if passed == total:
        print("\n🎉 모든 테스트를 통과했습니다!")
        print("   geometric_correction_pipeline_v1.py를 실행할 준비가 되었습니다.")
        return 0
    else:
        print(f"\n⚠️  {total - passed}개의 테스트가 실패했습니다.")
        print("   위의 오류 메시지를 확인하고 문제를 해결하세요.")
        return 1

if __name__ == "__main__":
    sys.exit(main())

