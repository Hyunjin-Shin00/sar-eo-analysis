"""Recompute coherence / phase / unwrapped-displacement statistics from ISCE2 binary outputs (read-only)."""
import sys, os, json
import numpy as np
import xml.etree.ElementTree as ET


def dims(xml):
    r = ET.parse(xml).getroot()
    g = lambda n: r.find(f".//property[@name='{n}']/value").text.strip()
    return int(g('width')), int(g('length'))


def stats(a, name):
    a = a[np.isfinite(a)]
    if a.size == 0:
        return {name: 'empty'}
    q = np.percentile(a, [5, 25, 50, 75, 95])
    return {name: dict(n=int(a.size), mean=float(a.mean()), p5=float(q[0]), p25=float(q[1]), median=float(q[2]), p75=float(q[3]), p95=float(q[4]),
                       frac_gt_0_3=float((a > 0.3).mean()), frac_gt_0_5=float((a > 0.5).mean()), frac_zero=float((a == 0).mean()))}


def ifg_dir(d, lam):
    out = {}
    W, L = dims(f'{d}/topophase.cor.xml')
    out['radar dims (W x L)'] = (W, L)
    cor = np.fromfile(f'{d}/topophase.cor', np.float32).reshape(L, 2, W)  # BIL 2 bands
    out.update(stats(cor[:, 1, :], 'topophase.cor band2 (coherence)'))
    out.update(stats(cor[:, 0, :], 'topophase.cor band1 (magnitude)'))
    ph = np.fromfile(f'{d}/phsig.cor', np.float32).reshape(L, W)
    out.update(stats(ph, 'phsig.cor'))
    z = np.fromfile(f'{d}/filt_topophase.flat', np.complex64).reshape(L, W)
    out['filt_topophase.flat: frac |z|==0'] = float((np.abs(z) == 0).mean())
    out['filt_topophase.flat: frac non-finite'] = float((~np.isfinite(z)).mean())
    unw_p = f'{d}/filt_topophase.unw.phase2'
    if os.path.exists(unw_p):
        unw = np.fromfile(unw_p, np.float32).reshape(L, W)
        cc = np.fromfile(unw_p + '.conncomp', np.uint8).reshape(L, W)
        out['conncomp labels'] = {int(k): int(v) for k, v in zip(*np.unique(cc, return_counts=True))}
        m = (cc > 0) & np.isfinite(unw)
        u = unw[m]
        out['unw phase rad (p2,p50,p98)'] = [float(x) for x in np.percentile(u, [2, 50, 98])]
        span = np.percentile(u, 98) - np.percentile(u, 2)
        out['unw phase span p2-p98 (rad)'] = float(span)
        out['equiv LOS span p2-p98 (m) = lam/4pi*span'] = float(lam / (4 * np.pi) * span)
        out['fringes in span (span/2pi)'] = float(span / (2 * np.pi))
        # consistency: rewrap(unw) vs wrapped filt phase
        wr = np.angle(z)
        d_ = np.angle(np.exp(1j * (unw - wr)))
        out['rewrap(unw)-wrapped |diff| median rad (masked)'] = float(np.median(np.abs(d_[m])))
        # coherence-masked portion
        coh = cor[:, 1, :]
        mh = m & (coh > 0.5)
        if mh.sum():
            uh = unw[mh]
            sp = np.percentile(uh, 98) - np.percentile(uh, 2)
            out['coh>0.5 pixels: frac'] = float(mh.mean())
            out['coh>0.5: LOS span p2-p98 (m)'] = float(lam / (4 * np.pi) * sp)
    return out


def geo_cor(d):
    p = f'{d}/phsig.cor.geo'
    if not os.path.exists(p):
        return {}
    W, L = dims(p + '.xml')
    a = np.fromfile(p, np.float32).reshape(L, W)
    a = np.where(a == 0, np.nan, a)
    return stats(a, 'phsig.cor.geo (nonzero)')


if __name__ == '__main__':
    res = {}
    csk = sys.argv[1]; n2 = sys.argv[2]
    res['CSK_1day_tandem'] = ifg_dir(csk + '/interferogram', 0.031228381041666666)
    res['CSK_1day_tandem'].update(geo_cor(csk + '/interferogram'))
    res['N2_tiny_selfpair'] = ifg_dir(n2 + '/interferogram', 0.03106657595854922)
    print(json.dumps(res, indent=1, ensure_ascii=False))
