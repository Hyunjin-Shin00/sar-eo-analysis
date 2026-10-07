"""실행 시점의 가용 RAM을 측정하고 안전한 타일 크기를 산정.

psutil이 있으면 그것을, 없으면 Windows API(GlobalMemoryStatusEx) 또는
/proc/meminfo를 사용하고, 모두 실패하면 보수적인 2GiB로 폴백한다.
"""
import os
import sys


def available_ram_bytes() -> int:
    """현재 가용 RAM(bytes). 알 수 없으면 보수적 추정."""
    try:
        import psutil
        return int(psutil.virtual_memory().available)
    except Exception:
        pass

    if sys.platform.startswith('win'):
        try:
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [
                    ('dwLength', ctypes.c_ulong),
                    ('dwMemoryLoad', ctypes.c_ulong),
                    ('ullTotalPhys', ctypes.c_ulonglong),
                    ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong),
                    ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong),
                    ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('sullAvailExtendedVirtual', ctypes.c_ulonglong),
                ]

            ms = _MS()
            ms.dwLength = ctypes.sizeof(_MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                return int(ms.ullAvailPhys)
        except Exception:
            pass

    try:
        with open('/proc/meminfo') as f:
            for line in f:
                if line.startswith('MemAvailable:'):
                    return int(line.split()[1]) * 1024
    except Exception:
        pass

    return 2 * 1024 ** 3


def total_ram_bytes() -> int:
    try:
        import psutil
        return int(psutil.virtual_memory().total)
    except Exception:
        pass
    if sys.platform.startswith('win'):
        try:
            import ctypes

            class _MS(ctypes.Structure):
                _fields_ = [
                    ('dwLength', ctypes.c_ulong),
                    ('dwMemoryLoad', ctypes.c_ulong),
                    ('ullTotalPhys', ctypes.c_ulonglong),
                    ('ullAvailPhys', ctypes.c_ulonglong),
                    ('ullTotalPageFile', ctypes.c_ulonglong),
                    ('ullAvailPageFile', ctypes.c_ulonglong),
                    ('ullTotalVirtual', ctypes.c_ulonglong),
                    ('ullAvailVirtual', ctypes.c_ulonglong),
                    ('sullAvailExtendedVirtual', ctypes.c_ulonglong),
                ]

            ms = _MS()
            ms.dwLength = ctypes.sizeof(_MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms)):
                return int(ms.ullTotalPhys)
        except Exception:
            pass
    return 4 * 1024 ** 3


def pick_match_tile(K: int, ncols: int, nrows: int, ram_budget: int) -> tuple:
    """스펙트럼 매칭 단계의 안전한 (tile_rows, tile_cols)를 결정.

    한 타일의 피크 메모리 ~= 10 * K * tile_rows * tile_cols * 4 byte
    (dots/base_diff2/num/Vnorm2/pos/alpha_k/dist2 + 마진)
    """
    per_pix_bytes = 10 * max(1, K) * 4
    max_pixels = max(64 * 64, ram_budget // per_pix_bytes)

    # numpy 벡터화 효율을 위해 가로를 우선 키운다.
    tile_cols = min(ncols, 4096)
    tile_rows = min(nrows, max(32, max_pixels // tile_cols))

    if tile_rows < 32:
        # 가로를 줄여서라도 최소 세로 32 확보
        tile_cols = max(256, int((max_pixels / 64) ** 0.5))
        tile_cols = min(ncols, tile_cols)
        tile_rows = max(32, max_pixels // max(1, tile_cols))

    return int(tile_rows), int(tile_cols)


def pick_boxavg_tile(ncols: int, nrows: int, ram_budget: int) -> int:
    """공간 평균 단계의 정사각 타일 크기."""
    per_pix_bytes = 6 * 4  # 동시에 상주하는 float32 배열 약 6개
    max_pixels = max(512 * 512, ram_budget // per_pix_bytes)
    tile = int(max_pixels ** 0.5)
    return int(max(1024, min(tile, 8192, max(ncols, nrows))))
