#!/usr/bin/env python3
"""Perpendicular/temporal baselines for the CSG stack, and master selection."""
import glob, sys, datetime
import numpy as np
sys.path.insert(0, '<DATA_ROOT>/CSK_PSInSAR/code')
from csg_sensor import COSMO_SkyMed_CSG

WGS_A, WGS_E2 = 6378137.0, 6.69437999014e-3

def llh2xyz(lat, lon, h):
    lat, lon = np.radians(lat), np.radians(lon)
    N = WGS_A / np.sqrt(1 - WGS_E2 * np.sin(lat) ** 2)
    return np.array([(N + h) * np.cos(lat) * np.cos(lon),
                     (N + h) * np.cos(lat) * np.sin(lon),
                     (N * (1 - WGS_E2) + h) * np.sin(lat)])

def zero_doppler_state(orbit, t0, target, span=6.0, step=0.02):
    """Satellite state at the zero-Doppler time for `target`."""
    best = None
    n = int(2 * span / step)
    for i in range(n + 1):
        t = t0 + datetime.timedelta(seconds=-span + i * step)
        try:
            sv = orbit.interpolateOrbit(t, method='hermite')
        except Exception:
            continue
        p = np.array(sv.getPosition()); v = np.array(sv.getVelocity())
        fd = abs(np.dot(v, target - p))
        if best is None or fd < best[0]:
            best = (fd, p, v, t)
    return best[1], best[2], best[3]

def main():
    files = sorted(glob.glob('<DATA_ROOT>/Cosmo-Skymed/*/*/CSG_*.h5'))
    import h5py
    scenes = []
    for f in files:
        o = COSMO_SkyMed_CSG(); o.hdf5 = f; o.parse()
        fr = o.getFrame()
        with h5py.File(f, 'r') as h:
            c = h.attrs['Scene Centre Geodetic Coordinates']
        tgt = llh2xyz(float(c[0]), float(c[1]), float(c[2]))
        p, v, t = zero_doppler_state(fr.getOrbit(), fr.getSensingMid(), tgt)
        scenes.append(dict(date=fr.getSensingStart().strftime('%Y%m%d'),
                           dt=fr.getSensingStart(), pos=p, vel=v, tgt=tgt,
                           sat=fr.getInstrument().getPlatform().getMission().decode()))
    scenes.sort(key=lambda s: s['date'])

    def bperp(m, s):
        los = m['tgt'] - m['pos']; R = np.linalg.norm(los); los = los / R
        vh = m['vel'] / np.linalg.norm(m['vel'])
        ph = np.cross(vh, los); ph /= np.linalg.norm(ph)
        B = s['pos'] - m['pos']
        bp = float(np.dot(B, ph))
        # sign convention: positive when secondary is further from target
        return bp if np.dot(B, los) <= 0 else bp

    print("=== 마스터 후보별 기선 통계 (28씬) ===")
    print(f"{'master':>10} {'Bperp범위(m)':>18} {'|Bperp|평균':>12} {'|Bperp|최대':>12} {'Btemp최대(일)':>14} {'점수':>8}")
    stats = []
    for m in scenes:
        bps = [bperp(m, s) for s in scenes]
        bts = [abs((s['dt'] - m['dt']).days) for s in scenes]
        ab = [abs(x) for x in bps]
        score = np.mean(ab) / 150.0 + np.mean(bts) / 100.0
        stats.append((score, m['date'], min(bps), max(bps), np.mean(ab), max(ab), max(bts)))
    for sc in sorted(stats)[:6]:
        print(f"{sc[1]:>10} {sc[2]:8.1f}..{sc[3]:7.1f} {sc[4]:12.1f} {sc[5]:12.1f} {sc[6]:14d} {sc[0]:8.3f}")

    best = sorted(stats)[0][1]
    m = [s for s in scenes if s['date'] == best][0]
    print(f"\n=== 추천 마스터 = {best} 기준 전체 기선 ===")
    print(f"{'date':>10} {'sat':>6} {'Bperp(m)':>10} {'Btemp(d)':>9}")
    for s in scenes:
        print(f"{s['date']:>10} {s['sat']:>6} {bperp(m, s):10.1f} {(s['dt']-m['dt']).days:9d}")

if __name__ == '__main__':
    main()
