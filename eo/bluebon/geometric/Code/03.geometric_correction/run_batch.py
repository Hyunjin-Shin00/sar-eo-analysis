#!/usr/bin/env python3
"""
배치 처리 스크립트
JSON/TXT 설정 파일을 읽어서 여러 데이터셋에 대해 기하보정 파이프라인을 실행합니다.

사용법:
    python run_batch.py <설정파일경로>

예시:
    python run_batch.py /Users/kyle_kim/Downloads/geometric_correction/batch_config.json
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime
import traceback

# geometric_correction 모듈 import
try:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "geometric_correction_module",
        os.path.join(os.path.dirname(__file__), "geometric_correction.py")
    )
    geometric_correction_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(geometric_correction_module)
    
    run_pipeline = geometric_correction_module.main
except Exception as e:
    print(f"❌ 오류: geometric_correction 모듈을 import할 수 없습니다: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)


def load_batch_config(config_path):
    """
    배치 설정 파일을 읽어서 데이터셋 리스트를 반환합니다.
    
    Args:
        config_path: JSON 또는 TXT 파일 경로
        
    Returns:
        list: 데이터셋 딕셔너리 리스트
    """
    config_path = Path(config_path)
    
    if not config_path.exists():
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {config_path}")
    
    if config_path.suffix.lower() == '.json':
        # JSON 파일 읽기
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        # 딕셔너리 형태인 경우 리스트로 변환
        if isinstance(data, dict):
            datasets = list(data.values())
        elif isinstance(data, list):
            datasets = data
        else:
            raise ValueError(f"JSON 파일 형식이 올바르지 않습니다: {type(data)}")
            
    elif config_path.suffix.lower() in ['.txt', '.tsv']:
        # TXT/TSV 파일 읽기 (탭 구분)
        datasets = []
        with open(config_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            if len(lines) < 2:
                raise ValueError("TXT 파일에 헤더와 데이터가 없습니다.")
            
            # 헤더 파싱
            header = lines[0].strip().split('\t')
            required_fields = ['name', 'dem', 'reference', 'target', 'output', 
                             'target_center_lat', 'target_center_lon', 'target_resolution']
            
            # 필수 필드 확인
            missing_fields = [f for f in required_fields if f not in header]
            if missing_fields:
                raise ValueError(f"필수 필드가 없습니다: {missing_fields}")
            
            # 데이터 파싱
            for line_num, line in enumerate(lines[1:], start=2):
                line = line.strip()
                if not line:
                    continue
                
                values = line.split('\t')
                if len(values) != len(header):
                    print(f"⚠️ 경고: {line_num}번째 줄의 필드 개수가 맞지 않습니다. 건너뜁니다.")
                    continue
                
                dataset = {}
                for i, field in enumerate(header):
                    value = values[i].strip()
                    # 숫자 필드 변환
                    if field in ['target_center_lat', 'target_center_lon', 'target_resolution']:
                        try:
                            dataset[field] = float(value)
                        except ValueError:
                            raise ValueError(f"{line_num}번째 줄의 {field} 값이 숫자가 아닙니다: {value}")
                    else:
                        dataset[field] = value
                
                datasets.append(dataset)
    else:
        raise ValueError(f"지원하지 않는 파일 형식입니다: {config_path.suffix}")
    
    # 필수 필드 검증
    required_fields = ['dem', 'reference', 'target', 'output', 
                      'target_center_lat', 'target_center_lon', 'target_resolution']
    for i, dataset in enumerate(datasets, 1):
        missing = [f for f in required_fields if f not in dataset]
        if missing:
            raise ValueError(f"데이터셋 {i}번째에 필수 필드가 없습니다: {missing}")
    
    return datasets


def run_batch_processing(config_path):
    """
    배치 처리를 실행합니다.
    
    Args:
        config_path: 배치 설정 파일 경로
    """
    print("="*80)
    print("배치 처리 시작")
    print("="*80)
    
    # 설정 파일 로드
    try:
        datasets = load_batch_config(config_path)
        print(f"✅ 설정 파일 로드 완료: {len(datasets)}개 데이터셋")
    except Exception as e:
        print(f"❌ 설정 파일 로드 실패: {e}")
        traceback.print_exc()
        return
    
    total = len(datasets)
    success_count = 0
    fail_count = 0
    failed_datasets = []
    
    start_time = datetime.now()
    
    # 각 데이터셋 처리
    for idx, dataset in enumerate(datasets, 1):
        print("\n" + "="*80)
        print(f"데이터셋 {idx}/{total}: {dataset['name']}")
        print("="*80)
        print(f"DEM: {dataset['dem']}")
        print(f"Reference: {dataset['reference']}")
        print(f"Target: {dataset['target']}")
        print(f"Output: {dataset['output']}")
        print(f"위도: {dataset['target_center_lat']}, 경도: {dataset['target_center_lon']}, 해상도: {dataset['target_resolution']}m")
        print("-"*80)
        
        # 파일 존재 확인
        missing_files = []
        if not os.path.exists(dataset['dem']):
            missing_files.append(f"DEM: {dataset['dem']}")
        if not os.path.exists(dataset['reference']):
            missing_files.append(f"Reference: {dataset['reference']}")
        if not os.path.exists(dataset['target']):
            missing_files.append(f"Target: {dataset['target']}")
        
        if missing_files:
            print(f"❌ 파일이 존재하지 않습니다:")
            for f in missing_files:
                print(f"   - {f}")
            fail_count += 1
            failed_datasets.append(dataset['name'])
            continue
        
        # 파이프라인 실행
        try:
            run_pipeline(
                dem_path=dataset['dem'],
                reference_path=dataset['reference'],
                target_path=dataset['target'],
                output_dir=dataset['output'],
                target_center_lat=dataset['target_center_lat'],
                target_center_lon=dataset['target_center_lon'],
                target_resolution=dataset['target_resolution']
            )
            
            success_count += 1
            print(f"\n✅ 데이터셋 {idx}/{total} 완료: {dataset['name']}")
            
        except KeyboardInterrupt:
            print(f"\n⚠️ 사용자가 배치 처리를 중단했습니다.")
            print(f"   완료: {success_count}개, 실패: {fail_count}개, 남은 데이터셋: {total - idx}개")
            break
            
        except Exception as e:
            fail_count += 1
            failed_datasets.append(dataset['name'])
            print(f"\n❌ 데이터셋 {idx}/{total} 실패: {dataset['name']}")
            print(f"   오류: {str(e)}")
            print(f"   상세:")
            traceback.print_exc()
            print("\n다음 데이터셋으로 계속 진행합니다...")
            continue
    
    # 최종 결과 요약
    end_time = datetime.now()
    duration = end_time - start_time
    
    print("\n" + "="*80)
    print("배치 처리 완료")
    print("="*80)
    print(f"총 데이터셋: {total}개")
    print(f"성공: {success_count}개")
    print(f"실패: {fail_count}개")
    print(f"소요 시간: {duration}")
    print(f"시작 시간: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"종료 시간: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    if failed_datasets:
        print(f"\n실패한 데이터셋:")
        for name in failed_datasets:
            print(f"   - {name}")
    
    print("="*80)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python run_batch.py <설정파일경로>")
        print("\n예시:")
        print("  python run_batch.py /Users/kyle_kim/Downloads/geometric_correction/batch_config.json")
        sys.exit(1)
    
    config_path = sys.argv[1]
    run_batch_processing(config_path)

