"""파일 타입 감지, 출력 경로 계산."""
import os
import re


def detect_file_type(fin: str) -> str:
    """Returns 'nc', 'tif', 'png', or 'jpg'."""
    ext = os.path.splitext(fin)[1].lower()
    if ext == '.nc':
        return 'nc'
    if ext in ('.tif', '.tiff'):
        return 'tif'
    if ext == '.png':
        return 'png'
    if ext in ('.jpg', '.jpeg'):
        return 'jpg'
    raise ValueError(f'지원하지 않는 확장자: {ext} ({fin})')


def detect_rho_type(fin: str) -> str:
    """Returns 'rhorc', 'rhot', or 'unknown'."""
    name = os.path.basename(fin).lower()
    if 'rhorc' in name:
        return 'rhorc'
    if 'rhot' in name:
        return 'rhot'
    return 'unknown'


def compute_output_paths(fin: str, output_dir: str | None):
    """원본 basematch_NEW.py의 명명 로직 그대로, output_dir 지정 시 디렉토리만 교체.

    Returns (fin_base, fin_deh_base, fin_aero_base) - 확장자 없는 base 경로들.
    """
    fin_base = re.sub(r'(?<!^)\.([^./\\:]*$)', '', fin)
    fin_deh_base = re.sub(r'_[^_]*$', '_dehSpec', fin_base, count=1)
    fin_aero_base = re.sub(r'_[^_]*$', '_aeroSpec', fin_base, count=1)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        fin_base = os.path.join(output_dir, os.path.basename(fin_base))
        fin_deh_base = os.path.join(output_dir, os.path.basename(fin_deh_base))
        fin_aero_base = os.path.join(output_dir, os.path.basename(fin_aero_base))
    return fin_base, fin_deh_base, fin_aero_base
