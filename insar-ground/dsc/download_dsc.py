# -*- coding: utf-8 -*-
"""지반침하 분석 - 하강궤도(DSC) Sentinel-1 SLC 일괄 다운로드.
usage: download_dsc.py [--dry] [--workers N] [--track 134|61]

설계 근거
 · 상승궤도(ASC)로 이미 분석한 7 AOI 중 송도 제외 6 AOI에 대해 '다른 궤도' = 하강궤도 확보.
 · 한 씬이 여러 AOI를 덮으므로 궤도별 1벌만 받아 AOI로 자른다(사용자 지시).
     track 134 → 강동 · 서대문 · 광명 · 양양   (서울·양양이 194씬 공유)
     track  61 → 만덕 · 사상                  (211씬 전부 두 AOI 공통)
 · 기간 = 하강궤도 가용 전 기간(2014-10 ~ 현재). 2022~2024는 S1B 고장으로 AOI당 1~3장뿐이며
   ASF·ESA CDSE 두 카탈로그로 확인함. 해당 구간은 SBAS 망 구성 불가 → 별도 스택으로 분리 처리.
 · AOI 완전포함 검증 완료(부분 걸침 0일).
재실행 안전: 파일 크기가 기대값과 일치하면 건너뛴다(이어받기).
"""
import os, sys, json, time, netrc, threading, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

os.environ.pop("PYTHONPATH", None)
import asf_search as asf

ROOT = "<WORK_ROOT>/CLAB_DSC"
AOI = {"강동": (37.5097, 37.5840, 127.1033, 127.1994),
       "서대문": (37.5407, 37.5977, 126.8844, 126.9636),
       "광명": (37.3812, 37.4442, 126.8410, 126.9181),
       "양양": (38.0596, 38.1536, 128.5469, 128.6751),
       "만덕": (35.1644, 35.2508, 129.0092, 129.1379),
       "사상": (35.1294, 35.1664, 128.9677, 129.0049)}
JOBS = {134: dict(name="t134_seoul_yangyang", regs=["강동", "서대문", "광명", "양양"]),
        61:  dict(name="t061_busan",          regs=["만덕", "사상"])}
START, END = "2014-10-01", "2026-12-31"
LOCK = threading.Lock()


def log(msg, fp=None):
    line = f"[{time.strftime('%F %T')}] {msg}"
    with LOCK:
        print(line, flush=True)
        if fp:
            open(fp, "a").write(line + "\n")


def wkt(S, N, W, E):
    return f"POLYGON(({W} {S},{E} {S},{E} {N},{W} {N},{W} {S}))"


def session():
    n = netrc.netrc(os.path.expanduser("~/.netrc"))
    u, _, p = n.authenticators("urs.earthdata.nasa.gov")
    return asf.ASFSession().auth_with_creds(u, p)


def collect(track):
    """AOI 합집합 씬 목록(중복 제거). 반환 {fileName: product}"""
    out = {}
    for rg in JOBS[track]["regs"]:
        r = asf.search(platform=[asf.PLATFORM.SENTINEL1], processingLevel=[asf.PRODUCT_TYPE.SLC],
                       beamMode=[asf.BEAMMODE.IW], flightDirection="DESCENDING",
                       relativeOrbit=track, intersectsWith=wkt(*AOI[rg]),
                       start=START, end=END, maxResults=6000)
        for x in r:
            out.setdefault(x.properties["fileName"], x)
    return out


def fetch(prod, outdir, sess, fp, idx, tot):
    fn = prod.properties["fileName"]
    exp = int(prod.properties.get("bytes") or 0)
    dst = os.path.join(outdir, fn)
    if os.path.exists(dst) and exp and abs(os.path.getsize(dst) - exp) <= 4096:
        return ("skip", fn, 0)
    for attempt in (1, 2, 3):
        try:
            t0 = time.time()
            prod.download(path=outdir, session=sess)
            got = os.path.getsize(dst) if os.path.exists(dst) else 0
            if exp and abs(got - exp) > 4096:
                raise IOError(f"크기 불일치 {got} != {exp}")
            log(f"  ({idx}/{tot}) OK   {fn}  {got/1e9:.2f}GB  {time.time()-t0:.0f}s", fp)
            return ("ok", fn, got)
        except Exception as e:
            log(f"  ({idx}/{tot}) 실패{attempt}/3 {fn}: {e}", fp)
            if os.path.exists(dst):
                try:
                    os.remove(dst)
                except OSError:
                    pass
            time.sleep(10 * attempt)
    return ("fail", fn, 0)


def main():
    dry = "--dry" in sys.argv
    workers = 4
    tracks = list(JOBS)
    for i, a in enumerate(sys.argv):
        if a == "--workers":
            workers = int(sys.argv[i + 1])
        if a == "--track":
            tracks = [int(sys.argv[i + 1])]
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    fp = os.path.join(ROOT, "logs", f"download_{time.strftime('%Y%m%d_%H%M%S')}.log")
    sess = None if dry else session()

    grand = {}
    for tr in tracks:
        j = JOBS[tr]
        outdir = os.path.join(ROOT, j["name"], "slc")
        os.makedirs(outdir, exist_ok=True)
        log(f"■ track {tr} → {j['name']}  (AOI: {' · '.join(j['regs'])})", fp)
        prods = collect(tr)
        days = sorted({p.properties["startTime"][:10] for p in prods.values()})
        gb = sum(int(p.properties.get("bytes") or 0) for p in prods.values()) / 1e9
        have = sum(1 for f, p in prods.items()
                   if os.path.exists(os.path.join(outdir, f))
                   and abs(os.path.getsize(os.path.join(outdir, f))
                           - int(p.properties.get("bytes") or 0)) <= 4096)
        log(f"  씬 {len(prods)} · 고유일 {len(days)} · {days[0]}~{days[-1]} · {gb:.1f}GB "
            f"· 이미 보유 {have} · 받을 것 {len(prods)-have}", fp)
        man = {"track": tr, "aois": {k: AOI[k] for k in j["regs"]},
               "period": [days[0], days[-1]], "n_scene": len(prods), "n_day": len(days),
               "total_gb": round(gb, 1), "queried_at": time.strftime("%F %T"),
               "scenes": [{"file": f, "date": p.properties["startTime"][:10],
                           "platform": p.properties["platform"],
                           "frame": p.properties.get("frameNumber"),
                           "bytes": p.properties.get("bytes"),
                           "url": p.properties.get("url")}
                          for f, p in sorted(prods.items(),
                                             key=lambda z: z[1].properties["startTime"])]}
        json.dump(man, open(os.path.join(ROOT, j["name"], "manifest.json"), "w"),
                  ensure_ascii=False, indent=1)
        grand[tr] = man
        if dry:
            continue
        todo = [(f, p) for f, p in sorted(prods.items(),
                                          key=lambda z: z[1].properties["startTime"])]
        ok = sk = fl = 0
        got_gb = 0.0
        with ThreadPoolExecutor(max_workers=workers) as ex:
            fut = {ex.submit(fetch, p, outdir, sess, fp, i + 1, len(todo)): f
                   for i, (f, p) in enumerate(todo)}
            for k, fu in enumerate(as_completed(fut), 1):
                st, fn, nb = fu.result()
                ok += st == "ok"; sk += st == "skip"; fl += st == "fail"
                got_gb += nb / 1e9
                if k % 20 == 0:
                    log(f"  … 진행 {k}/{len(todo)} (신규 {ok} · 기존 {sk} · 실패 {fl} · {got_gb:.0f}GB)", fp)
        log(f"  track {tr} 완료: 신규 {ok} · 기존 {sk} · 실패 {fl} · {got_gb:.1f}GB", fp)

    json.dump({str(k): {kk: vv for kk, vv in v.items() if kk != "scenes"}
               for k, v in grand.items()},
              open(os.path.join(ROOT, "SUMMARY.json"), "w"), ensure_ascii=False, indent=1)
    log(f"→ 로그 {fp}", fp)


if __name__ == "__main__":
    main()
