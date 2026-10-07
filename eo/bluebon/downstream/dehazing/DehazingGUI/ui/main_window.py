"""MainWindow: 좌측 ImageViewer + 우측 ControlPanel + 하단 상태바."""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QPushButton, QButtonGroup, QProgressBar, QLabel, QMessageBox,
)

from .image_viewer import ImageViewer
from .control_panel import ControlPanel
from .worker import DehazingWorker
from .compare_window import CompareDialog


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('TELEPIX Dehazing')
        self.resize(1600, 900)

        self._loaded = None      # load_image() 결과 캐시
        self._loaded_path = None # 위 캐시의 원본 파일 경로
        self._worker = None
        self._last_result = None # 마지막 dehazing 결과 dict (preview_* 포함)
        self._compare_dialogs = []

        self._build_ui()
        self._connect()

    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)

        # 좌측: 결과 토글 버튼 + ImageViewer
        left = QWidget()
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(2)

        top_bar = QHBoxLayout()
        self.btn_ori  = QPushButton('원본')
        self.btn_deh  = QPushButton('Dehazing')
        self.btn_aero = QPushButton('에어로졸')
        for b in (self.btn_ori, self.btn_deh, self.btn_aero):
            b.setCheckable(True)
            b.setEnabled(False)
        self._result_grp = QButtonGroup(self)
        self._result_grp.addButton(self.btn_ori, 0)
        self._result_grp.addButton(self.btn_deh, 1)
        self._result_grp.addButton(self.btn_aero, 2)
        top_bar.addWidget(self.btn_ori)
        top_bar.addWidget(self.btn_deh)
        top_bar.addWidget(self.btn_aero)
        self.btn_compare = QPushButton('전후 비교')
        self.btn_compare.setEnabled(False)
        top_bar.addWidget(self.btn_compare)
        top_bar.addStretch(1)
        self.btn_zoom_fit    = QPushButton('Fit')
        self.btn_zoom_actual = QPushButton('1:1')
        top_bar.addWidget(self.btn_zoom_fit)
        top_bar.addWidget(self.btn_zoom_actual)
        left_lay.addLayout(top_bar)

        self.viewer = ImageViewer()
        left_lay.addWidget(self.viewer, 1)

        splitter.addWidget(left)

        # 우측: 컨트롤 패널
        self.panel = ControlPanel()
        splitter.addWidget(self.panel)
        splitter.setStretchFactor(0, 7)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([1100, 480])

        self.setCentralWidget(splitter)

        # 상태바
        self.lbl_stage = QLabel('대기 중')
        self.progress = QProgressBar()
        self.progress.setMaximum(100)
        self.progress.setValue(0)
        self.progress.setFixedWidth(280)
        self.statusBar().addPermanentWidget(self.lbl_stage, 1)
        self.statusBar().addPermanentWidget(self.progress, 0)

    def _connect(self):
        self.panel.file_opened.connect(self._on_file_opened)
        self.panel.draw_mode_toggled.connect(self._on_draw_toggled)
        self.panel.polyline_clear_requested.connect(self._on_clear_polyline)
        self.panel.process_requested.connect(self._on_process_requested)
        self.panel.stop_requested.connect(self._on_stop_requested)
        self.panel.basis_save_requested.connect(self._on_basis_save_requested)

        self.viewer.polyline_changed.connect(self._on_polyline_changed)
        self.viewer.polyline_finished.connect(self._on_polyline_finished)

        self.btn_ori.clicked.connect(lambda: self.viewer.show_result(ImageViewer.RESULT_ORI))
        self.btn_deh.clicked.connect(lambda: self.viewer.show_result(ImageViewer.RESULT_DEH))
        self.btn_aero.clicked.connect(lambda: self.viewer.show_result(ImageViewer.RESULT_AERO))
        self.btn_zoom_fit.clicked.connect(self.viewer.zoom_fit)
        self.btn_zoom_actual.clicked.connect(self.viewer.zoom_actual)
        self.btn_compare.clicked.connect(self._on_compare_clicked)

    # ── slots ──────────────────────────────────────────────────
    def _on_file_opened(self, fin: str):
        # NOTE: import 자체가 PIL/_imaging DLL 로드 실패로 깨질 수 있으므로
        # try 블록 안으로 끌어들이고 ImportError 까지 잡는다. GUI 가 그냥
        # 종료되는 일이 없게 BaseException 까지 광역 처리, 사용자 가시
        # QMessageBox + exe 옆 runtime_error.log 영구 기록.
        try:
            from pipeline.loader import load_image
            self.panel.log(f'영상 로드 시작: {fin}')
            loaded = load_image(fin)
            self._loaded = loaded
            self._loaded_path = fin
            self.viewer.load_full_image(loaded['preview'])
            nb, h, w = loaded['shape']
            self.panel.update_metadata(fin, nb, h, w)
            self.panel.log(
                f'로드 완료: shape=({nb}, {h}, {w}), type={loaded["file_type"]}, rho={loaded["rho_type"]}'
            )
            # 결과 토글 비활성
            for b in (self.btn_ori, self.btn_deh, self.btn_aero):
                b.setEnabled(False)
                b.setChecked(False)
            self.btn_compare.setEnabled(False)
            self._last_result = None
        except BaseException as e:
            import traceback
            tb = traceback.format_exc()
            try:
                self.panel.log(f'로드 실패: {type(e).__name__}: {e}')
            except Exception:
                pass
            try:
                from pipeline.loader import _log_runtime_error
                _log_runtime_error(e, 'main_window._on_file_opened')
            except BaseException:
                # loader import 자체가 실패한 경우 — 헬퍼를 직접 구현해 기록
                try:
                    import os as _os, sys as _sys
                    log_dir = (_os.path.dirname(_sys.executable)
                               if getattr(_sys, 'frozen', False)
                               else _os.path.dirname(_os.path.abspath(__file__)))
                    with open(_os.path.join(log_dir, 'runtime_error.log'),
                              'a', encoding='utf-8') as f:
                        f.write('\n=== main_window._on_file_opened '
                                '(loader import failed) ===\n')
                        f.write(f'sys.executable: {_sys.executable}\n')
                        f.write(f'sys._MEIPASS: '
                                f'{getattr(_sys, "_MEIPASS", None)}\n')
                        f.write(tb)
                except Exception:
                    pass
            QMessageBox.critical(
                self, 'DehazingGUI 오류',
                f'{type(e).__name__}: {e}\n\n'
                f'자세한 내용은 exe 옆 runtime_error.log 참고.\n\n'
                f'{tb}'
            )

    def _on_draw_toggled(self, on: bool, name: str):
        if on:
            self.viewer.set_active_overlay(name or 'clear')
            self.viewer.set_mode(ImageViewer.MODE_DRAW)
            self.viewer.setFocus()
        else:
            self.viewer.set_mode(ImageViewer.MODE_VIEW)

    def _on_clear_polyline(self):
        self.viewer.clear_polyline('all')
        self.panel.update_polyline_stats('clear', 0, 0, vertices=None)
        self.panel.update_polyline_stats('hazy',  0, 0, vertices=None)

    def _on_polyline_changed(self, name: str, n_vertices: int):
        verts = self.viewer.get_vertices(name)
        if len(verts) >= 2:
            n_pix = sum(
                max(abs(b[0] - a[0]), abs(b[1] - a[1])) + 1
                for a, b in zip(verts[:-1], verts[1:])
            )
        else:
            n_pix = 0
        self.panel.update_polyline_stats(name, n_vertices, n_pix, vertices=verts)

    def _on_polyline_finished(self):
        # 그리기 종료 → active overlay 의 패널 토글 OFF
        active = self.viewer.active_overlay_name()
        btn = (self.panel.btn_draw_clear if active == 'clear'
               else self.panel.btn_draw_hazy)
        btn.setChecked(False)
        # 다른 overlay 토글이 켜져 있으면 그쪽으로 모드 유지됨 (control_panel 이 처리)
        verts = self.viewer.get_vertices(active)
        self.panel.log(f'{active} polyline 그리기 종료: 정점 {len(verts)}개')

    def _on_process_requested(self, fins: list, sensor: str, output_dir: str,
                              basis_id: str, basis_payload):
        # 첫 파일이 현재 preview 된 파일과 동일할 때만 cached_img 재활용
        cached = None
        if (self._loaded is not None and fins
                and self._loaded_path == fins[0]):
            cached = self._loaded.get('img')
        self.progress.setValue(0)
        self.lbl_stage.setText('초기화…')
        self._worker = DehazingWorker(
            fins, sensor, output_dir or None,
            basis_id, basis_payload,
            cached_img=cached, parent=self,
        )
        self._worker.log_signal.connect(self.panel.log)
        self._worker.progress_signal.connect(self._on_progress)
        self._worker.finished_signal.connect(self._on_finished)
        self._worker.error_signal.connect(self._on_error)
        self._worker.cancelled_signal.connect(self._on_cancelled)
        self._worker.file_started_signal.connect(self._on_file_started)
        self._worker.file_finished_signal.connect(self._on_file_finished)
        self._worker.file_failed_signal.connect(self._on_file_failed)
        self._worker.batch_finished_signal.connect(self._on_batch_finished)
        self._worker.start()

    def _on_file_started(self, idx: int, total: int, path: str):
        import os
        self.panel.log(f'\n▶ [{idx+1}/{total}] {os.path.basename(path)} 시작')

    def _on_file_finished(self, idx: int, total: int, path: str, result: dict):
        import os
        deh = result.get('deh_path') if isinstance(result, dict) else None
        self.panel.log(
            f'✔ [{idx+1}/{total}] {os.path.basename(path)} 완료'
            + (f' → {deh}' if deh else '')
        )

    def _on_file_failed(self, idx: int, total: int, path: str, err: str):
        import os
        self.panel.log(f'✘ [{idx+1}/{total}] {os.path.basename(path)} 실패: {err}')

    def _on_batch_finished(self, total: int, ok: int, failed: int):
        skipped = total - ok - failed  # 취소된 파일
        msg = f'배치 완료: 성공 {ok}/{total}'
        if failed:
            msg += f', 실패 {failed}'
        if skipped:
            msg += f', 미처리 {skipped}'
        self.panel.log(f'\n=== {msg} ===')
        self.lbl_stage.setText(msg)
        # 한 번도 성공 못해서 finished_signal 이 안 떴을 경우 대비 — 버튼 복원
        self.panel.processing_done()

    def _on_progress(self, pct: int, stage: str):
        self.progress.setValue(pct)
        self.lbl_stage.setText(stage)

    def _on_finished(self, result: dict):
        self._last_result = result
        self.viewer.load_result_images(
            result.get('preview_ori'),
            result.get('preview_deh'),
            result.get('preview_aero'),
        )
        for b in (self.btn_ori, self.btn_deh, self.btn_aero):
            b.setEnabled(True)
        self.btn_deh.setChecked(True)
        self.btn_compare.setEnabled(
            result.get('preview_ori') is not None
            and result.get('preview_deh') is not None
        )
        self.panel.processing_done()
        deh = result.get('deh_path')
        self.panel.log(f'완료: dehSpec → {deh}')
        self.lbl_stage.setText('완료')

    def _on_compare_clicked(self):
        if not self._last_result:
            return
        ori = self._last_result.get('preview_ori')
        deh = self._last_result.get('preview_deh')
        if ori is None or deh is None:
            return
        dlg = CompareDialog(ori, deh, parent=self)
        # 비모달 + GC 방지를 위해 참조 유지, 닫힐 때 정리
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.destroyed.connect(lambda _=None, d=dlg: self._compare_dialogs.remove(d)
                              if d in self._compare_dialogs else None)
        self._compare_dialogs.append(dlg)
        dlg.show()

    def _on_basis_save_requested(self, name: str):
        from pipeline.basis_extractor import extract_user_basis_payload
        from pipeline.basis_store import BasisStoreError
        if self._loaded is None:
            QMessageBox.warning(self, '저장 불가', '먼저 영상을 로드하세요')
            return
        clear_verts = self.panel.current_clear_vertices()
        if not clear_verts or len(clear_verts) < 2:
            QMessageBox.warning(self, '저장 불가', 'Clear polyline을 2점 이상 그리세요')
            return
        hazy_verts = self.panel.current_hazy_vertices()
        if not (hazy_verts and len(hazy_verts) >= 2):
            hazy_verts = None
        try:
            bp = extract_user_basis_payload(
                self._loaded['img'], clear_verts, hazy_verts, max_samples=500
            )
        except Exception as e:
            QMessageBox.critical(self, '추출 실패', f'basis 추출 실패: {e}')
            return
        sensor = self.panel.combo_sensor.currentData()
        try:
            bid = self.panel.store.add(
                name, sensor, bp['bases'],
                u_h=bp['u_h'], u_l=bp['u_l'], u_norm=bp['u_norm'],
            )
        except BasisStoreError as e:
            QMessageBox.critical(self, '저장 실패', str(e))
            return
        u_note = 'u 포함' if bp['u_norm'] is not None else 'u 없음 (센서 기본 사용)'
        self.panel.log(
            f'사용자 basis 저장: "{name}" (K={len(bp["bases"])}, '
            f'nb={bp["bases"].shape[1]}, sensor={sensor}, {u_note})'
        )
        self.panel.on_basis_saved(bid)

    def _on_error(self, msg: str):
        self.panel.log(f'[ERROR]\n{msg}')
        self.panel.processing_done()
        self.lbl_stage.setText('오류')
        QMessageBox.critical(self, '처리 실패', msg)

    def _on_stop_requested(self):
        if self._worker is not None and self._worker.isRunning():
            self.panel.log('[중지 요청] 현재 단계가 끝나는 즉시 멈춥니다')
            self._worker.requestInterruption()
            self.lbl_stage.setText('중지 중…')

    def _on_cancelled(self):
        self.panel.processing_done()
        self.lbl_stage.setText('중지됨')
