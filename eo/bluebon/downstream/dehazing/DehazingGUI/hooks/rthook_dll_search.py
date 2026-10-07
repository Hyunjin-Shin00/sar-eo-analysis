"""PyInstaller 런타임 hook: standalone dist 보증.

목적:
  타깃 PC 의 사전 설치/PATH/SYSTEM32 상태에 관계 없이, `dist/DehazingGUI/`
  를 복사만 하면 동작하도록 프로세스 DLL 환경을 잠근다.

방어:
  1. `SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_DEFAULT_DIRS)` 로
     PATH/cwd 검색을 끄고 APPLICATION_DIR | USER_DIRS | SYSTEM32 만 허용.
  2. `add_dll_directory` 로 `_MEIPASS` / `_MEIPASS/bin` / `_MEIPASS/Library/bin`
     을 USER_DIRS 에 등록.
  3. `_MEIPASS` 직속의 모든 `*.dll` 을 절대경로 `ctypes.WinDLL` 로
     **2 패스** 일괄 preload. 첫 패스에서 dep 부재로 실패한 것이 둘째
     패스에서 다른 DLL 메모리 적재 뒤 성공할 수 있다.
  4. `_MEIPASS/PIL/*.pyd` 도 절대경로 로드해 PIL C extension 핸들을 미리
     프로세스에 박는다. 성공 시 후속 Python `from PIL import _imaging` 이
     우리 핸들을 재사용 → DLL 충돌 자체가 무력화.

진단:
  hook 진입 시점에 `sys.executable`, OS 버전, PATH, hook 도착 전에 이미
  로드돼 있는 핵심 DLL 의 실제 경로를 stdout 으로 덤프. `[dllhook]` 접두어.

요구사항:
  Windows 8 이상 기본 지원. Windows 7 은 KB2533623 필요. 그 외엔 silent
  fallback (PATH 기반 검색 살림) 으로 깨지지 않는다.

이 hook 은 반드시 다른 rthook 보다 먼저 실행되어야 한다
(`spec` 의 `runtime_hooks` 맨 앞).
"""
import os
import sys


def _log(msg):
    try:
        print(f'[dllhook] {msg}', flush=True)
    except Exception:
        pass


if getattr(sys, 'frozen', False) and sys.platform.startswith('win'):
    import ctypes

    base = sys._MEIPASS  # type: ignore[attr-defined]
    _log(f'enter, base={base}')
    _log(f'sys.executable={sys.executable}')
    try:
        wv = sys.getwindowsversion()
        _log(f'OS: major={wv.major} minor={wv.minor} build={wv.build} '
             f'platform={wv.platform} product_type={wv.product_type}')
    except Exception as e:
        _log(f'OS info unavailable: {e}')
    _path = os.environ.get('PATH', '')
    _log(f'PATH (first 1500 chars): {_path[:1500]}')

    # 1. SetDefaultDllDirectories
    LOAD_LIBRARY_SEARCH_DEFAULT_DIRS = 0x00001000
    try:
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        if hasattr(k32, 'SetDefaultDllDirectories'):
            rc = k32.SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_DEFAULT_DIRS)
            _log(f'SetDefaultDllDirectories rc={rc}')
        else:
            _log('SetDefaultDllDirectories not available (legacy Windows)')
    except (OSError, AttributeError) as e:
        _log(f'SetDefaultDllDirectories raised: {type(e).__name__}: {e}')

    # 2. add_dll_directory
    candidate_dirs = [
        base,
        os.path.join(base, 'bin'),
        os.path.join(base, 'Library', 'bin'),
        os.path.join(base, 'PIL'),
    ]
    if hasattr(os, 'add_dll_directory'):
        for d in candidate_dirs:
            if os.path.isdir(d):
                try:
                    os.add_dll_directory(d)
                    _log(f'add_dll_directory: {d}')
                except (FileNotFoundError, OSError) as e:
                    _log(f'add_dll_directory FAILED: {d} ({e})')

    # 3. hook 도착 전에 이미 로드된 핵심 DLL 의 실제 경로 (시스템 충돌 진단)
    try:
        GMH = ctypes.windll.kernel32.GetModuleHandleW
        GMFN = ctypes.windll.kernel32.GetModuleFileNameW
        _buf = ctypes.create_unicode_buffer(1024)
        for _probe in ('tiff.dll', 'zlib.dll', 'jpeg8.dll', 'libpng16.dll',
                       'openjp2.dll', 'libxml2.dll', 'msvcp140.dll',
                       'vcruntime140.dll', 'python311.dll'):
            _h = GMH(_probe)
            if _h:
                GMFN(_h, _buf, 1024)
                _log(f'pre-existing {_probe}: {_buf.value}')
    except Exception as e:
        _log(f'GetModuleHandle probe failed: {e}')

    # 4. _internal/*.dll 일괄 preload (2 패스)
    try:
        all_dlls = sorted(
            f for f in os.listdir(base) if f.lower().endswith('.dll')
        )
    except OSError as e:
        all_dlls = []
        _log(f'listdir({base}) failed: {e}')
    _log(f'preload candidates: {len(all_dlls)}')

    for _pass in (1, 2):
        _fails = []
        for _name in all_dlls:
            try:
                ctypes.WinDLL(os.path.join(base, _name))
            except OSError as e:
                _fails.append((_name, e))
        if _pass == 2 and _fails:
            for _n, _e in _fails:
                _log(
                    f'preload FAIL pass2: {_n} '
                    f'(winerror={getattr(_e, "winerror", "?")}: {_e})'
                )
        _log(
            f'preload pass{_pass}: ok={len(all_dlls)-len(_fails)}, '
            f'fail={len(_fails)}'
        )

    # 5. _internal/PIL/*.pyd 직접 로드 (Python import 보다 먼저 핸들 선점)
    pil_dir = os.path.join(base, 'PIL')
    if os.path.isdir(pil_dir):
        try:
            pyd_files = sorted(
                f for f in os.listdir(pil_dir) if f.lower().endswith('.pyd')
            )
        except OSError as e:
            pyd_files = []
            _log(f'listdir({pil_dir}) failed: {e}')
        for _fname in pyd_files:
            _full = os.path.join(pil_dir, _fname)
            try:
                ctypes.WinDLL(_full)
                _log(f'preloaded pyd: {_fname}')
            except OSError as e:
                _log(
                    f'preload pyd FAIL: {_fname} '
                    f'(winerror={getattr(e, "winerror", "?")}: {e})'
                )

    _log('done')
