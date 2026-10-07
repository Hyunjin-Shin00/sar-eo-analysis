"""ASF 버스트(.tiff) -> ESA SAFE 변환. 궤도별/날짜별로 SAFE 1개 생성."""
import os, sys, json, glob, shutil, pathlib, netrc
os.environ.pop('PYTHONPATH', None)
os.environ['PROJ_DATA'] = os.path.join(os.environ.get('CONDA_PREFIX', ''), 'share/proj')
os.environ['PROJ_LIB'] = os.environ['PROJ_DATA']
n = netrc.netrc(os.path.expanduser('~/.netrc'))
login, _, pw = n.authenticators('urs.earthdata.nasa.gov')
os.environ['EARTHDATA_USERNAME'] = login
os.environ['EARTHDATA_PASSWORD'] = pw
from burst2safe.burst2safe import burst2safe

SLC_ROOT = os.path.join(os.environ.get('DATA_ROOT', '<DATA_ROOT>'), 'SLC')
TRACKS = {'ASC_085': 'IW2', 'DSC_019': 'IW1', 'DSC_121': 'IW3'}
only = sys.argv[1:] or list(TRACKS)

for trk in only:
    swath = TRACKS[trk]
    src = os.path.join(SLC_ROOT, trk)
    wd = pathlib.Path(os.environ.get('DATA_ROOT', '<DATA_ROOT>')) / 'work' / f'safe_{trk}'
    wd.mkdir(parents=True, exist_ok=True)
    # .zip(실제는 tiff) -> work_dir/<granule>.tiff 로 하드링크
    grans = []
    for f in sorted(glob.glob(os.path.join(src, '*-BURST.zip'))):
        g = os.path.basename(f)[:-4]
        dst = wd / f'{g}.tiff'
        if not dst.exists():
            try: os.link(f, dst)
            except OSError: shutil.copy2(f, dst)
        grans.append(g)
    by_date = {}
    for g in grans:
        by_date.setdefault(g.split('_')[3][:8], []).append(g)
    print(f'\n===== {trk} ({swath}) : {len(grans)} bursts / {len(by_date)} dates =====', flush=True)
    for d in sorted(by_date):
        gl = sorted(by_date[d])
        print(f'  [{d}] {len(gl)} bursts -> SAFE 생성 중...', flush=True)
        try:
            out = burst2safe(granules=gl, polarizations=['VV', 'VH'], swaths=[swath], work_dir=wd)
            print(f'    OK: {out.name}', flush=True)
        except Exception as e:
            print(f'    FAIL: {type(e).__name__}: {e}', flush=True)
