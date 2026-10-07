"""TELEPIX Dehazing 메인 파이프라인.

원본 basematch_NEW.py의 __main__ 블록을 함수화한 것.
변경점:
  - print는 유지 (worker에서 builtins.print 가로채기로 GUI 로그에 흘려보냄)
  - progress_fn(pct, stage) 호출
  - custom_basis 파라미터: 사용자 폴리라인에서 추출한 basis 우선 사용
  - 출력 디렉토리 지정 가능
  - msi_20m rhorc의 Pyeongyang 덮어쓰기 버그 수정 (Wonsan1 고정)
"""
import time
import numpy as np

import basematch_sub_NEW as BSNEW
import box_average2 as BA
import ncutils
import tiffutils
from genrgb import gen_rgb
from PIL import Image

from .sensor_config import get_sensor_params
from .io_helpers import detect_file_type, compute_output_paths
from .mem_utils import (
    available_ram_bytes, total_ram_bytes,
    pick_match_tile, pick_boxavg_tile,
)
from .cancel import CancelledError, check as _check_cancel


def _noop_progress(pct, stage):
    pass


class _StageTimer:
    """단계별 소요시간을 누적하고 마지막에 표 형태로 출력."""
    def __init__(self):
        self.records = []  # [(name, seconds)]
        self._t0 = None
        self._name = None

    def start(self, name):
        if self._name is not None:
            self.stop()
        self._name = name
        self._t0 = time.perf_counter()
        print(f'[time] >>> {name} 시작')

    def stop(self):
        if self._name is None:
            return
        dt = time.perf_counter() - self._t0
        self.records.append((self._name, dt))
        print(f'[time] <<< {self._name}: {dt:.2f}s')
        self._name = None
        self._t0 = None

    def summary(self):
        if self._name is not None:
            self.stop()
        total = sum(s for _, s in self.records) or 1e-9
        print('')
        print('=' * 52)
        print(f'{"단계":<32}{"시간(s)":>10}{"비율":>10}')
        print('-' * 52)
        for name, sec in self.records:
            print(f'{name:<32}{sec:>10.2f}{sec/total*100:>9.1f}%')
        print('-' * 52)
        print(f'{"TOTAL":<32}{total:>10.2f}{100.0:>9.1f}%')
        print('=' * 52)


def run_dehazing(
    fin: str,
    sensor: str,
    output_dir: str | None = None,
    custom_basis: np.ndarray | None = None,
    custom_u: np.ndarray | None = None,
    basis_id: str | None = None,
    progress_fn=_noop_progress,
    cancel_check=None,
) -> dict:
    """Returns dict with keys:
        deh_path, aero_path, preview_ori, preview_deh, preview_aero
    """
    timer = _StageTimer()

    # ── 1. 파일 로드 ────────────────────────────────────────────
    timer.start('1. 파일 로드')
    file_type = detect_file_type(fin)
    if file_type == 'nc':
        img0 = ncutils.getimage(fin, bip=False)
    elif file_type == 'tif':
        img0 = tiffutils.getraster(fin, None)
    elif file_type in ('png', 'jpg'):
        _d = Image.open(fin)
        arr = np.array(_d)
        if arr.ndim == 2:
            img0 = arr[np.newaxis, :, :].astype(np.float32) / 255.0
        else:
            img0 = np.transpose(arr, [2, 0, 1])[:3].astype(np.float32) / 255.0
    img0 = img0.astype(np.float32, copy=False)
    nb, nrows, ncols = img0.shape
    print(f'입력 영상 로드: shape=(nb={nb}, rows={nrows}, cols={ncols}) type={file_type}')
    progress_fn(5, '파일 로드 완료')
    timer.stop()
    _check_cancel(cancel_check)

    # ── 2. 센서 설정 ───────────────────────────────────────────
    timer.start('2. 센서 설정')
    bases, u, bds, bds_rgb, bxsize = get_sensor_params(sensor, nb, basis_id=basis_id)

    # 사용자 u override (있으면 센서 기본 u 대신 사용)
    if custom_u is not None:
        cu = np.asarray(custom_u, np.float32)
        if cu.shape[0] == nb:
            u = cu[bds]
        elif cu.shape[0] == len(bds):
            u = cu
        else:
            raise ValueError(
                f'custom_u shape {cu.shape} != nb({nb}) / len(bds)({len(bds)})'
            )
        print(f'사용자 u 사용: shape={u.shape}')

    u0_full = u  # rhorc 가정, u_norm 그대로 사용 (저장 단계 aerosol 계산)

    if custom_basis is not None:
        # 폴리라인 픽셀 스펙트럼을 basis로 사용
        if custom_basis.ndim != 2:
            raise ValueError(f'custom_basis shape (N, nb) 기대, 실제: {custom_basis.shape}')
        if custom_basis.shape[1] == nb:
            custom_basis = custom_basis[:, bds]
        elif custom_basis.shape[1] != len(bds):
            raise ValueError(
                f'custom_basis 채널({custom_basis.shape[1]}) != '
                f'센서 nb({nb}) / bds({len(bds)})'
            )
        bases = custom_basis.astype(np.float32, copy=False)
        print(f'폴리라인 basis 사용: K={len(bases)} pixels')
    else:
        print(f'센서 기본 basis 사용 ({sensor}): K={len(bases)}')

    # bds 가 연속 정수면 slice (view), 아니면 fancy indexing (copy).
    # 현재 모든 센서가 0..N-1 연속이라 slice 한 번으로 메모리 절약.
    if len(bds) > 0 and bds == list(range(bds[0], bds[0] + len(bds))):
        img = img0[bds[0]:bds[0] + len(bds)]   # view, no copy
        print(f'[mem] img band-subset: slice (no copy), nb={len(bds)}')
    else:
        img = img0[bds, :, :]
        print(f'[mem] img band-subset: fancy index (copy), nb={len(bds)}')
    progress_fn(10, '센서 설정')
    timer.stop()
    _check_cancel(cancel_check)

    # ── 3. 스펙트럼 매칭 ───────────────────────────────────────
    timer.start('3. 스펙트럼 매칭')
    u_img = np.broadcast_to(u[:, None, None], (len(bds), nrows, ncols))
    topk = 3
    K = len(bases)

    # ── 가용 RAM 측정 + 동적 타일 사이즈 결정 ──
    ram_total = total_ram_bytes()
    ram_avail = available_ram_bytes()
    match_budget = int(ram_avail * 0.30)  # 가용 RAM의 30%만 한 타일 피크에 할당
    tile_rows, tile_cols = pick_match_tile(K, ncols, nrows, match_budget)
    print(
        f'[mem] RAM total={ram_total/1024**3:.2f}GiB '
        f'avail={ram_avail/1024**3:.2f}GiB '
        f'match_budget={match_budget/1024**3:.2f}GiB'
    )
    print(
        f'스펙트럼 매칭 시작: topk={topk}, K={K}, '
        f'ncols={ncols}, nrows={nrows} '
        f'-> tile_rows={tile_rows}, tile_cols={tile_cols}'
    )
    # 메모리 lean 버전: 매칭 결과 best_basis/alpha_star/dist2 풀사이즈 배열을
    # 미리 할당하지 않고, 타일 처리 중에 곧바로 reconR0(=top-k 평균의 band-0)을
    # 누적해서 (R, C) 단일 배열만 반환한다.
    try:
        reconR0 = BSNEW.compute_reconR0_tiled(
            img, bases, u_img,
            topk=topk, tile_rows=tile_rows, tile_cols=tile_cols,
            cancel_check=cancel_check,
        )
    except RuntimeError as e:
        if str(e) == 'CANCELLED':
            raise CancelledError('사용자가 처리를 중지했습니다')
        raise
    c_star = img[0] - reconR0
    del reconR0
    progress_fn(50, '스펙트럼 매칭')
    timer.stop()
    _check_cancel(cancel_check)

    # ── 4. 공간 평균 ───────────────────────────────────────────
    timer.start('4. 공간 평균')
    thresh = 0.15
    maskvalid = c_star < thresh
    mask = ~maskvalid

    # 박스 평균도 동적 RAM 예산으로 타일 사이즈 결정
    ba_budget = int(available_ram_bytes() * 0.30)
    ba_tile = pick_boxavg_tile(ncols, nrows, ba_budget)
    print(
        f'공간 평균 시작: boxsize={bxsize}, tile_size={ba_tile}, '
        f'budget={ba_budget/1024**3:.2f}GiB'
    )
    try:
        ave, _pct = BA.wrap_boxaverage_tiled(
            c_star, maskvalid,
            boxsize=bxsize, q=5,
            tile_size=ba_tile, n_workers=4,
            cancel_check=cancel_check,
        )
    except RuntimeError as e:
        if str(e) == 'CANCELLED':
            raise CancelledError('사용자가 처리를 중지했습니다')
        raise
    ave = ave.astype(np.float32)
    ave[mask] = np.nan
    ave = BA.fill_nearest(ave)
    progress_fn(80, '공간 평균 완료')
    timer.stop()
    _check_cancel(cancel_check)

    # ── 5. 에어로졸 스펙트럼 계산 ──────────────────────────────
    timer.start('5. 에어로졸 계산')
    # u0_full 길이 = len(bds). msi_10m처럼 4밴드 입력은 동일하게 매칭.
    aer = np.array([ave * float(_) for _ in u0_full.astype(np.float32)])
    progress_fn(90, '에어로졸 계산')
    timer.stop()
    _check_cancel(cancel_check)  # 저장 시작 전 마지막 체크 (저장 중에는 미체크)

    # ── 6. 결과 파일 저장 ──────────────────────────────────────
    timer.start('6. 결과 파일 저장')
    fin_base, fin_deh_base, fin_aero_base = compute_output_paths(fin, output_dir)

    waves = None
    deh_path = None
    aero_path = None

    if file_type == 'nc':
        try:
            waves = ncutils.readheader(fin).get('waves')
        except Exception:
            waves = None
        aero_path = fin_aero_base + '.nc'
        deh_path = fin_deh_base + '.nc'
        ncutils.writeSpecData2file_2nc(
            aer, aero_path, waves=waves, slope=1./65535, offset=-0.1)
        ncutils.writeSpecData2file_2nc(
            img0 - aer, deh_path, waves=waves, slope=1./65535, offset=-0.1)
    elif file_type == 'tif':
        try:
            waves = tiffutils.get_waves_tif(fin)
        except Exception:
            waves = None
        aero_path = fin_aero_base + '.tif'
        deh_path = fin_deh_base + '.tif'
        tiffutils.writeData_to_geotif(
            aer, fin, aero_path, waves=waves, slope=1./65535, offset=-0.1)
        tiffutils.writeData_to_geotif(
            img0 - aer, fin, deh_path, waves=waves, slope=1./65535, offset=-0.1)
    # png/jpg 입력은 결과 파일 저장 안 함 (미리보기만 반환)
    progress_fn(95, '파일 저장 완료')
    timer.stop()

    # ── 7. 미리보기 PNG 생성 ───────────────────────────────────
    timer.start('7. 미리보기 PNG')
    preview_ori = gen_rgb(
        img0, mask=None, linear=1, ofilepath=None,
        bds=bds_rgb, data4alpha=img0[0, :, :],
    )
    preview_deh = gen_rgb(
        img0 - aer, mask=None, linear=1,
        ofilepath=fin_deh_base if file_type in ('nc', 'tif') else None,
        bds=bds_rgb, data4alpha=img0[0, :, :],
    )
    preview_aero = gen_rgb(
        aer, mask=None, linear=1,
        ofilepath=fin_aero_base if file_type in ('nc', 'tif') else None,
        bds=bds_rgb, data4alpha=img0[0, :, :],
    )
    progress_fn(100, '완료')
    timer.stop()
    timer.summary()

    return {
        'deh_path':     deh_path,
        'aero_path':    aero_path,
        'preview_ori':  preview_ori,
        'preview_deh':  preview_deh,
        'preview_aero': preview_aero,
    }


if __name__ == '__main__':
    # CLI 단독 검증용
    import argparse, sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'vendor'))

    p = argparse.ArgumentParser()
    p.add_argument('--fin', required=True)
    p.add_argument('--sensor', required=True, choices=['sky', 'msi_20m', 'msi_10m'])
    p.add_argument('--output-dir', default=None)
    args = p.parse_args()

    result = run_dehazing(
        args.fin, args.sensor, args.output_dir,
        progress_fn=lambda p, s: print(f'  [{p:3d}%] {s}'),
    )
    print('\n=== 결과 ===')
    for k, v in result.items():
        if hasattr(v, 'size'):
            print(f'  {k}: PIL.Image size={v.size}')
        else:
            print(f'  {k}: {v}')
