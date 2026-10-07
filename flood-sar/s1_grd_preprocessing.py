# file: S1_GRD_preprocessing.py
# 선택한 편파(VV/HH)만 처리하는 S1 GRD 전처리 파이프라인

# 순서:
# 1 READ
# 1.5 Subset (선택 편파만 유지)
# 2 Apply-Orbit-File (Sentinel Precise)
# 3 ThermalNoiseRemoval (removeThermalNoise=True)
# 4 Remove-GRD-Border-Noise (border margin = 500 px)
# 5 Calibration (Sigma0만)
# 6 Speckle-Filter (Lee Sigma: looks=1, 7x7, sigma=0.9, target 3x3)
# 7 Terrain-Correction (DEM=SRTM 1Sec HGT, Bilinear)
# 8 LinearToFromdB (to dB)
# 9 WRITE (GeoTIFF)

# 사용:
#   anaconda prompt 실행 후
#   conda activate snappy39
#   python "<S1_GRD_preprocessing.py 경로>" --input "<ZIP or folder 경로>" --out "<OUT_DIR 경로>" --pol VV

#   실행 예시 : 
# 개별 파일 전처리
# python <DATA_ROOT>\etc\code\S1_GRD_preprocessing.py --input "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\sentinel1\S1A_IW_GRDH_1SDV_20250712T093124_20250712T093154_060049_0775E2_5D79.SAFE.zip" --out "<DATA_ROOT>\07_disaster\flood\Korea\S1_process" --pol VV

# 폴더 내 파일 모두 전처리
# python <DATA_ROOT>\etc\code\S1_GRD_preprocessing.py --input "<DATA_ROOT>\07_disaster\flood\Korea\202507_Jinju\sentinel1" --out "<DATA_ROOT>\07_disaster\flood\Korea\S1_process" --pol VV


import os
import sys
import gc
import argparse

# esa_snappy 라이브러리를 사용하여 API 가져오기
try:
    from esa_snappy import ProductIO, GPF, HashMap, jpy
    print("esa_snappy API를 성공적으로 불러왔습니다.")
except ImportError:
    print("오류: esa_snappy를 찾을 수 없습니다.")
    print("snappy가 올바르게 설치 및 구성되었는지 확인해주세요.")
    sys.exit(1)


# --- 함수 정의 ---

def s1_grd_preprocessing(product_path, output_dir, polarization):
    """
    Sentinel-1 GRD 데이터를 전처리하는 파이프라인 함수

    :param product_path: 입력 Sentinel-1 GRD 파일 경로 (.zip 또는 .SAFE 폴더)
    :param output_dir: 결과 GeoTIFF 파일이 저장될 폴더
    :param polarization: 처리할 편파 ('VV' 또는 'VH')
    """
    # 결과 파일명 생성
    basename = os.path.splitext(os.path.basename(product_path))[0]
    target_path = os.path.join(output_dir, f"{basename}_{polarization}_processed.tif")

    if os.path.exists(target_path):
        print(f"결과 파일이 이미 존재합니다: {target_path}")
        return

    print(f"처리 시작: {product_path}")
    print(f"선택된 편파: {polarization}")
    print("="*50)

    # GPF 파라미터 설정을 위한 HashMap 생성
    parameters = HashMap()

    # 1. READ
    # - 목적: Sentinel-1 데이터 파일을 snappy가 처리 가능한 Product 객체로 변환
    print("1. 데이터 읽기...")
    try:
        product = ProductIO.readProduct(product_path)
    except Exception as e:
        print(f"오류: 파일을 읽을 수 없습니다. - {e}")
        return
    print("   ...완료")

    # 2. Apply-Orbit-File (Sentinel Precise)
    # - 목적: 영상의 위치 정확도 향상
    # - 방법: 가장 정확한 위성 궤도 정보(정밀 궤도)를 자동 다운로드하여 적용
    # - 참고: 정밀 궤도 없을 시, 차선책인 복원 궤도(Restituted)를 자동으로 사용
    print("2. 정밀 궤도 정보 적용...")
    parameters.clear()
    parameters.put('Orbit State Vectors', 'Sentinel Precise (Auto Download)')
    parameters.put('Polynomial Degree', 3)
    parameters.put('Continue on Failure', 'true')
    product = GPF.createProduct('Apply-Orbit-File', parameters, product)
    print("   ...완료")

    # 3. ThermalNoiseRemoval (removeThermalNoise=True)
    # - 목적: 위성 센서 자체의 열로 인해 발생하는 노이즈 제거
    # - 효과: 신호 품질 향상
    print("3. 열잡음 제거...")
    parameters.clear()
    parameters.put('removeThermalNoise', True)
    product = GPF.createProduct('ThermalNoiseRemoval', parameters, product)
    print("   ...완료")

    # 4. Remove-GRD-Border-Noise (border margin = 500 px)
    # - 목적: 영상 가장자리의 품질이 낮은 검은색 테두리 노이즈 제거
    print("4. 경계 노이즈 제거...")
    parameters.clear()
    parameters.put('borderMargin', 500)
    product = GPF.createProduct('Remove-GRD-Border-Noise', parameters, product)
    print("   ...완료")

    # 5. Calibration (Sigma0만)
    # - 목적: 물리적 의미가 없는 디지털 값을 후방산란계수(Sigma0)로 변환
    # - 효과: 서로 다른 영상을 객관적으로 비교 가능
    print("5. 방사 보정 (Sigma0)...")
    parameters.clear()
    parameters.put('outputSigmaBand', True)
    parameters.put('outputBetaBand', False)
    parameters.put('outputGammaBand', False)
    product = GPF.createProduct('Calibration', parameters, product)
    print("   ...완료")

    # 5.5. Subset (선택 편파만 유지)
    # - 목적: 사용자가 선택한 편파(VV 또는 VH) 밴드만 남기고 불필요한 밴드 제거
    print("5.5. 편파 선택 (Subset)...")
    parameters.clear()
    parameters.put('sourceBands', f'Sigma0_{polarization}')
    product = GPF.createProduct('Subset', parameters, product)
    print("   ...완료")

    # 6. Speckle-Filter (Lee Sigma: looks=1, 7x7, sigma=0.9, target 3x3)
    # - 목적: SAR 영상 고유의 점과 같은 노이즈(스펙클) 제거
    # - 방법: Lee Sigma 알고리즘 사용
    print("6. 스펙클 필터 적용 (Lee Sigma)...")
    parameters.clear()
    parameters.put('filter', 'Lee Sigma')
    parameters.put('filterSizeX', '7')
    parameters.put('filterSizeY', '7')
    parameters.put('numLooksStr', '1')
    parameters.put('sigma', 0.9)
    parameters.put('targetWindowSizeStr', '3x3')
    product = GPF.createProduct('Speckle-Filter', parameters, product)
    print("   ...완료")

    # 7. Terrain-Correction (DEM=SRTM 1Sec HGT, Bilinear)
    # - 목적: 지형으로 인한 영상의 기하학적 왜곡 보정 및 정확한 위경도 좌표 부여
    # - 방법: 수치표고모델(DEM) 활용
    print("7. 지형 보정...")
    parameters.clear()
    parameters.put('demName', 'SRTM 1Sec HGT')
    parameters.put('imgResamplingMethod', 'BILINEAR_INTERPOLATION')
    product = GPF.createProduct('Terrain-Correction', parameters, product)
    print("   ...완료")

    # 8. LinearToFromdB (to dB)
    # - 목적: 픽셀 값을 로그 스케일인 데시벨(dB) 단위로 변환
    # - 효과: 값의 범위를 줄여 시각적 분석 용이
    print("8. dB 단위로 변환...")
    parameters.clear()
    source_band = product.getBandNames()[0]
    parameters.put('sourceBands', source_band)
    product = GPF.createProduct('LinearToFromdB', parameters, product)
    print("   ...완료")

    # 9. WRITE (GeoTIFF)
    # - 목적: 최종 처리 결과를 GeoTIFF 파일로 저장
    # - 옵션: LZW 압축(파일 크기 감소) 및 타일링(GIS 프로그램 성능 향상) 적용
    print(f"9. 결과 파일 저장 중: {target_path}")
    System = jpy.get_type('java.lang.System')
    System.setProperty('snap.dataio.bigtiff.compression.type', 'LZW')
    System.setProperty('snap.dataio.bigtiff.tiling.width', '256')
    System.setProperty('snap.dataio.bigtiff.tiling.height', '256')
    
    ProductIO.writeProduct(product, target_path, 'GeoTIFF-BigTIFF')
    
    System.clearProperty('snap.dataio.bigtiff.compression.type')
    System.clearProperty('snap.dataio.bigtiff.tiling.width')
    System.clearProperty('snap.dataio.bigtiff.tiling.height')
    
    print("   ...저장 완료!")
    print("="*50)

    # 메모리 정리
    product.closeIO()
    gc.collect()


# --- 메인 스크립트 실행 ---
if __name__ == '__main__':
    # 커맨드 라인 인자 파서 설정
    parser = argparse.ArgumentParser(description='Sentinel-1 GRD 전처리 파이프라인')
    parser.add_argument('--input', required=True, help='처리할 Sentinel-1 GRD 파일 또는 파일이 포함된 폴더 경로')
    parser.add_argument('--out', required=True, help='결과 파일이 저장될 폴더')
    parser.add_argument('--pol', required=True, choices=['VV', 'VH'], help="처리할 편파 ('VV' 또는 'VH')")
    
    args = parser.parse_args()

    # 커맨드 라인 인자를 변수에 할당
    input_path = args.input
    output_dir = args.out
    polarization_to_process = args.pol

    # 처리할 파일 목록 생성
    files_to_process = []
    if os.path.isdir(input_path):
        print(f"입력 경로가 폴더입니다. 폴더 내의 모든 .zip 파일을 찾습니다: {input_path}")
        for filename in sorted(os.listdir(input_path)): # 정렬하여 순서 보장
            if filename.lower().endswith('.zip'):
                files_to_process.append(os.path.join(input_path, filename))
        if not files_to_process:
            print("처리할 .zip 파일을 찾지 못했습니다.")
            sys.exit(0)
    elif os.path.isfile(input_path):
        print(f"입력 경로가 단일 파일입니다: {input_path}")
        files_to_process.append(input_path)
    else:
        print(f"오류: 입력 경로를 찾을 수 없습니다: {input_path}")
        sys.exit(1)

    # 출력 폴더가 없으면 생성
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 목록에 있는 파일들을 순차적으로 처리
    total_files = len(files_to_process)
    print(f"\n총 {total_files}개의 파일을 처리합니다.")
    for i, file_path in enumerate(files_to_process):
        print(f"\n--- 파일 처리 중 ({i+1}/{total_files}) ---")
        try:
            s1_grd_preprocessing(file_path, output_dir, polarization_to_process)
        except Exception as e:
            print(f"!!! 오류 발생: {os.path.basename(file_path)} 처리 중 문제가 발생했습니다. - {e}")
            print("다음 파일로 넘어갑니다.")
            continue

    print("\n모든 작업이 완료되었습니다.")