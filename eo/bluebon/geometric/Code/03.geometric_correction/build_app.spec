# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 설정 파일
독립 실행 파일 빌드용

사용 방법:
1. pip install pyinstaller
2. pyinstaller build_app.spec
"""

block_cipher = None

a = Analysis(
    ['gui_app.py'],
    pathex=[],
    binaries=[],
    datas=[
        # 모델 가중치 파일 등이 있다면 여기에 추가
        # ('path/to/models', 'models'),
        # 한글 폰트 파일 포함 (Windows용)
        # 사용 전에 fonts/ 폴더에 폰트 파일을 복사해야 함
        # ('fonts/malgun.ttf', 'fonts'),  # Windows: 맑은 고딕 (라이선스 확인 필요)
        # ('fonts/nanumgothic.ttf', 'fonts'),  # Linux: 나눔고딕 (무료)
        # 참고: 폰트 파일은 직접 다운로드하여 fonts/ 폴더에 배치 필요
    ],
    hiddenimports=[
        'geometric_correction',
        'rasterio',
        'rasterio.warp',
        'rasterio.control',
        'rasterio.enums',
        'rasterio.transform',
        'osgeo',
        'osgeo.gdal',
        'osgeo.osr',
        'pyproj',
        'pyproj.crs',
        'pyproj.transformer',
        'torch',
        'torchvision',
        'lightglue',
        'kornia',
        'kornia.feature',
        'transformers',
        'cv2',
        'numpy',
        'pandas',
        'PIL',
        'skimage',
        'sklearn',
        'openpyxl',
        'matplotlib',
        'matplotlib.font_manager',
        'tqdm',
        'rpcm',
        'rpcfit',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 불필요한 패키지 제외 (선택사항)
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='GeometricCorrectionGUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # GUI 앱이므로 콘솔 창 숨김
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 아이콘 파일이 있다면 여기에 경로 지정
)

