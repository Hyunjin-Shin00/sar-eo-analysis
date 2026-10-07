"""Dehazing 처리용 QThread 워커 (배치 큐 지원).

- 단일 파일도 1원소 리스트로 처리해서 코드 경로 통합.
- vendor의 print() 출력을 GUI 로그로 흘려보내기 위해 builtins.print를 가로챔.
- 파일 사이에 CuPy MemoryPool 명시 해제 — 큰 영상 연속 처리 시 OOM 방지.

basis_id 종류 / basis_payload 형식:
  - 'polyline'    : {'clear_verts': [...], 'hazy_verts': [...] | None}
                    영상에서 즉시 bases / u_l / u_h / u_norm 추출
                    (다중 파일 선택 시에는 control_panel 가드로 진입 차단)
  - 'user:<uuid>' : {'bases': ndarray (K,nb), 'u': ndarray (nb,) | None}
                    pre-resolved
  - 'builtin:...' : None — runner 가 sensor_config 에서 직접 로드
"""
import builtins
import os
import traceback
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal


class DehazingWorker(QThread):
    log_signal      = pyqtSignal(str)
    progress_signal = pyqtSignal(int, str)   # overall pct, stage label
    # 마지막 성공 파일의 결과 (preview/compare 활성용). 한 번도 성공 없으면 미발신.
    finished_signal = pyqtSignal(dict)
    # 파이프라인 import 실패 등 치명적 오류 전용. 파일별 실패는 file_failed_signal.
    error_signal    = pyqtSignal(str)
    cancelled_signal = pyqtSignal()

    # 배치 진행 시그널
    file_started_signal   = pyqtSignal(int, int, str)         # idx, total, path
    file_finished_signal  = pyqtSignal(int, int, str, dict)   # idx, total, path, result
    file_failed_signal    = pyqtSignal(int, int, str, str)    # idx, total, path, error
    batch_finished_signal = pyqtSignal(int, int, int)         # total, ok, failed

    def __init__(self, fins: list[str], sensor: str, output_dir,
                 basis_id: str, basis_payload,
                 cached_img: np.ndarray | None = None, parent=None):
        super().__init__(parent)
        # 단일/리스트 모두 허용
        if isinstance(fins, str):
            self.fins = [fins]
        else:
            self.fins = list(fins)
        self.sensor = sensor
        self.output_dir = output_dir
        self.basis_id = basis_id
        self.basis_payload = basis_payload
        self.cached_img = cached_img  # 첫 파일에 한해 폴리라인 추출용 재활용

    def _overall_pct(self, idx: int, file_pct: int) -> int:
        total = max(1, len(self.fins))
        return int((idx * 100 + max(0, min(100, file_pct))) / total)

    def _resolve_basis_for_file(self, fin: str):
        """현재 파일에 대해 (custom_basis, custom_u, runner_basis_id) 결정.

        폴리라인 모드는 단일 파일 한정이므로 첫 파일에서만 동작. 다중 파일은
        control_panel 가드로 진입 자체가 차단되지만 방어적으로 한번 더 검사.
        """
        from pipeline.basis_extractor import extract_user_basis_payload
        from pipeline.loader import load_image

        custom_basis = None
        custom_u = None
        runner_basis_id: str | None = None

        if self.basis_id == 'polyline':
            payload = self.basis_payload or {}
            clear_verts = payload.get('clear_verts')
            hazy_verts  = payload.get('hazy_verts')
            if not clear_verts or len(clear_verts) < 2:
                raise ValueError('Clear polyline 정점이 2개 이상 필요합니다')
            img = self.cached_img if self.cached_img is not None \
                else load_image(fin)['img']
            bp = extract_user_basis_payload(
                img, clear_verts, hazy_verts, max_samples=500
            )
            custom_basis = bp['bases']
            custom_u = bp['u_norm']
            u_note = ('+ u 직접 추출' if custom_u is not None
                      else '(u 는 센서 기본값 사용)')
            self.log_signal.emit(
                f'폴리라인 basis 추출: K={len(custom_basis)} 픽셀 {u_note}'
            )
        elif isinstance(self.basis_id, str) and self.basis_id.startswith('user:'):
            payload = self.basis_payload or {}
            arr = payload.get('bases')
            if not isinstance(arr, np.ndarray) or arr.ndim != 2:
                raise ValueError('user basis payload bases (K, nb) ndarray 필요')
            custom_basis = arr.astype(np.float32, copy=False)
            u_payload = payload.get('u')
            if isinstance(u_payload, np.ndarray):
                custom_u = u_payload.astype(np.float32, copy=False)
                u_note = '+ 저장된 u 사용'
            else:
                u_note = '(u 는 센서 기본값 사용)'
            self.log_signal.emit(
                f'저장된 사용자 basis 사용: K={len(custom_basis)}, '
                f'nb={custom_basis.shape[1]} {u_note}'
            )
        else:
            # builtin
            runner_basis_id = self.basis_id
            self.log_signal.emit(f'기본 basis 사용: {self.basis_id}')
        return custom_basis, custom_u, runner_basis_id

    @staticmethod
    def _free_gpu_memory():
        """파일 사이에 GPU 메모리 풀 해제. CuPy 없으면 무시."""
        try:
            import cupy as cp
            cp.get_default_memory_pool().free_all_blocks()
            cp.get_default_pinned_memory_pool().free_all_blocks()
        except Exception:
            pass

    def run(self):
        _orig_print = builtins.print

        def _captured_print(*args, **kwargs):
            try:
                msg = ' '.join(str(a) for a in args)
                self.log_signal.emit(msg)
            except Exception:
                pass

        builtins.print = _captured_print

        total = len(self.fins)
        ok = 0
        failed = 0
        last_result = None

        try:
            from pipeline.runner import run_dehazing
            from pipeline.cancel import CancelledError
        except Exception as e:
            tb = traceback.format_exc()
            builtins.print = _orig_print
            self.error_signal.emit(f'{type(e).__name__}: {e}\n\n{tb}')
            return

        cancelled = False
        try:
            for i, fin in enumerate(self.fins):
                if self.isInterruptionRequested():
                    cancelled = True
                    break
                self.file_started_signal.emit(i, total, fin)
                self.log_signal.emit(
                    f'\n=== [{i+1}/{total}] {os.path.basename(fin)} ==='
                )
                try:
                    custom_basis, custom_u, runner_basis_id = \
                        self._resolve_basis_for_file(fin)

                    def _progress(p, s, _i=i):
                        self.progress_signal.emit(
                            self._overall_pct(_i, p),
                            f'[{_i+1}/{total}] {s}',
                        )

                    result = run_dehazing(
                        fin, self.sensor, self.output_dir,
                        custom_basis=custom_basis,
                        custom_u=custom_u,
                        basis_id=runner_basis_id,
                        progress_fn=_progress,
                        cancel_check=lambda: self.isInterruptionRequested(),
                    )
                    ok += 1
                    last_result = result
                    self.file_finished_signal.emit(i, total, fin, result)
                except CancelledError:
                    cancelled = True
                    break
                except Exception as e:
                    failed += 1
                    err_msg = f'{type(e).__name__}: {e}'
                    self.log_signal.emit(
                        f'[ERROR] {os.path.basename(fin)}: {err_msg}\n'
                        f'{traceback.format_exc()}'
                    )
                    self.file_failed_signal.emit(i, total, fin, err_msg)
                finally:
                    # 다음 파일 진입 전 GPU 메모리 풀 비움 (OOM 방지)
                    self._free_gpu_memory()
        finally:
            builtins.print = _orig_print

        # 최종 시그널 — 순서가 중요:
        #  1) 마지막 성공 결과 (preview 활성)
        #  2) batch summary (상태바 갱신)
        #  3) cancelled (있으면)
        if last_result is not None:
            self.finished_signal.emit(last_result)
        self.batch_finished_signal.emit(total, ok, failed)
        if cancelled:
            self.log_signal.emit('[중지됨] 사용자가 처리를 중지했습니다')
            self.cancelled_signal.emit()
