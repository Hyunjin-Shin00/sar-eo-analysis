#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""주소 + 기준일 → 지반침하 위험 보고서 PDF (+ 주의·위험 구역 GeoJSON)

세 단계를 한 번에 돌린다.
  ① 주소 → 좌표 지오코딩 → 등급 판정 → 보고서 본문 (report_site)
  ② 주의 구역(누적)·위험 구역을 지도에 두 겹으로 그리고 GeoJSON 저장 (zone_danger)
  ③ <고객사> CI·삼성긴고딕 4쪽 PDF 출력 (report_restyle)

usage: make_report.py --addr "부산 사상구 새벽로 87" --asof 2024-06-30 [--name 이름] [--out DIR]
       기준일은 data/zone_cache/ 에 격자 캐시가 있는 날짜만 가능하다(--list 로 확인).
"""
import os, sys, glob, argparse, subprocess, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
PY = sys.executable
CACHE = os.path.join(BASE, "data", "zone_cache")


def cached_dates():
    return sorted(os.path.basename(f)[9:-4] for f in glob.glob(os.path.join(CACHE, "dz_cache_*.npz")))


def run(cmd, tag):
    print("\n── %s" % tag, flush=True)
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.setdefault("CLAB_ROOT", os.path.join(BASE, "clab"))
    env.setdefault("OMP_NUM_THREADS", "1")
    r = subprocess.run(cmd, env=env)
    if r.returncode:
        sys.exit("실패: %s" % tag)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--addr", default="부산 사상구 새벽로 87")
    p.add_argument("--asof", default="2024-06-30")
    p.add_argument("--name", default="사상 새벽로87 신축공사")
    p.add_argument("--out", default=os.path.join(BASE, "out"))
    p.add_argument("--list", action="store_true", help="가능한 기준일 목록")
    a = p.parse_args()

    if a.list:
        print("사용 가능한 기준일:", " ".join(cached_dates()))
        return
    if a.asof not in cached_dates():
        sys.exit("기준일 %s 는 격자 캐시가 없습니다.\n  가능한 날짜: %s"
                 % (a.asof, " ".join(cached_dates())))
    os.makedirs(a.out, exist_ok=True)
    html = os.path.join(a.out, "report_%s.html" % a.asof)
    mapped = os.path.join(a.out, "report_%s_map.html" % a.asof)
    pdf = os.path.join(a.out, "보고서_%s.pdf" % a.asof)

    run([PY, os.path.join(BASE, "clab", "analysis", "sbas_sweep", "report_site.py"),
         "--addr", a.addr, "--name", a.name, "--asof", a.asof, "--out", html],
        "① 주소 → 좌표 → 등급 판정 → 보고서 본문")
    run([PY, os.path.join(HERE, "zone_danger.py"), html, a.asof, mapped],
        "② 주의·위험 구역 지도 + GeoJSON")
    run([PY, os.path.join(HERE, "report_restyle.py"), mapped, pdf],
        "③ 보고서 PDF 출력")

    gj = mapped.replace(".html", "") + "_zones.geojson"
    print("\n보고서  %s" % pdf)
    print("구역    %s" % gj)


if __name__ == "__main__":
    main()
