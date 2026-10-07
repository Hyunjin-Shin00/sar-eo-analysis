#!/usr/bin/env python3
"""TELEPIX Dehazing GUI — 진입점.

PyInstaller 번들 / 개발 모드 양쪽에서 동작하도록 vendor/ 경로를 sys.path에 추가.
"""
import os
import sys


def _setup_paths():
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS  # type: ignore[attr-defined]
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    vendor = os.path.join(base, 'vendor')
    if vendor not in sys.path:
        sys.path.insert(0, vendor)
    if base not in sys.path:
        sys.path.insert(0, base)


_setup_paths()


# PIL pyd 선점 로드 (PyInstaller runtime hook 이 안 도는 경우의 두번째 방어선).
# 번들 모드 + Windows 에서만 동작하고 그 외엔 noop. import 실패도 silent.
if getattr(sys, 'frozen', False) and sys.platform.startswith('win'):
    try:
        import _pil_bootstrap  # noqa: F401  # vendor/ 에 위치
    except Exception:
        pass


def _log_startup_error(exc: BaseException):
    """frozen 빌드에서 stderr가 없을 때 startup_error.log로 떨어뜨림."""
    import traceback
    try:
        if getattr(sys, 'frozen', False):
            log_dir = os.path.dirname(sys.executable)
        else:
            log_dir = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(log_dir, 'startup_error.log'), 'w', encoding='utf-8') as f:
            f.write(f'sys.executable: {sys.executable}\n')
            f.write(f'sys._MEIPASS: {getattr(sys, "_MEIPASS", None)}\n')
            f.write(f'GDAL_DATA: {os.environ.get("GDAL_DATA")}\n')
            f.write(f'PROJ_LIB:  {os.environ.get("PROJ_LIB")}\n')
            f.write('-' * 60 + '\n')
            traceback.print_exc(file=f)
    except Exception:
        pass


def main():
    try:
        from PyQt5.QtWidgets import QApplication
        from ui.main_window import MainWindow
    except BaseException as e:
        _log_startup_error(e)
        raise

    app = QApplication(sys.argv)
    app.setApplicationName('TELEPIX Dehazing')
    app.setOrganizationName('TELEPIX')

    try:
        win = MainWindow()
        win.show()
    except BaseException as e:
        _log_startup_error(e)
        raise

    sys.exit(app.exec_())


if __name__ == '__main__':
    try:
        main()
    except BaseException as e:
        _log_startup_error(e)
        raise
