"""Recompute N2 / CSK geometry from HDF5 attributes only (read-only).
- N2: wavelength, incidence (spoof formula vs rigorous range-Doppler), scene centre, timing consistency
- CSK pair: perpendicular baseline at scene centre
"""
import sys, math, datetime as dt
import numpy as np, h5py

C = 299792458.0
A, B = 6378137.0, 6356752.314245
E2 = 1 - (B / A) ** 2


def ecef2llh(x, y, z):
    lon = math.atan2(y, x); p = math.hypot(x, y); lat = math.atan2(z, p * (1 - E2))
    for _ in range(10):
        N = A / math.sqrt(1 - E2 * math.sin(lat) ** 2)
        h = p / math.cos(lat) - N
        lat = math.atan2(z, p * (1 - E2 * N / (N + h)))
    return math.degrees(lat), math.degrees(lon), h


def llh2ecef(lat, lon, h):
    lat, lon = math.radians(lat), math.radians(lon)
    N = A / math.sqrt(1 - E2 * math.sin(lat) ** 2)
    return np.array([(N + h) * math.cos(lat) * math.cos(lon), (N + h) * math.cos(lat) * math.sin(lon), (N * (1 - E2) + h) * math.sin(lat)])


def interp_sv(t, ts, P, V):
    # Hermite-free: cubic polyfit around t (adequate for <10 s scenes)
    i = np.argsort(np.abs(ts - t))[:8]
    pp = np.array([np.polyval(np.polyfit(ts[i] - t, P[i, k], 5), 0) for k in range(3)])
    vv = np.array([np.polyval(np.polyfit(ts[i] - t, V[i, k], 5), 0) for k in range(3)])
    return pp, vv


def rd_geolocate(S, Vs, R, right=True, h=0.0):
    """zero-Doppler: target on ellipsoid(h), |T-S|=R, (T-S).V=0"""
    v = Vs / np.linalg.norm(Vs); n = -S / np.linalg.norm(S)
    c = np.cross(v, n); c /= np.linalg.norm(c)  # cross-track (left for v x down?)
    n2 = np.cross(c, v)
    sgn = -1 if right else 1

    def f(th):
        T = S + R * (math.cos(th) * n2 + sgn * math.sin(th) * c)
        la, lo, hh = ecef2llh(*T)
        return hh - h, T
    lo_, hi_ = 0.0, math.radians(60)
    for _ in range(80):
        mid = 0.5 * (lo_ + hi_)
        if f(mid)[0] > 0: hi_ = mid
        else: lo_ = mid
    th = 0.5 * (lo_ + hi_)
    T = f(th)[1]
    return T, math.degrees(th)


def incidence(S, T):
    la, lo, _ = ecef2llh(*T)
    up = np.array([math.cos(math.radians(la)) * math.cos(math.radians(lo)), math.cos(math.radians(la)) * math.sin(math.radians(lo)), math.sin(math.radians(la))])
    los = (S - T) / np.linalg.norm(S - T)
    return math.degrees(math.acos(np.dot(up, los)))


def n2(path):
    with h5py.File(path, 'r') as f:
        r = f.attrs; s = f['S01'].attrs; b = f['S01/SBI'].attrs
        rf = float(r['Radar Frequency']); H = float(r['Satellite Height']); look = float(s['Look Angle'])
        prf = float(s['PRF']); nl = int(b['Line Samples']); ns = int(b['Column Samples'])
        lti = float(b['Line Time Interval']); cti = float(b['Column Time Interval']); dr = float(b['Column Spacing'])
        t0 = float(b['Zero Doppler Azimuth First Time']); t1 = float(b['Zero Doppler Azimuth Last Time'])
        r0t = float(b['Zero Doppler Range First Time']); r1t = float(b['Zero Doppler Range Last Time'])
        ts = np.array(r['State Vectors Times'], float); P = np.array(r['ECEF Satellite Position'], float).reshape(-1, 3); V = np.array(r['ECEF Satellite Velocity'], float).reshape(-1, 3)
        sbi_shape = f['S01/SBI'].shape
    out = {}
    out['SBI dataset shape (actual pixels stored)'] = sbi_shape
    out['declared image size (lines x samples)'] = (nl, ns)
    out['wavelength m'] = C / rf
    sin_inc = (6371000.0 + H) / 6371000.0 * math.sin(math.radians(abs(look)))
    out['incidence (spoof formula, deg)'] = math.degrees(math.asin(sin_inc))
    out['start time UTC'] = dt.datetime.utcfromtimestamp(t0).isoformat()
    out['duration s (t1-t0)'] = t1 - t0
    out['duration s ((nl-1)*lti)'] = (nl - 1) * lti
    out['PRF vs 1/lti'] = (prf, 1 / lti)
    out['range samp. rate from dr (Hz)'] = C / (2 * dr)
    out['range samp. rate from cti (Hz)'] = 1 / cti
    out['swath time (ns-1)*cti vs r1-r0'] = ((ns - 1) * cti, r1t - r0t)
    R0 = C * r0t / 2; Rm = C * (r0t + r1t) / 4
    out['near slant range m'] = R0
    out['state vectors'] = (len(ts), float(ts.min() - t0), float(ts.max() - t0))
    tm = 0.5 * (t0 + t1)
    S, Vs = interp_sv(tm, ts, P, V)
    la, lo, hs = ecef2llh(*S)
    out['sat at mid: lat,lon,h'] = (la, lo, hs)
    out['|V| m/s'] = float(np.linalg.norm(Vs))
    for name, RR in (('near', R0), ('mid', Rm)):
        T, lk = rd_geolocate(S, Vs, RR, right=True, h=0.0)
        tl = ecef2llh(*T)
        out[f'{name}-range target lat,lon (h=0)'] = (tl[0], tl[1])
        out[f'{name}-range look angle (rigorous, deg)'] = lk
        out[f'{name}-range incidence (rigorous, deg)'] = incidence(S, T)
    return out


def csk_bperp(ref, sec):
    def load(p):
        with h5py.File(p, 'r') as f:
            r = f.attrs
            ts = np.array(r['State Vectors Times'], float) if 'State Vectors Times' in r else None
            P = np.array(r['ECEF Satellite Position'], float).reshape(-1, 3); V = np.array(r['ECEF Satellite Velocity'], float).reshape(-1, 3)
            ref_utc = r['Reference UTC']; ref_utc = ref_utc.decode() if isinstance(ref_utc, bytes) else str(ref_utc)
            s = f['S01'].attrs; b = f['S01/SBI'].attrs
            az0 = float(b['Zero Doppler Azimuth First Time']); az1 = float(b['Zero Doppler Azimuth Last Time'])
            r0 = float(b['Zero Doppler Range First Time']); cti = float(b['Column Time Interval']); ns = int(f['S01/SBI'].shape[1])
            rf = float(r['Radar Frequency'])
        return dict(ts=ts, P=P, V=V, ref=ref_utc, az0=az0, az1=az1, r0=r0, cti=cti, ns=ns, rf=rf)
    a = load(ref); b = load(sec)
    tm = 0.5 * (a['az0'] + a['az1'])
    S1, V1 = interp_sv(tm, a['ts'], a['P'], a['V'])
    Rm = C * (a['r0'] + 0.5 * a['ns'] * a['cti']) / 2
    T, lk = rd_geolocate(S1, V1, Rm, right=True, h=0.0)
    # secondary: find zero-Doppler time to T
    tb = 0.5 * (b['az0'] + b['az1'])
    for _ in range(30):
        S2, V2 = interp_sv(tb, b['ts'], b['P'], b['V'])
        fdt = np.dot(T - S2, V2) / np.dot(V2, V2)
        tb += fdt
        if abs(fdt) < 1e-7: break
    S2, V2 = interp_sv(tb, b['ts'], b['P'], b['V'])
    los = (T - S1) / np.linalg.norm(T - S1)
    Bv = S2 - S1
    bpar = np.dot(Bv, los)
    bperp = np.linalg.norm(Bv - bpar * los)
    # sign: positive if secondary is further from earth side... report magnitude
    tl = ecef2llh(*T)
    lam = C / a['rf']
    inc = incidence(S1, T)
    hamb = lam * np.linalg.norm(T - S1) * math.sin(math.radians(inc)) / (2 * bperp)
    return dict(ref_utc=a['ref'], centre=(tl[0], tl[1]), look=lk, inc=inc, B=float(np.linalg.norm(Bv)), bpar=float(bpar), bperp=float(bperp), height_of_ambiguity_m=float(hamb), wavelength=lam)


if __name__ == '__main__':
    n2p, cr, cs = sys.argv[1:4]
    print('=== N2 (structure_with_tiny_data_n2.h5) ===')
    for k, v in n2(n2p).items(): print(f'{k}: {v}')
    print('=== CSK pair baseline ===')
    for k, v in csk_bperp(cr, cs).items(): print(f'{k}: {v}')
