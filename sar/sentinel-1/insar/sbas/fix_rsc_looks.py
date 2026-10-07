#!/usr/bin/env python3
"""멀티룩한 파일의 .rsc 를 실제 룩 수에 맞게 고친다.

prep_isce.py 는 기준영상 메타에서 값을 읽어 오므로 항상 단일룩 값을 쓴다. 멀티룩
산출물에 그대로 두면
  · NCORRLOOKS 가 16배 작아 결맞음->위상분산 환산이 틀리고 (weightFunc=var 일 때 가중치가 왜곡)
  · 화소 크기가 1/룩 이라 공간필터 창 크기가 어긋난다.
geocode 는 lat/lon 룩업표를 쓰므로 영향받지 않는다.

usage: fix_rsc_looks.py <sbas_dir> <alooks> <rlooks>
"""
import glob
import os
import sys


def patch(path, alk, rlk):
    kv, order = {}, []
    for line in open(path):
        if not line.strip():
            continue
        k = line.split()[0]
        v = line[len(k):].strip()
        if k not in kv:
            order.append(k)
        kv[k] = v
    if kv.get('ALOOKS') == str(alk) and kv.get('RLOOKS') == str(rlk):
        return False
    base_a = float(kv['AZIMUTH_PIXEL_SIZE']) / max(1, int(kv.get('ALOOKS', 1)))
    base_r = float(kv['RANGE_PIXEL_SIZE']) / max(1, int(kv.get('RLOOKS', 1)))
    base_n = float(kv['NCORRLOOKS']) / max(1, int(kv.get('ALOOKS', 1)) * int(kv.get('RLOOKS', 1)))
    kv['ALOOKS'] = str(alk)
    kv['RLOOKS'] = str(rlk)
    kv['AZIMUTH_PIXEL_SIZE'] = repr(base_a * alk)
    kv['RANGE_PIXEL_SIZE'] = repr(base_r * rlk)
    kv['NCORRLOOKS'] = repr(base_n * alk * rlk)
    with open(path, 'w') as f:
        for k in order:
            f.write(f'{k:<25s} {kv[k]}\n')
    return True


def main():
    sb, alk, rlk = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    targets = (glob.glob(f'{sb}/Igrams/*/*.rsc')
               + glob.glob(f'{sb}/geom_reference/*.rsc'))
    n = sum(patch(p, alk, rlk) for p in targets if os.path.exists(p))
    print(f'{sb}: {n}/{len(targets)} 개 .rsc 를 ALOOKS={alk} RLOOKS={rlk} 로 보정')
    sample = sorted(glob.glob(f'{sb}/Igrams/*/*.unw.rsc'))[:1]
    for p in sample:
        d = dict(l.split(None, 1) for l in open(p) if l.strip())
        for k in ('ALOOKS', 'RLOOKS', 'AZIMUTH_PIXEL_SIZE', 'RANGE_PIXEL_SIZE', 'NCORRLOOKS'):
            print(f'   {k:22s} {d[k].strip()}')


if __name__ == '__main__':
    main()
