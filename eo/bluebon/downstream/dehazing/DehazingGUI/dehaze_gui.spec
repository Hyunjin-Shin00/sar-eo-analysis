# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: Windows 10 폴더 번들 빌드."""
import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None

# osgeo / netCDF4 데이터/바이너리/숨은 import 수집
datas, binaries, hiddenimports = collect_all('osgeo')
try:
    datas += collect_data_files('netCDF4')
except Exception:
    pass

# PIL (Pillow): 의존 DLL 일부가 자동 분석에서 누락되는 케이스가 있어
# 명시적으로 전체 수집. standalone dist 보증을 위해.
try:
    d_pil, b_pil, h_pil = collect_all('PIL')
    datas += d_pil; binaries += b_pil; hiddenimports += h_pil
    print(f'[spec] PIL: +{len(d_pil)} datas, +{len(b_pil)} binaries')
except Exception as e:
    print(f'[spec] collect_all(PIL) failed: {e}')

# PyQt5: 플러그인/Qt5 DLL 누락 케이스 방지를 위해 전체 수집.
try:
    d_qt, b_qt, h_qt = collect_all('PyQt5')
    datas += d_qt; binaries += b_qt; hiddenimports += h_qt
    print(f'[spec] PyQt5: +{len(d_qt)} datas, +{len(b_qt)} binaries')
except Exception as e:
    print(f'[spec] collect_all(PyQt5) failed: {e}')

# CuPy (선택). 빌드 머신에 cupy가 설치돼 있으면 함께 번들. 없으면 무시.
# 버전 가드: 타깃 GPU (Quadro M6000, Maxwell sm_52) 호환을 위해 13.x 강제.
# 14.x 가 잡히면 FP8 E8M0 incomplete-type 으로 NVRTC JIT 가 실패한다.
try:
    import cupy as _cupy_check
    _major = int(_cupy_check.__version__.split('.')[0])
    if _major != 13:
        raise SystemExit(
            f'[spec] FATAL: cupy {_cupy_check.__version__} detected; '
            'this build requires cupy 13.x (see environment.yml). '
            'Recreate the conda env: conda env remove -n dehaze_gui && '
            'conda env create -f environment.yml'
        )
    print(f'[spec] cupy version check OK: {_cupy_check.__version__}')
    d_cp, b_cp, h_cp = collect_all('cupy')
    datas += d_cp; binaries += b_cp; hiddenimports += h_cp
    try:
        d_cx, b_cx, h_cx = collect_all('cupy_backends')
        datas += d_cx; binaries += b_cx; hiddenimports += h_cx
    except Exception:
        pass
    try:
        d_fa, b_fa, h_fa = collect_all('fastrlock')
        datas += d_fa; binaries += b_fa; hiddenimports += h_fa
    except Exception:
        pass

    # conda 환경의 Library\bin 에서 CUDA 런타임 DLL 수집.
    # conda-forge cupy 가 의존하는 cudatoolkit 의 DLL 들이 여기 있다.
    import glob
    cuda_dll_patterns = [
        'cudart64_*.dll',
        'nvrtc64_*.dll', 'nvrtc-builtins64_*.dll',
        'cublas64_*.dll', 'cublasLt64_*.dll',
        'curand64_*.dll', 'cusolver64_*.dll', 'cusolverMg64_*.dll',
        'cusparse64_*.dll', 'cufft64_*.dll', 'cufftw64_*.dll',
        'nvjitlink_*.dll', 'nvJitLink_*.dll',
        'cudnn*.dll', 'nccl*.dll',
        'nvToolsExt64_*.dll', 'nvtoolsext*.dll',
        'cccl*.dll',
    ]
    cuda_bin_dirs = []
    # conda env 의 Library\bin
    env_bin = os.path.join(sys.prefix, 'Library', 'bin')
    if os.path.isdir(env_bin):
        cuda_bin_dirs.append(env_bin)
    # NVIDIA Toolkit 별도 설치 시 (CUDA_PATH)
    cuda_path_env = os.environ.get('CUDA_PATH')
    if cuda_path_env and os.path.isdir(os.path.join(cuda_path_env, 'bin')):
        cuda_bin_dirs.append(os.path.join(cuda_path_env, 'bin'))

    cuda_dll_count = 0
    for d in cuda_bin_dirs:
        for pat in cuda_dll_patterns:
            for path in glob.glob(os.path.join(d, pat)):
                binaries.append((path, '.'))
                cuda_dll_count += 1
    print(f'[spec] cupy bundled (+{cuda_dll_count} CUDA DLLs from {cuda_bin_dirs})')

    # CuPy NVRTC JIT 컴파일에 필요한 CUDA 헤더 (<conda_env>\Library\include).
    # 번들 후엔 runtime hook 이 CONDA_PREFIX = _MEIPASS 로 설정해
    # cupy 가 <_MEIPASS>\Library\include 에서 찾도록 한다.
    conda_include = os.path.join(sys.prefix, 'Library', 'include')
    inc_count = 0
    if os.path.isdir(conda_include):
        # CUDA 헤더 트리만 선별해서 묶어 빌드 크기 절감
        cuda_include_targets = [
            'cuda', 'cuda.h', 'cuda_*.h', 'cuda_runtime.h',
            'cuda_runtime_api.h', 'cuda_fp16*', 'cuda_bf16*',
            'cooperative_groups', 'cooperative_groups.h',
            'crt', 'cub', 'thrust', 'nv', 'cuComplex.h',
            'driver_types.h', 'driver_functions.h',
            'device_types.h', 'host_defines.h', 'host_config.h',
            'vector_types.h', 'vector_functions.h', 'vector_functions.hpp',
            'sm_*.h', 'sm_*.hpp',
            'channel_descriptor.h', 'texture_types.h', 'surface_types.h',
            'texture_indirect_functions.h', 'surface_indirect_functions.h',
            'texture_fetch_functions.h', 'surface_functions.h',
            'builtin_types.h', 'library_types.h',
            'math_constants.h', 'math_functions.h', 'math_functions.hpp',
            'common_functions.h', 'common_types.h',
            'device_atomic_functions.h', 'device_atomic_functions.hpp',
            'device_double_functions.h', 'device_functions.h',
            'nvrtc.h', 'nvfunctional',
            'nvml.h', 'nvtx3', 'nvToolsExt*.h',
            'cublas*.h', 'curand*.h', 'cufft*.h',
            'cusolver*.h', 'cusparse*.h',
            'cuda_awbarrier*.h', 'cuda_pipeline*.h',
            'cuda_*.hpp',
        ]
        for pat in cuda_include_targets:
            for path in glob.glob(os.path.join(conda_include, pat)):
                rel = os.path.relpath(path, conda_include)
                dest_dir = os.path.join('Library', 'include',
                                        os.path.dirname(rel) or '.')
                if os.path.isdir(path):
                    # 디렉토리 전체 재귀 수집
                    for root, _dn, files in os.walk(path):
                        rel_dir = os.path.relpath(root, conda_include)
                        dd = os.path.join('Library', 'include', rel_dir)
                        for fn in files:
                            datas.append((os.path.join(root, fn), dd))
                            inc_count += 1
                else:
                    datas.append((path, dest_dir))
                    inc_count += 1
        print(f'[spec] CUDA headers bundled: {inc_count} files from {conda_include}')
    else:
        print(f'[spec] WARNING: {conda_include} not found, NVRTC may fail')
except Exception as e:
    print(f'[spec] cupy not bundled: {e}')

# vendor 모듈을 sys.path에 두고 패키징
datas += [
    ('vendor', 'vendor'),
    ('assets', 'assets'),
]

hiddenimports += [
    'scipy.interpolate',
    'scipy.interpolate._rbfinterp',
    'scipy.ndimage',
    'skimage.util',
    'netCDF4',
    'psutil',
]

a = Analysis(
    ['main.py'],
    pathex=['.', 'vendor'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[
        'hooks/rthook_dll_search.py',  # 반드시 맨 앞: DLL 검색 정책 잠금
        'hooks/rthook_gdal.py',
        'hooks/rthook_cupy.py',
    ],
    excludes=['tkinter', 'tornado', 'IPython', 'jupyter', 'pytest', 'matplotlib', 'rasterio'],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DehazingGUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,  # TODO: 디버깅 끝나면 False로 복귀
    icon=os.path.join('assets', 'icon.ico') if os.path.isfile(os.path.join('assets', 'icon.ico')) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name='DehazingGUI',
)
