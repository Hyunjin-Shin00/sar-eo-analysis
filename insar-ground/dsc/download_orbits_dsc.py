# -*- coding: utf-8 -*-
"""DSC 264장에 대응하는 S1B 정밀궤도(POEORB) 확보. usage: download_orbits_dsc.py [--dry]

방식
  · 필요 목록 = stage{1,2}_manifest.json 의 고유 (미션, 날짜) 264개. DSC는 전부 S1B.
  · 기존 CLAB/data1 내 EOF 를 전수 스캔해 유효기간이 해당 날짜를 덮으면 심볼릭 링크(재다운로드 안 함).
  · 부족분은 ESA step 미러에서 받는다(.EOF.zip → 압축해제). 실패 시 ASF s1qc(.netrc 인증)로 재시도.
  · 결과를 한 디렉토리에 모아 ISCE2 stackSentinel -o 로 바로 쓸 수 있게 한다.
POEORB 파일명 규칙  S1B_OPER_AUX_POEORB_OPOD_<생성>_V<시작>T225942_<종료>T005942.EOF
  → 유효구간이 (시작+1일) 하루를 온전히 덮는다. 관측일 D 를 덮는 파일은 시작=D-1.
"""
import os, sys, re, io, glob, json, zipfile, netrc, time
from datetime import datetime, timedelta
os.environ.pop("PYTHONPATH", None)
import requests

ROOT = "<WORK_ROOT>/CLAB_DSC"
OUT = os.path.join(ROOT, "orbits")
ESA = "https://step.esa.int/auxdata/orbits/Sentinel-1/POEORB"
ASF = "https://s1qc.asf.alaska.edu/aux_poeorb"
SCAN = ["<DATA_ROOT>/CLAB/**/*.EOF", "<WORK_ROOT>/**/*.EOF"]
PAT = re.compile(r"(S1[ABC])_OPER_AUX_(POEORB|RESORB)_OPOD_\d{8}T\d{6}"
                 r"_V(\d{8})T\d{6}_(\d{8})T\d{6}\.EOF")
_lst = {}


def need_list():
    out = set()
    for st, d in ((1, "t061_f475_busan"), (2, "t134_f466_capital")):
        for e in json.load(open(os.path.join(ROOT, d, "stage%d_manifest.json" % st))):
            out.add((e["platform"].replace("Sentinel-1", "S1"), e["date"]))
    return sorted(out)


def scan_existing():
    """{(미션, 날짜): [(종류, 경로)]}  — POEORB 우선"""
    have = {}
    for pat in SCAN:
        for p in glob.glob(pat, recursive=True):
            m = PAT.match(os.path.basename(p))
            if not m:
                continue
            mis, typ, s, e = m.groups()
            t, end = datetime.strptime(s, "%Y%m%d"), datetime.strptime(e, "%Y%m%d")
            while t <= end:
                have.setdefault((mis, t.strftime("%Y-%m-%d")), []).append((typ, p))
                t += timedelta(days=1)
    for k in have:
        have[k].sort(key=lambda z: z[0] != "POEORB")     # POEORB 먼저
    return have


def esa_listing(mis, y, m):
    k = (mis, y, m)
    if k in _lst:
        return _lst[k]
    url = "%s/%s/%04d/%02d/" % (ESA, mis, y, m)
    try:
        r = requests.get(url, timeout=90)
        names = sorted(set(re.findall(r"S1[ABC]_OPER_AUX_POEORB[0-9A-Za-z_.]*?\.EOF\.zip", r.text))) \
            if r.status_code == 200 else []
    except Exception:
        names = []
    _lst[k] = (url, names)
    return _lst[k]


def fetch_esa(mis, date):
    """관측일 date 를 덮는 EOF 확보. 시작=date-1 인 파일을 찾는다(전월 디렉토리도 확인)."""
    d = datetime.strptime(date, "%Y-%m-%d")
    want = (d - timedelta(days=1)).strftime("%Y%m%d")
    cands = [(d.year, d.month), ((d - timedelta(days=1)).year, (d - timedelta(days=1)).month)]
    for y, mo in dict.fromkeys(cands):
        url, names = esa_listing(mis, y, mo)
        for n in names:
            if "_V%sT" % want in n:
                r = requests.get(url + n, timeout=180)
                if r.status_code != 200:
                    continue
                with zipfile.ZipFile(io.BytesIO(r.content)) as z:
                    nm = [x for x in z.namelist() if x.endswith(".EOF")][0]
                    data = z.read(nm)
                dst = os.path.join(OUT, os.path.basename(nm))
                open(dst, "wb").write(data)
                return dst
    return None


def fetch_asf(mis, date, sess):
    d = datetime.strptime(date, "%Y-%m-%d")
    want = (d - timedelta(days=1)).strftime("%Y%m%d")
    if "asf" not in _lst:
        try:
            r = sess.get(ASF + "/", timeout=180)
            _lst["asf"] = sorted(set(re.findall(r"S1[ABC]_OPER_AUX_POEORB[0-9A-Za-z_.]*?\.EOF", r.text)))
        except Exception:
            _lst["asf"] = []
    for n in _lst["asf"]:
        if n.startswith(mis) and "_V%sT" % want in n:
            r = sess.get("%s/%s" % (ASF, n), timeout=180)
            if r.status_code == 200 and r.content[:5] == b"<?xml":
                dst = os.path.join(OUT, n)
                open(dst, "wb").write(r.content)
                return dst
    return None


def main():
    dry = "--dry" in sys.argv
    os.makedirs(OUT, exist_ok=True)
    need = need_list()
    have = scan_existing()
    print("필요 궤도파일 %d개 (고유 미션·날짜)" % len(need))
    link = [x for x in need if x in have]
    miss = [x for x in need if x not in have]
    print("  기존 보유 → 링크 %d개 · 새로 받을 것 %d개" % (len(link), len(miss)))
    if dry:
        print("  부족 날짜:", ", ".join(d for _, d in miss[:15]), "…" if len(miss) > 15 else "")
        return
    # ① 기존 보유 링크
    nl = 0
    for mis_, d in link:
        typ, src = have[(mis_, d)][0]
        dst = os.path.join(OUT, os.path.basename(src))
        if not os.path.exists(dst):
            os.symlink(src, dst)
            nl += 1
    print("  링크 생성 %d개" % nl)
    # ② 다운로드
    sess = requests.Session()
    try:
        u, _, p = netrc.netrc(os.path.expanduser("~/.netrc")).authenticators("urs.earthdata.nasa.gov")
        sess.auth = (u, p)
    except Exception:
        pass
    ok = fail = 0
    for i, (mis_, d) in enumerate(miss, 1):
        r = None
        try:
            r = fetch_esa(mis_, d)
        except Exception as e:                                  # noqa: BLE001
            print("    ESA 오류 %s: %s" % (d, str(e)[:70]))
        if not r:
            try:
                r = fetch_asf(mis_, d, sess)
                if r:
                    print("    (%d/%d) ASF 대체 %s" % (i, len(miss), d))
            except Exception as e:                              # noqa: BLE001
                print("    ASF 오류 %s: %s" % (d, str(e)[:70]))
        if r:
            ok += 1
            if i % 20 == 0 or i == len(miss):
                print("    … %d/%d (성공 %d · 실패 %d)" % (i, len(miss), ok, fail), flush=True)
        else:
            fail += 1
            print("    ★실패 %s %s — 궤도파일 못 찾음" % (mis_, d))
        time.sleep(0.3)
    print("  다운로드 성공 %d · 실패 %d" % (ok, fail))
    # ③ 최종 검증
    have2 = {}
    for p in glob.glob(os.path.join(OUT, "*.EOF")):
        m = PAT.match(os.path.basename(p))
        if not m:
            continue
        mis2, typ, s, e = m.groups()
        t, end = datetime.strptime(s, "%Y%m%d"), datetime.strptime(e, "%Y%m%d")
        while t <= end:
            have2[(mis2, t.strftime("%Y-%m-%d"))] = p
            t += timedelta(days=1)
    bad = [x for x in need if x not in have2]
    print("\n검증: 필요 %d개 중 확보 %d개 · 미확보 %d개" % (len(need), len(need) - len(bad), len(bad)))
    if bad:
        print("  미확보:", ", ".join(d for _, d in bad))
    print("→ %s  (파일 %d개)" % (OUT, len(glob.glob(os.path.join(OUT, "*.EOF")))))


if __name__ == "__main__":
    main()
