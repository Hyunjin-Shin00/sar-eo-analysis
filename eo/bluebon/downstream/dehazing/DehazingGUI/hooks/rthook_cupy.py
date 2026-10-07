"""PyInstaller 런타임 hook: CuPy가 번들된 CUDA DLL을 찾도록 환경변수 설정.

문제:
  - conda-forge cupy 는 cudatoolkit (Library\\bin\\*.dll) 에 의존.
  - PyInstaller spec 에서 위 DLL 들을 _MEIPASS 루트에 함께 번들했다.
  - 그러나 CuPy 일부 코드 경로가 CUDA_PATH 환경변수를 가정한 채
    `os.path.join(CUDA_PATH, 'bin')` 식으로 호출하다 None 이 들어가면 TypeError.

해결:
  - CUDA_PATH 가 비어있으면 _MEIPASS 로 설정.
  - 그리고 _MEIPASS 와 _MEIPASS\\bin 을 PATH 와 dll 검색 디렉토리에 추가.
"""
import os
import sys


if getattr(sys, 'frozen', False):
    base = sys._MEIPASS  # type: ignore[attr-defined]

    # CUDA_PATH 가 비어있을 때만 채움 (시스템 CUDA 가 있으면 그걸 우선)
    if not os.environ.get('CUDA_PATH'):
        os.environ['CUDA_PATH'] = base
    # CUDA_HOME 도 일부 라이브러리가 참조
    if not os.environ.get('CUDA_HOME'):
        os.environ['CUDA_HOME'] = base
    # CuPy 는 conda 환경 헤더를 _get_conda_cuda_path() 로 찾는데
    # 그게 CONDA_PREFIX 환경변수에 의존한다. 번들에선 비어있으니 채워준다.
    # cupy 는 <CONDA_PREFIX>\Library\include 에서 CUDA 헤더를 찾으므로
    # spec 에서 그 경로에 cudatoolkit 헤더를 묶어두었다.
    if not os.environ.get('CONDA_PREFIX'):
        os.environ['CONDA_PREFIX'] = base

    # CUB reduction 가속 명시 (CuPy 기본값이지만 미래 변경 대비 고정).
    # 비우면 CCCL/libcudacxx 헤더 컴파일을 회피할 수 있지만 reduction 속도 손실.
    # 13.x 는 FP8 E8M0 이슈가 없어 CUB 활성으로 안전하게 속도 챙김.
    if not os.environ.get('CUPY_ACCELERATORS'):
        os.environ['CUPY_ACCELERATORS'] = 'cub'

    # NOTE: DLL 검색 경로 등록 (AddDllDirectory) 은 rthook_dll_search.py 가
    # 일괄 처리한다. 여기서 PATH 를 조작하면 SetDefaultDllDirectories 로
    # 잠근 정책을 우회해 시스템의 다른 버전 DLL 을 다시 끌어들일 수 있어
    # 의도적으로 제거.
