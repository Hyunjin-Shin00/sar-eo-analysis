"""Generate bundle figures (PNG in tmp; converted to webp afterwards). Read-only on sources."""
import os, sys, glob, math, csv, datetime as dt
import numpy as np, h5py, rasterio
import xml.etree.ElementTree as ET
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import recompute_geometry as G

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'png')
os.makedirs(OUT, exist_ok=True)
CSK = os.environ.get('CSK_RUN', '<DATA_ROOT>/CSK/20200712_20200713_interferogram_isce2_snaphu')
N2H5 = os.environ.get('N2_H5', '<DATA_ROOT>/SLC/structure_with_tiny_data_n2.h5')
NDVI = os.environ.get('NDVI_ROOT', '<DATA_ROOT>/ndvi_parks')  # <park> 국립공원/change_monitoring_ndvi_*.csv
DEMP = os.environ.get('CSK_EXT_DEM', '<DATA_ROOT>/CSK/DEM/output_hh.tif')
LAM = 0.031228381041666666
INK, INK2, MUTED, SURF = '#0b0b0b', '#52514e', '#898781', '#fcfcfb'
SER = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948']
plt.rcParams.update({'font.size': 10, 'axes.edgecolor': MUTED, 'axes.labelcolor': INK2, 'xtick.color': INK2, 'ytick.color': INK2,
                     'axes.titlecolor': INK, 'figure.facecolor': 'white', 'axes.spines.top': False, 'axes.spines.right': False})


def dims(xml):
    r = ET.parse(xml).getroot()
    g = lambda n: r.find(f".//property[@name='{n}']/value")
    out = [int(g('width').text), int(g('length').text)]
    for n in ('first_latitude', 'first_longitude', 'delta_latitude', 'delta_longitude'):
        e = g(n)
        out.append(float(e.text) if e is not None else None)
    return out


def geo_extent(xml):
    import re
    v = open(xml[:-4] + '.vrt').read()
    W = int(re.search(r'rasterXSize="(\d+)"', v).group(1)); L = int(re.search(r'rasterYSize="(\d+)"', v).group(1))
    gt = [float(x) for x in re.search(r'<GeoTransform>(.*?)</GeoTransform>', v).group(1).split(',')]
    return W, L, [gt[0], gt[0] + W * gt[1], gt[3] + L * gt[5], gt[3]]


# ---------- 00 key: CSK geo amplitude / wrapped phase / coherence ----------
def fig_key():
    ifg = CSK + '/interferogram'
    W, L, ext = geo_extent(ifg + '/filt_topophase.flat.geo.xml')
    z = np.fromfile(ifg + '/filt_topophase.flat.geo', np.complex64).reshape(L, W)[::3, ::3]
    Wc, Lc, _ = geo_extent(ifg + '/topophase.cor.geo.xml')
    cor = np.fromfile(ifg + '/topophase.cor.geo', np.float32).reshape(Lc, 2, Wc)
    amp = cor[::3, 0, ::3]; coh = cor[::3, 1, ::3]
    valid = np.abs(z) > 0
    amp = np.where(amp > 0, amp, np.nan); ph = np.where(valid, np.angle(z), np.nan); coh = np.where(coh > 0, coh, np.nan)
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.6))
    lo, hi = np.nanpercentile(amp, [2, 98])
    ims = [ax[0].imshow(amp, cmap='gray', vmin=lo, vmax=hi, extent=ext, aspect='auto'),
           ax[1].imshow(ph, cmap='twilight', vmin=-np.pi, vmax=np.pi, extent=ext, aspect='auto', interpolation='nearest'),
           ax[2].imshow(coh, cmap='magma', vmin=0, vmax=1, extent=ext, aspect='auto')]
    titles = ['Amplitude (12x12 looks)', 'Filtered wrapped phase (rad)', 'Coherence']
    for a, im, t in zip(ax, ims, titles):
        a.set_title(t, fontsize=11); a.set_xlabel('Longitude (°E)')
        if t != titles[0]:
            fig.colorbar(im, ax=a, fraction=0.04, pad=0.02)
    ax[0].set_ylabel('Latitude (°)')
    fig.suptitle('COSMO-SkyMed 1-day tandem pair (2020-07-12/13), ISCE2 stripmapApp end-to-end test — topography NOT removed (void DEM)', fontsize=11, color=INK2)
    fig.tight_layout(); fig.savefig(f'{OUT}/00-key.png', dpi=110); plt.close(fig)


# ---------- 01 workflow diagram ----------
def fig_workflow():
    fig, ax = plt.subplots(figsize=(13, 6.2)); ax.set_xlim(-0.15, 13); ax.set_ylim(0, 6.2); ax.axis('off')

    def box(x, y, w, h, title, body, fc='#eef4fc', ec='#2a78d6'):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle='round,pad=0.02,rounding_size=0.12', fc=fc, ec=ec, lw=1.2))
        ax.text(x + 0.12, y + h - 0.18, title, fontsize=10.5, weight='bold', va='top', color=INK)
        ax.text(x + 0.12, y + h - 0.55, body, fontsize=8.6, va='top', color=INK2, linespacing=1.35)

    def arr(x0, y0, x1, y1):
        ax.annotate('', xy=(x1, y1), xytext=(x0, y0), arrowprops=dict(arrowstyle='->', color=MUTED, lw=1.4))

    box(0.0, 3.5, 3.5, 2.5, 'N2 L1A HDF5', 'ROOT: Radar Frequency, Look Side,\n Doppler Centroid (scalar),\n 60 ECEF state vectors, attitude\nS01: PRF, chirp rate/length,\n look angle\nS01/SBI: lines x samples,\n zero-Doppler az./range times', '#f6f6f4', MUTED)
    box(3.8, 3.5, 3.6, 2.5, 'N2MetadataEngine', '_find_attr(): case/space-insensitive keys\nderive: wavelength = c/f\n R0 = c*tau0/2, fs = c/(2*dr)\n incidence from look angle + height\n Doppler = [scalar] constant poly\nMapping_Report_*.txt (flushed per line)')
    box(8.0, 3.5, 4.8, 2.5, 'sitecustomize.py (PYTHONPATH head)', 'monkey-patch COSMO_SkyMed_SLC:\n parse() / populateMetadata(): run original,\n  suppress KeyError, then inject N2 values\n  into Frame / Instrument / Orbit\n extractImage(): set image length,\n  sparse-pad SLC to lines*samples*8 B\nruntime: skip failing runRefineSecondaryTiming,\n normalise DataAccessor mode r -> read')
    arr(3.5, 4.75, 3.8, 4.75); arr(7.4, 4.75, 8.0, 4.75)
    steps = ['Preprocess', 'VerifyDEM', 'Topo', 'Geo2rdr', 'ResampleSlc', 'Refine\nSecTiming*', 'Interferogram', 'Coherence', 'Filter', 'Geocode', 'snaphu\nunwrap']
    ax.text(0.2, 2.85, 'ISCE2 stripmapApp.py with sensor name = COSMO_SKYMED_SLC (unchanged ISCE2 install)', fontsize=10, weight='bold', color=INK)
    x = 0.2
    for i, s in enumerate(steps):
        w = 1.0
        ax.add_patch(FancyBboxPatch((x, 1.85), w, 0.7, boxstyle='round,pad=0.02,rounding_size=0.08', fc='#e8f6f0' if '*' not in s else '#fdf0e9', ec='#1baf7a' if '*' not in s else '#eb6834', lw=1))
        ax.text(x + w / 2, 2.2, s, ha='center', va='center', fontsize=7.4, color=INK, linespacing=1.1)
        if i < len(steps) - 1:
            arr(x + w, 2.2, x + w + 0.08, 2.2)
        x += w + 0.08
    arr(10.4, 3.5, 6.5, 2.6)
    ax.text(0.2, 1.3, '* auto-skipped on failure: needed for the 1x1-pixel structure-only test file, but on real data a silent skip leaves coregistration un-refined (handoff manual G-1).', fontsize=8.6, color=INK2)
    ax.text(0.2, 0.85, 'Verification paths on this server:  (a) N2 structure-only file (1x1 px, self-pair) -> pipeline completes, all output pixels = 0;', fontsize=8.6, color=INK2)
    ax.text(0.2, 0.5, '(b) real COSMO-SkyMed tandem pair through the same ISCE2 chain (native CSK reader) -> interferogram, coherence, snaphu unwrap.', fontsize=8.6, color=INK2)
    ax.text(0.2, 0.12, 'Two-date real N2 data: not processed on this server (on-site run planned on the data owner\'s laptop).', fontsize=8.6, color='#e34948')
    fig.savefig(f'{OUT}/01-workflow.png', dpi=110, bbox_inches='tight'); plt.close(fig)


# ---------- 02 N2 geometry from header ----------
def fig_n2_geometry():
    import cartopy.crs as ccrs, cartopy.io.shapereader as shp
    from cartopy.feature import ShapelyFeature
    with h5py.File(N2H5, 'r') as f:
        r = f.attrs; b = f['S01/SBI'].attrs
        ts = np.array(r['State Vectors Times'], float); P = np.array(r['ECEF Satellite Position'], float).reshape(-1, 3); V = np.array(r['ECEF Satellite Velocity'], float).reshape(-1, 3)
        t0 = float(b['Zero Doppler Azimuth First Time']); t1 = float(b['Zero Doppler Azimuth Last Time'])
        r0 = float(b['Zero Doppler Range First Time']); r1 = float(b['Zero Doppler Range Last Time'])
    track = np.array([G.ecef2llh(*p)[:2] for p in P])
    corners = []
    for t, rt in ((t0, r0), (t0, r1), (t1, r1), (t1, r0)):
        S, Vs = G.interp_sv(t, ts, P, V)
        T, _ = G.rd_geolocate(S, Vs, G.C * rt / 2, right=True, h=0.0)
        corners.append(G.ecef2llh(*T)[:2])
    corners = np.array(corners + [corners[0]])
    ax = plt.figure(figsize=(8, 6.2)).add_subplot(projection=ccrs.PlateCarree())
    ax.set_extent([123.5, 130.5, 33.0, 38.6])
    land = shp.natural_earth(resolution='10m', category='physical', name='land')
    ax.add_feature(ShapelyFeature(shp.Reader(land).geometries(), ccrs.PlateCarree()), fc='#f0efec', ec=MUTED, lw=0.5)
    ax.plot(track[:, 1], track[:, 0], '-', color=SER[0], lw=2, transform=ccrs.PlateCarree(), label='N2 orbit ground track (60 state vectors, ±30 s)')
    ax.annotate('', xy=(track[-1, 1], track[-1, 0]), xytext=(track[-8, 1], track[-8, 0]), arrowprops=dict(arrowstyle='->', color=SER[0], lw=2))
    ax.fill(corners[:, 1], corners[:, 0], color=SER[1], alpha=0.35, transform=ccrs.PlateCarree())
    ax.plot(corners[:, 1], corners[:, 0], color=SER[1], lw=1.5, transform=ccrs.PlateCarree(), label='Scene footprint (range-Doppler, h=0)')
    ax.plot(127.73, 35.34, marker='^', ms=9, color=INK, transform=ccrs.PlateCarree(), ls='none', label='Jirisan summit (reference)')
    gl = ax.gridlines(draw_labels=True, lw=0.3, color=MUTED); gl.top_labels = gl.right_labels = False
    ax.legend(loc='lower right', fontsize=8.5, frameon=True)
    ax.set_title('NEXTSat-2 stripmap, 2025-03-11 21:24 UTC, ascending, right-looking\n'
                 'recomputed from header: incidence 30.0–30.5° (spoof formula 31.0°), footprint ~10 km (ground range) x 55 km (azimuth)', fontsize=10)
    plt.savefig(f'{OUT}/02-n2-geometry.png', dpi=110, bbox_inches='tight'); plt.close()
    return corners


# ---------- 03 CSK wrapped vs unwrapped (radar) ----------
def fig_unw():
    ifg = CSK + '/interferogram'
    W, L = dims(ifg + '/topophase.cor.xml')[:2]
    z = np.fromfile(ifg + '/filt_topophase.flat', np.complex64).reshape(L, W)
    unw = np.fromfile(ifg + '/filt_topophase.unw.phase2', np.float32).reshape(L, W)
    cc = np.fromfile(ifg + '/filt_topophase.unw.phase2.conncomp', np.uint8).reshape(L, W)
    ph = np.where(np.abs(z) > 0, np.angle(z), np.nan)
    u = np.where(cc > 0, unw, np.nan)
    u = u - np.nanmedian(u)
    fig, ax = plt.subplots(1, 2, figsize=(12, 5.6))
    im0 = ax[0].imshow(ph, cmap='twilight', vmin=-np.pi, vmax=np.pi, interpolation='nearest')
    lo, hi = np.nanpercentile(u, [2, 98])
    im1 = ax[1].imshow(u, cmap='RdBu_r', vmin=-max(abs(lo), abs(hi)), vmax=max(abs(lo), abs(hi)))
    fig.colorbar(im0, ax=ax[0], fraction=0.045, label='wrapped phase (rad)')
    cb = fig.colorbar(im1, ax=ax[1], fraction=0.045, label='unwrapped phase rel. median (rad)')
    for a in ax: a.set_xlabel('range (looks)'); a.set_ylabel('azimuth (looks)')
    ax[0].set_title('Filtered interferogram, radar geometry (1638 x 1775)', fontsize=10.5)
    ax[1].set_title(f'snaphu MCF unwrap: 1 component, 97.6% px\n p2–p98 span {hi-lo:.0f} rad = {(hi-lo)/2/np.pi:.0f} fringes', fontsize=10.5)
    fig.tight_layout(); fig.savefig(f'{OUT}/03-csk-unwrap.png', dpi=110); plt.close(fig)


# ---------- 04 DEM check ----------
def fig_dem():
    ifg = CSK + '/interferogram'; geom = CSK + '/geometry'
    Wd, Ld, ext = geo_extent(CSK + '/interferogram/filt_topophase.flat.geo.xml')
    used = np.fromfile(CSK + '/dem.crop', np.int16).reshape(Ld, Wd)
    with rasterio.open(DEMP) as d:
        win = rasterio.windows.from_bounds(ext[0], ext[2], ext[1], ext[3], d.transform)
        prep = d.read(1, window=win, out_shape=(Ld // 2, Wd // 2))
    W, L = dims(ifg + '/topophase.cor.xml')[:2]
    unw = np.fromfile(ifg + '/filt_topophase.unw.phase2', np.float32).reshape(L, W)
    cc = np.fromfile(ifg + '/filt_topophase.unw.phase2.conncomp', np.uint8).reshape(L, W)
    coh = np.fromfile(ifg + '/topophase.cor', np.float32).reshape(L, 2, W)[:, 1, :]
    lat = np.fromfile(geom + '/lat.rdr', np.float64).reshape(L, W); lon = np.fromfile(geom + '/lon.rdr', np.float64).reshape(L, W)
    s = (slice(None, None, 4), slice(None, None, 4))
    u, la, lo, c, k = unw[s].ravel(), lat[s].ravel(), lon[s].ravel(), coh[s].ravel(), cc[s].ravel()
    with rasterio.open(DEMP) as d:
        cols, rows = (~d.transform) * (lo, la); rows = np.floor(rows).astype(int); cols = np.floor(cols).astype(int)
        ok = (rows >= 0) & (rows < d.height) & (cols >= 0) & (cols < d.width); a = d.read(1)
    h = np.full(u.shape, np.nan); h[ok] = a[rows[ok], cols[ok]]
    m = ok & (k > 0) & (c > 0.3) & np.isfinite(h) & (np.abs(la) > 1)
    x, y = h[m], u[m]; p = np.polyfit(x, y, 1); r = np.corrcoef(x, y)[0, 1]
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.6))
    im0 = ax[0].imshow(used, cmap='terrain', vmin=-60, vmax=1000, extent=ext, aspect='auto')
    ax[0].set_title(f'DEM actually used by ISCE2\n(SRTM void >60°S → constant {used.min()}..{used.max()} m)', fontsize=10)
    im1 = ax[1].imshow(prep, cmap='terrain', vmin=-60, vmax=1000, extent=ext, aspect='auto')
    ax[1].set_title('External DEM prepared (not applied:\ndemFilename set outside <insar> component)', fontsize=10)
    fig.colorbar(im1, ax=ax[1], fraction=0.04, label='height (m)')
    for a_ in ax[:2]: a_.set_xlabel('Longitude (°E)')
    ax[0].set_ylabel('Latitude (°)')
    idx = np.random.default_rng(0).choice(x.size, min(20000, x.size), replace=False)
    ax[2].scatter(x[idx], y[idx], s=2, alpha=0.25, color=SER[0], lw=0)
    xx = np.linspace(np.percentile(x, 1), np.percentile(x, 99), 10)
    ax[2].plot(xx, np.polyval(p, xx), color=SER[1], lw=2, label=f'fit: {p[0]:.3f} rad/m, r = {r:.2f}')
    ax[2].plot(xx, np.polyval([-2 * np.pi / 32.45, np.polyval(p, xx.mean()) + 2 * np.pi / 32.45 * xx.mean()], xx), '--', color=INK2, lw=1.4, label='topography-only expectation\n(B⊥≈156 m → 2π/32 m = 0.194 rad/m)')
    ax[2].set_xlabel('external DEM height (m)'); ax[2].set_ylabel('unwrapped phase (rad)'); ax[2].legend(fontsize=8.5, frameon=False)
    ax[2].set_title('Unwrapped phase vs DEM height (coh > 0.3)', fontsize=10)
    fig.tight_layout(); fig.savefig(f'{OUT}/04-dem-check.png', dpi=110); plt.close(fig)


# ---------- 05 NDVI curves ----------
PARKS = [('설악산', 'Seoraksan'), ('오대산', 'Odaesan'), ('치악산', 'Chiaksan'), ('주왕산', 'Juwangsan'), ('지리산', 'Jirisan'), ('무등산', 'Mudeungsan')]


def fig_ndvi():
    fig, ax = plt.subplots(figsize=(11, 5))
    for i, (ko, en) in enumerate(PARKS):
        f = glob.glob(f'{NDVI}/{ko} 국립공원/change_monitoring_ndvi_*.csv')[0]
        rows = list(csv.DictReader(open(f, encoding='utf-8')))
        d = [dt.date.fromisoformat(r['Date']) for r in rows]; v = [float(r['Mean Value']) for r in rows]
        area = float(rows[0]['Area (km²)'])
        ax.plot(d, v, '-o', color=SER[i], lw=2, ms=4, label=f'{en} ({area:.0f} km², n={len(v)})')
    ax.set_ylabel('park-mean NDVI'); ax.set_ylim(0.1, 0.7); ax.grid(axis='y', color='#e6e5e1', lw=0.6)
    ax.legend(fontsize=8.5, ncol=2, frameon=False, loc='upper left')
    ax.set_title('Sentinel-2 NDVI, park-mean per scene, 2025 (6 national parks) — residual cloud lowers some summer points', fontsize=11)
    fig.tight_layout(); fig.savefig(f'{OUT}/05-ndvi-parks.png', dpi=110); plt.close(fig)


# ---------- 06 NDVI overlay Jirisan winter vs summer ----------
def fig_ndvi_maps():
    from PIL import Image
    a = Image.open(glob.glob(f'{NDVI}/지리산 국립공원/20250121T*_ndvi_overlay_*.png')[0]).convert('RGB')
    b = Image.open(glob.glob(f'{NDVI}/지리산 국립공원/20250710T*_ndvi_overlay_*.png')[0]).convert('RGB')
    fig, ax = plt.subplots(1, 2, figsize=(13, 5))
    for x_, im, t in zip(ax, (a, b), ('2025-01-21 (winter)', '2025-07-10 (summer; pale patches = cloud)')):
        im.thumbnail((1400, 1400)); x_.imshow(np.asarray(im)); x_.set_title(f'Jirisan NP — Sentinel-2 NDVI overlay, {t}', fontsize=10.5); x_.axis('off')
    fig.tight_layout(); fig.savefig(f'{OUT}/06-ndvi-jirisan.png', dpi=110); plt.close(fig)


if __name__ == '__main__':
    which = sys.argv[1:] or ['key', 'workflow', 'geom', 'unw', 'dem', 'ndvi', 'ndvimap']
    fn = dict(key=fig_key, workflow=fig_workflow, geom=fig_n2_geometry, unw=fig_unw, dem=fig_dem, ndvi=fig_ndvi, ndvimap=fig_ndvi_maps)
    for w in which:
        print(w, fn[w]())
