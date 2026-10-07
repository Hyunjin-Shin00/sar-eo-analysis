"""PyInstaller 런타임 hook: 번들에서 GDAL_DATA / PROJ_LIB 환경변수 설정.

conda-forge / pip wheel / OSGeo4W 등 GDAL 배포에 따라 데이터 디렉토리 위치가
제각각이라 후보 경로들을 탐색하고, 그래도 못 찾으면 번들 트리를 한 번 walk해서
찾아낸다.
"""
import os
import sys


def _first_existing(*paths):
    for p in paths:
        if p and os.path.isdir(p):
            return p
    return None


def _find_dir_with_file(root, filename, max_depth=6):
    root = os.path.abspath(root)
    base_depth = root.count(os.sep)
    for dirpath, _dirnames, filenames in os.walk(root):
        if dirpath.count(os.sep) - base_depth > max_depth:
            continue
        if filename in filenames:
            return dirpath
    return None


if getattr(sys, 'frozen', False):
    base = sys._MEIPASS  # type: ignore[attr-defined]

    # 오프라인 환경: PROJ가 cdn.proj.org에서 grid shift 파일을 받아오려는 시도를 차단
    os.environ.setdefault('PROJ_NETWORK', 'OFF')
    # 일부 GDAL 빌드가 참조하는 추가 변수들
    os.environ.setdefault('GDAL_HTTP_TIMEOUT', '1')
    os.environ.setdefault('GDAL_HTTP_CONNECTTIMEOUT', '1')

    # GDAL_DATA: gdal_datums.csv 또는 gt_datum.csv가 들어 있는 디렉토리
    gdal_data = _first_existing(
        os.path.join(base, 'osgeo', 'data', 'gdal'),
        os.path.join(base, 'Library', 'share', 'gdal'),
        os.path.join(base, 'share', 'gdal'),
        os.path.join(base, 'gdal-data'),
    )
    if gdal_data is None:
        gdal_data = _find_dir_with_file(base, 'gdal_datums.csv') \
                 or _find_dir_with_file(base, 'gt_datum.csv') \
                 or _find_dir_with_file(base, 'pcs.csv')
    if gdal_data:
        os.environ.setdefault('GDAL_DATA', gdal_data)

    # PROJ_LIB: proj.db가 들어 있는 디렉토리
    proj_dir = _first_existing(
        os.path.join(base, 'proj'),
        os.path.join(base, 'osgeo', 'data', 'proj'),
        os.path.join(base, 'Library', 'share', 'proj'),
        os.path.join(base, 'share', 'proj'),
    )
    if proj_dir is None:
        proj_dir = _find_dir_with_file(base, 'proj.db')
    if proj_dir:
        os.environ.setdefault('PROJ_LIB', proj_dir)
        os.environ.setdefault('PROJ_DATA', proj_dir)  # PROJ ≥ 9

    # vendor 디렉토리를 sys.path에 추가 (main.py에서도 처리하지만 안전망)
    vendor = os.path.join(base, 'vendor')
    if os.path.isdir(vendor) and vendor not in sys.path:
        sys.path.insert(0, vendor)
