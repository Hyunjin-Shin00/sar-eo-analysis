"""영상 로드 + GUI 미리보기 생성.

processing 전에 호출하여 사용자가 영상을 보고 폴리라인을 그릴 수 있도록 한다.
"""
import os
import sys
import traceback

import numpy as np


def _log_runtime_error(exc, where):
    """frozen 빌드에서 import/runtime 실패를 exe 옆 runtime_error.log 에 누적 기록.

    워커 스레드의 예외는 stdout 캡처가 어려운 경우가 많아 파일 로그로 보존.
    """
    try:
        if getattr(sys, 'frozen', False):
            log_dir = os.path.dirname(sys.executable)
        else:
            log_dir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(log_dir, 'runtime_error.log'), 'a',
                  encoding='utf-8') as f:
            f.write('\n=== ' + where + ' ===\n')
            f.write(f'sys.executable: {sys.executable}\n')
            f.write(f'sys._MEIPASS: {getattr(sys, "_MEIPASS", None)}\n')
            f.write(f'cwd: {os.getcwd()}\n')
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=f)
    except Exception:
        pass


try:
    from PIL import Image
except BaseException as _e:
    _log_runtime_error(_e, 'pipeline.loader: from PIL import Image')
    raise

import ncutils
import tiffutils
from genrgb import gen_rgb

from .io_helpers import detect_file_type, detect_rho_type


def load_image(fin: str, bds_rgb: list | None = None) -> dict:
    """
    Returns:
      {
        'img':       np.ndarray (nb, rows, cols) float32,
        'file_type': 'nc' | 'tif' | 'png' | 'jpg',
        'rho_type':  'rhorc' | 'rhot' | 'unknown',
        'preview':   PIL.Image (RGB, 원본 해상도),
        'waves':     list[float] | None,
        'shape':     (nb, rows, cols),
      }
    """
    file_type = detect_file_type(fin)

    if file_type == 'nc':
        img0 = ncutils.getimage(fin, bip=False)
        try:
            waves = ncutils.readheader(fin).get('waves')
        except Exception:
            waves = None
    elif file_type == 'tif':
        img0 = tiffutils.getraster(fin, None)
        try:
            waves = tiffutils.get_waves_tif(fin)
        except Exception:
            waves = None
    else:  # png/jpg
        _d = Image.open(fin)
        arr = np.array(_d)
        if arr.ndim == 2:
            img0 = arr[np.newaxis, :, :].astype(np.float32) / 255.0
        else:
            img0 = np.transpose(arr, [2, 0, 1])[:3].astype(np.float32) / 255.0
        waves = None

    img0 = img0.astype(np.float32, copy=False)
    nb, nrows, ncols = img0.shape

    if bds_rgb is None:
        if nb >= 3:
            bds_rgb = [2, 1, 0]
        elif nb == 2:
            bds_rgb = [1, 0]
        else:
            bds_rgb = [0]

    # gen_rgb는 ofilepath=None이면 파일로 저장하지 않고 PIL.Image만 반환
    preview = gen_rgb(
        img0, mask=None, linear=1, ofilepath=None,
        bds=bds_rgb, data4alpha=img0[0, :, :],
    )

    return {
        'img':       img0,
        'file_type': file_type,
        'rho_type':  detect_rho_type(fin),
        'preview':   preview,
        'waves':     waves,
        'shape':     (nb, nrows, ncols),
    }
