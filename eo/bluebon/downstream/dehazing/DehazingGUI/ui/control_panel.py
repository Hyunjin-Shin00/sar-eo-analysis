"""우측 컨트롤 패널: 메타데이터 + 입출력 + Basis 그리기 + 로그."""
import os
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QComboBox,
    QTextEdit, QFileDialog, QMessageBox, QInputDialog,
)

from pipeline.sensor_config import SENSOR_OPTIONS, auto_detect_sensor
from pipeline.io_helpers import detect_rho_type
from pipeline.basis_catalog import list_builtin, default_basis_id
from pipeline.basis_store import BasisStore, BasisStoreError


POLYLINE_ID = 'polyline'


class ControlPanel(QWidget):
    file_opened              = pyqtSignal(str)             # 첫 파일만 emit (preview용)
    draw_mode_toggled        = pyqtSignal(bool, str)       # (on, overlay_name) — name='' if off
    polyline_clear_requested = pyqtSignal()                # 둘 다 지움
    process_requested        = pyqtSignal(list, str, str, str, object)
    # fins: list[str], sensor, output_dir, basis_id, basis_payload
    stop_requested           = pyqtSignal()
    basis_save_requested     = pyqtSignal(str)             # 사용자가 입력한 이름

    def __init__(self, parent=None):
        super().__init__(parent)
        self.store = BasisStore()
        self._cached_clear_verts = None
        self._cached_hazy_verts = None
        self._is_running = False
        self._selected_files: list[str] = []  # 배치 큐 (단일 선택도 1원소 리스트)
        self._build_ui()
        self._connect()
        self._refresh_basis_combo()

    # ── UI ─────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # 구분 (메타데이터)
        meta_box = QGroupBox('구분')
        meta_form = QFormLayout(meta_box)
        self.lbl_scene   = QLabel('-')
        self.lbl_product = QLabel('-')
        self.lbl_size    = QLabel('-')
        self.lbl_method  = QLabel('Spectral basis - top-3')
        self.lbl_pattern = QLabel('dehSpec')
        for lab in (self.lbl_scene, self.lbl_product, self.lbl_size,
                    self.lbl_method, self.lbl_pattern):
            lab.setStyleSheet('color:#222;')
        meta_form.addRow('SCENE:',    self.lbl_scene)
        meta_form.addRow('PRODUCT:',  self.lbl_product)
        meta_form.addRow('SIZE:',     self.lbl_size)
        meta_form.addRow('METHOD:',   self.lbl_method)
        meta_form.addRow('PATTERN:',  self.lbl_pattern)
        root.addWidget(meta_box)

        # 입출력
        io_box = QGroupBox('입출력')
        io_form = QFormLayout(io_box)
        self.edit_input = QLineEdit()
        self.edit_input.setReadOnly(True)
        self.btn_browse_in = QPushButton('찾아보기')
        in_row = QHBoxLayout()
        in_row.addWidget(self.edit_input, 1)
        in_row.addWidget(self.btn_browse_in)
        in_w = QWidget(); in_w.setLayout(in_row)
        io_form.addRow('입력:', in_w)

        self.combo_sensor = QComboBox()
        for label, key in SENSOR_OPTIONS:
            self.combo_sensor.addItem(label, key)
        io_form.addRow('센서:', self.combo_sensor)

        self.edit_output = QLineEdit()
        self.btn_browse_out = QPushButton('찾아보기')
        out_row = QHBoxLayout()
        out_row.addWidget(self.edit_output, 1)
        out_row.addWidget(self.btn_browse_out)
        out_w = QWidget(); out_w.setLayout(out_row)
        io_form.addRow('출력:', out_w)
        root.addWidget(io_box)

        # Basis 선택
        basis_box = QGroupBox('Clear 영역 Basis')
        basis_lay = QVBoxLayout(basis_box)

        self.combo_basis = QComboBox()
        basis_lay.addWidget(self.combo_basis)

        # 두 polyline 그리기 토글 (Clear=녹, Hazy=빨강)
        draw_row = QHBoxLayout()
        self.btn_draw_clear = QPushButton('Clear 그리기')
        self.btn_draw_clear.setCheckable(True)
        self.btn_draw_clear.setEnabled(False)
        self.btn_draw_clear.setStyleSheet(
            'QPushButton:checked { background-color:#1a8a2a; color:white; }'
        )
        self.btn_draw_hazy = QPushButton('Hazy 그리기')
        self.btn_draw_hazy.setCheckable(True)
        self.btn_draw_hazy.setEnabled(False)
        self.btn_draw_hazy.setStyleSheet(
            'QPushButton:checked { background-color:#b03030; color:white; }'
        )
        draw_row.addWidget(self.btn_draw_clear)
        draw_row.addWidget(self.btn_draw_hazy)
        basis_lay.addLayout(draw_row)

        btn_row = QHBoxLayout()
        self.btn_save_basis = QPushButton('저장…')
        self.btn_save_basis.setEnabled(False)
        self.btn_rename_basis = QPushButton('이름변경…')
        self.btn_rename_basis.setEnabled(False)
        self.btn_delete_basis = QPushButton('삭제')
        self.btn_delete_basis.setEnabled(False)
        btn_row.addWidget(self.btn_save_basis)
        btn_row.addWidget(self.btn_rename_basis)
        btn_row.addWidget(self.btn_delete_basis)
        basis_lay.addLayout(btn_row)

        self.lbl_polyline = QLabel('Clear: 정점 0 (~0 px)  |  Hazy: 정점 0 (~0 px)')
        self.lbl_polyline.setStyleSheet('color:#555;')
        basis_lay.addWidget(self.lbl_polyline)

        clear_row = QHBoxLayout()
        self.btn_clear = QPushButton('폴리라인 지우기')
        self.btn_clear.setEnabled(False)
        clear_row.addWidget(self.btn_clear)
        clear_row.addStretch(1)
        basis_lay.addLayout(clear_row)
        root.addWidget(basis_box)

        # 실행 버튼
        self.btn_run = QPushButton('처리 시작')
        self.btn_run.setEnabled(False)
        self.btn_run.setStyleSheet(
            'QPushButton { background-color:#E64A6F; color:white; '
            'font-weight:bold; padding:10px; border-radius:4px; }'
            'QPushButton:disabled { background-color:#aaa; }'
        )
        root.addWidget(self.btn_run)

        # 로그
        log_box = QGroupBox('로그')
        log_lay = QVBoxLayout(log_box)
        self.log_widget = QTextEdit()
        self.log_widget.setReadOnly(True)
        self.log_widget.setStyleSheet(
            'QTextEdit { background:#0d0d0d; color:#dcdcdc; }'
        )
        font = QFont('Consolas')
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(9)
        self.log_widget.setFont(font)
        log_lay.addWidget(self.log_widget)
        root.addWidget(log_box, 1)

    def _connect(self):
        self.btn_browse_in.clicked.connect(self._on_browse_in)
        self.btn_browse_out.clicked.connect(self._on_browse_out)
        self.btn_draw_clear.toggled.connect(lambda on: self._on_draw_toggled('clear', on))
        self.btn_draw_hazy.toggled.connect(lambda on: self._on_draw_toggled('hazy', on))
        self.btn_clear.clicked.connect(self.polyline_clear_requested.emit)
        self.btn_run.clicked.connect(self._on_run)

        self.combo_sensor.currentIndexChanged.connect(self._on_sensor_changed)
        self.combo_basis.currentIndexChanged.connect(self._on_basis_combo_changed)

        self.btn_save_basis.clicked.connect(self._on_save_basis_clicked)
        self.btn_rename_basis.clicked.connect(self._on_rename_basis_clicked)
        self.btn_delete_basis.clicked.connect(self._on_delete_basis_clicked)

    # ── basis combo 관리 ───────────────────────────────────────
    def _current_sensor(self) -> str:
        return self.combo_sensor.currentData()

    def _refresh_basis_combo(self, select_id: str | None = None):
        """현재 센서에 맞춰 basis 콤보 재구성."""
        prev_id = select_id or self.combo_basis.currentData()
        sensor = self._current_sensor()

        self.combo_basis.blockSignals(True)
        self.combo_basis.clear()

        for bid, label, _is_default in list_builtin(sensor):
            self.combo_basis.addItem(f'[기본] {label}', bid)

        for b in self.store.list(sensor=sensor):
            self.combo_basis.addItem(f'[저장] {b["name"]}', b['id'])

        self.combo_basis.addItem('▷ 새 폴리라인 그리기', POLYLINE_ID)

        # 이전 선택 복원
        idx = self.combo_basis.findData(prev_id) if prev_id else -1
        if idx < 0:
            # 센서 기본 항목으로
            did = default_basis_id(sensor)
            idx = self.combo_basis.findData(did)
        if idx < 0:
            idx = 0
        self.combo_basis.setCurrentIndex(idx)
        self.combo_basis.blockSignals(False)
        self._on_basis_combo_changed()

    def _on_basis_combo_changed(self, *_):
        bid = self.combo_basis.currentData()
        is_polyline = (bid == POLYLINE_ID)
        is_user = isinstance(bid, str) and bid.startswith('user:')

        has_input = bool(self.edit_input.text())
        # 폴리라인 그리기는 단일 파일 전용 (preview 한 장 기준)
        is_single = len(self._selected_files) <= 1
        self.btn_draw_clear.setEnabled(is_polyline and has_input and is_single)
        self.btn_draw_hazy.setEnabled(is_polyline and has_input and is_single)
        self.btn_rename_basis.setEnabled(is_user)
        self.btn_delete_basis.setEnabled(is_user)

        clear_ok = (self._cached_clear_verts is not None
                    and len(self._cached_clear_verts) >= 2)
        self.btn_save_basis.setEnabled(is_polyline and clear_ok)

        # 폴리라인 모드가 아니면 그리기 종료 + 오버레이 둘 다 지우기
        if not is_polyline:
            if self.btn_draw_clear.isChecked():
                self.btn_draw_clear.setChecked(False)
            if self.btn_draw_hazy.isChecked():
                self.btn_draw_hazy.setChecked(False)
            self.polyline_clear_requested.emit()
            self.lbl_polyline.setText('Clear: 정점 0 (~0 px)  |  Hazy: 정점 0 (~0 px)')

    def _on_sensor_changed(self, *_):
        self._refresh_basis_combo()

    def _on_save_basis_clicked(self):
        clear = self._cached_clear_verts
        hazy = self._cached_hazy_verts
        if not clear or len(clear) < 2:
            QMessageBox.warning(self, '저장 불가', 'Clear polyline을 2점 이상 그리세요')
            return
        # Hazy 없으면 u 없이 저장 — 확인
        if not hazy or len(hazy) < 2:
            r = QMessageBox.question(
                self, 'u 없이 저장',
                'Hazy polyline이 없습니다.\n'
                'u (aerosol spectrum) 없이 bases만 저장하시겠습니까?\n'
                '(처리 시 센서 기본 u를 사용합니다)',
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if r != QMessageBox.Yes:
                return
        name, ok = QInputDialog.getText(self, 'Basis 저장', '저장할 이름:')
        if not ok:
            return
        name = name.strip()
        if not name:
            QMessageBox.warning(self, '저장 불가', '이름을 입력하세요')
            return
        self.basis_save_requested.emit(name)

    def _on_rename_basis_clicked(self):
        bid = self.combo_basis.currentData()
        if not (isinstance(bid, str) and bid.startswith('user:')):
            return
        entry = self.store.get(bid)
        cur = entry.get('name', '') if entry else ''
        name, ok = QInputDialog.getText(
            self, '이름 변경', '새 이름:', text=cur
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            QMessageBox.warning(self, '오류', '이름을 입력하세요')
            return
        try:
            self.store.rename(bid, name)
        except BasisStoreError as e:
            QMessageBox.critical(self, '저장 실패', str(e))
            return
        self._refresh_basis_combo(select_id=bid)

    def _on_delete_basis_clicked(self):
        bid = self.combo_basis.currentData()
        if not (isinstance(bid, str) and bid.startswith('user:')):
            return
        entry = self.store.get(bid)
        nm = entry.get('name', bid) if entry else bid
        r = QMessageBox.question(
            self, '삭제 확인', f'"{nm}" 을(를) 삭제할까요?',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if r != QMessageBox.Yes:
            return
        try:
            self.store.delete(bid)
        except BasisStoreError as e:
            QMessageBox.critical(self, '저장 실패', str(e))
            return
        self._refresh_basis_combo()

    def on_basis_saved(self, bid: str):
        """MainWindow 가 store 에 추가한 뒤 호출."""
        self._refresh_basis_combo(select_id=bid)

    # ── slot ───────────────────────────────────────────────────
    def _on_browse_in(self):
        # 다중 선택 지원. 단일 선택도 1원소 리스트로 통일 처리.
        fns, _ = QFileDialog.getOpenFileNames(
            self, '입력 영상 선택 (다중 선택 가능)', '',
            '위성 영상 (*.nc *.tif *.tiff *.png *.jpg *.jpeg);;모든 파일 (*.*)',
        )
        if not fns:
            return
        self._selected_files = list(fns)
        n = len(fns)
        first = fns[0]
        if n == 1:
            self.edit_input.setText(first)
        else:
            base_first = os.path.basename(first)
            self.edit_input.setText(f'[{n}개 파일] {base_first} 외 {n-1}개')
            self.log(f'배치 처리 대상 {n}개 파일 선택:')
            for p in fns:
                self.log(f'  - {p}')
        if not self.edit_output.text():
            self.edit_output.setText(os.path.dirname(first))
        # 자동 센서 감지 — 첫 파일 기준
        guessed = auto_detect_sensor(first)
        if guessed:
            idx = self.combo_sensor.findData(guessed)
            if idx >= 0:
                self.combo_sensor.setCurrentIndex(idx)
        # rhorc 여부 체크 (모든 파일)
        for p in fns:
            rho = detect_rho_type(p)
            if rho == 'rhot':
                self.log(f'경고: {os.path.basename(p)} 는 rhot — '
                         '이 빌드에서 미지원 (rhorc만 지원)')

        # 다중 선택이면 폴리라인 콤보가 선택된 상태일 때 센서 기본으로 자동 전환
        if n > 1 and self.combo_basis.currentData() == POLYLINE_ID:
            sensor = self._current_sensor()
            did = default_basis_id(sensor)
            idx = self.combo_basis.findData(did)
            if idx >= 0:
                self.combo_basis.setCurrentIndex(idx)
                self.log(
                    '[안내] 다중 파일 선택이므로 폴리라인 모드를 해제하고 '
                    '센서 기본 basis 로 전환했습니다. 폴리라인 사용은 '
                    '단일 파일에서만 가능합니다.'
                )

        self.btn_run.setEnabled(True)
        self._on_basis_combo_changed()  # 그리기 토글 활성/비활성 갱신
        # 첫 파일만 preview 로 로드 (기존 동작 유지)
        self.file_opened.emit(first)

    def _on_browse_out(self):
        d = QFileDialog.getExistingDirectory(self, '출력 디렉토리 선택')
        if d:
            self.edit_output.setText(d)

    def _on_draw_toggled(self, name: str, on: bool):
        if on:
            # 상호 배타: 다른 토글 OFF
            other_btn = self.btn_draw_hazy if name == 'clear' else self.btn_draw_clear
            if other_btn.isChecked():
                other_btn.blockSignals(True)
                other_btn.setChecked(False)
                other_btn.blockSignals(False)
            label_base = {'clear': 'Clear', 'hazy': 'Hazy'}[name]
            btn = self.btn_draw_clear if name == 'clear' else self.btn_draw_hazy
            btn.setText(f'{label_base} 그리기 종료 (우클릭/Enter)')
            self.btn_clear.setEnabled(True)
            self.draw_mode_toggled.emit(True, name)
        else:
            label_base = {'clear': 'Clear', 'hazy': 'Hazy'}[name]
            btn = self.btn_draw_clear if name == 'clear' else self.btn_draw_hazy
            btn.setText(f'{label_base} 그리기')
            # 다른 토글이 ON 상태라면 그쪽으로 모드 유지, 아니면 OFF
            other_btn = self.btn_draw_hazy if name == 'clear' else self.btn_draw_clear
            other_name = 'hazy' if name == 'clear' else 'clear'
            if other_btn.isChecked():
                self.draw_mode_toggled.emit(True, other_name)
            else:
                self.draw_mode_toggled.emit(False, '')

    def _on_run(self):
        # 처리 중이면 중지 요청
        if self._is_running:
            self.btn_run.setEnabled(False)
            self.btn_run.setText('중지 중…')
            self.stop_requested.emit()
            return

        fins = [p for p in self._selected_files if os.path.isfile(p)]
        if not fins:
            QMessageBox.warning(self, '오류', '유효한 입력 파일을 선택하세요')
            return
        sensor = self.combo_sensor.currentData()
        output_dir = self.edit_output.text().strip() or None

        bid = self.combo_basis.currentData()
        payload = None
        if bid == POLYLINE_ID:
            if len(fins) > 1:
                QMessageBox.warning(
                    self, '폴리라인은 단일 파일 전용',
                    '폴리라인 basis 는 미리 보기 한 장 기준이라 다중 파일에 '
                    '적용할 수 없습니다. 저장된 user basis 또는 builtin basis 를 '
                    '선택하세요. (폴리라인을 저장하면 다중 처리에 재사용 가능)'
                )
                return
            clear = self._cached_clear_verts
            if not clear or len(clear) < 2:
                QMessageBox.warning(
                    self, '폴리라인 부족',
                    '"새 사용자 basis" 모드입니다. Clear polyline 정점을 2개 이상 찍으세요.'
                )
                return
            hazy = self._cached_hazy_verts
            payload = {
                'clear_verts': clear,
                'hazy_verts': hazy if (hazy and len(hazy) >= 2) else None,
            }
        elif isinstance(bid, str) and bid.startswith('user:'):
            arr = self.store.get_array(bid)
            if arr is None:
                QMessageBox.warning(self, '오류', '저장된 basis 를 찾을 수 없습니다')
                return
            u = self.store.get_u(bid)
            payload = {'bases': arr, 'u': u}

        self._is_running = True
        self.btn_run.setText('중지')
        self.btn_run.setStyleSheet(
            'QPushButton { background-color:#888; color:white; '
            'font-weight:bold; padding:10px; border-radius:4px; }'
            'QPushButton:disabled { background-color:#bbb; }'
        )
        self.process_requested.emit(fins, sensor, output_dir or '', bid, payload)

    # ── public API ─────────────────────────────────────────────
    def update_metadata(self, fin: str, nb: int, h: int, w: int):
        self.lbl_scene.setText(os.path.basename(fin))
        self.lbl_product.setText(detect_rho_type(fin))
        mp = (h * w) / 1_000_000.0
        self.lbl_size.setText(f'{w} × {h}  ({mp:.1f} Mpx, {nb} bands)')

    def update_polyline_stats(self, name: str, n_vertices: int,
                              n_pixels_est: int, vertices=None):
        """name: 'clear' or 'hazy'."""
        if name == 'clear':
            self._cached_clear_verts = vertices
        elif name == 'hazy':
            self._cached_hazy_verts = vertices
        # 라벨 갱신 (두 polyline 모두 표시)
        c_n = len(self._cached_clear_verts) if self._cached_clear_verts else 0
        h_n = len(self._cached_hazy_verts)  if self._cached_hazy_verts  else 0
        c_px = self._estimate_pixels(self._cached_clear_verts)
        h_px = self._estimate_pixels(self._cached_hazy_verts)
        self.lbl_polyline.setText(
            f'Clear: 정점 {c_n} (~{c_px} px)  |  Hazy: 정점 {h_n} (~{h_px} px)'
        )
        if c_n > 0 or h_n > 0:
            self.btn_clear.setEnabled(True)
        # 저장 버튼: Clear ≥ 2 필요 (Hazy 는 옵션)
        is_polyline = (self.combo_basis.currentData() == POLYLINE_ID)
        self.btn_save_basis.setEnabled(is_polyline and c_n >= 2)

    @staticmethod
    def _estimate_pixels(verts) -> int:
        if not verts or len(verts) < 2:
            return 0
        return sum(
            max(abs(b[0] - a[0]), abs(b[1] - a[1])) + 1
            for a, b in zip(verts[:-1], verts[1:])
        )

    def current_clear_vertices(self):
        return self._cached_clear_verts

    def current_hazy_vertices(self):
        return self._cached_hazy_verts

    def log(self, msg: str):
        self.log_widget.append(msg)

    def processing_done(self):
        self._is_running = False
        self.btn_run.setEnabled(True)
        self.btn_run.setText('처리 시작')
        self.btn_run.setStyleSheet(
            'QPushButton { background-color:#E64A6F; color:white; '
            'font-weight:bold; padding:10px; border-radius:4px; }'
            'QPushButton:disabled { background-color:#aaa; }'
        )
