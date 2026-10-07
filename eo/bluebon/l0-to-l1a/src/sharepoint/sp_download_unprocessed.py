import os
#!/usr/bin/env python3
"""
sp_download_unprocessed.py — SharePoint 00_LEOPS/01_downlinked 에서 아직 처리하지 않은 영상만 받아
/mnt/e/bkchoi/prep/data/YYYYMMDD_<target>.zip 으로 저장한다 (loop.sh 입력 형식).

"처리 안 한 영상" 기준:
  BlueBON Mission 시트(Mission 탭)에서 AD열(FEE/CEM Temp)이 비어 있는 행
  → E열(Capture Start Time)과 SharePoint 폴더명(YYMMDD_HHMMSS)을 ±MAX_DELTA 초로 매칭
  → 매칭된 폴더 중 로컬에 zip/디렉터리가 없는 것만 다운로드

Usage:
  sp_download_unprocessed.py --list            # SharePoint 폴더 목록만
  sp_download_unprocessed.py --dry-run         # 매칭/다운로드 계획만
  sp_download_unprocessed.py                   # 실제 다운로드 + zip
  sp_download_unprocessed.py --limit 3         # 처음 N개만
  sp_download_unprocessed.py --since 2026-08-01  # 이 날짜 이후 촬영만
"""
import argparse, json, os, re, shutil, subprocess, sys, zipfile
from datetime import datetime
from pathlib import Path

RCLONE     = os.path.expanduser("~/.local/bin/rclone2")
SP_ROOT    = "satrev:TelePIX/00_LEOPS/01_downlinked"
DATA_DIR   = Path("/mnt/e/bkchoi/prep/data")
TMP_DIR    = DATA_DIR / "tmp" / "sp_dl"
CREDS      = Path("/mnt/e/bkchoi/prep/data/fee_cee_temp/ee-hyunjin-f97764a9f222.json")
SHEET_ID   = os.environ.get("BLUEBON_SHEET_ID", "")
MAX_DELTA  = 20   # seconds (process_empty_rows.py 와 동일)

_DT_RE  = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")
_CAP_RE = re.compile(r"(\d{2})(\d{2})(\d{2})[_-](\d{2})(\d{2})(\d{2})")


def sheet_candidates():
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_file(str(CREDS), scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    ws = gspread.authorize(creds).open_by_key(SHEET_ID).worksheet("Mission")
    out = []
    for i, r in enumerate(ws.get_all_values(), start=1):
        r += [""] * (31 - len(r))
        m = _DT_RE.match(r[4].strip())
        if not m or r[29].strip():
            continue
        out.append(dict(row=i, id=r[0].strip(), target=r[2].strip(),
                        dt=datetime.fromisoformat(m.group(1)), image=r[19].strip()))
    return out


def sp_entries():
    """01_downlinked 바로 아래 항목 (폴더/파일) → [(name, is_dir, capture_dt|None)]"""
    r = subprocess.run([RCLONE, "lsf", "--format", "pt", "--separator", "|", SP_ROOT + "/"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"rclone lsf failed:\n{r.stderr}")
    out = []
    for line in r.stdout.splitlines():
        name = line.split("|", 1)[0]
        is_dir = name.endswith("/")
        name = name.rstrip("/")
        m = _CAP_RE.search(name)
        dt = None
        if m:
            yy, mo, dd, hh, mi, ss = map(int, m.groups())
            try:
                dt = datetime(2000 + yy, mo, dd, hh, mi, ss)
            except ValueError:
                pass
        out.append((name, is_dir, dt))
    return out


def sanitize(target):
    return re.sub(r"[^A-Za-z0-9]+", "_", target).strip("_") or "unknown"


def local_exists(zip_stem, cap_dt):
    """이미 받아둔 흔적: 같은 이름 zip/tar.xz/디렉터리, 또는 capture 시각이 같은 zip/디렉터리"""
    for p in (DATA_DIR / f"{zip_stem}.zip", DATA_DIR / f"{zip_stem}.tar.xz", DATA_DIR / zip_stem):
        if p.exists():
            return str(p)
    tag = cap_dt.strftime("%y%m%d_%H%M%S")
    for p in DATA_DIR.iterdir():
        if tag in p.name:
            return str(p)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--since", type=str, default="")
    a = ap.parse_args()

    entries = sp_entries()
    if a.list:
        for name, is_dir, dt in entries:
            print(("D " if is_dir else "F "), name, dt.isoformat() if dt else "-")
        print(f"{len(entries)} entries")
        return

    cands = sheet_candidates()
    if a.since:
        since = datetime.fromisoformat(a.since)
        cands = [c for c in cands if c["dt"] >= since]
    print(f"sheet: {len(cands)} rows with empty AD")
    print(f"sharepoint: {len(entries)} entries ({sum(1 for e in entries if e[2])} with capture time)")

    # greedy 1:1 matching by smallest Δ (same as process_empty_rows.py)
    pairs = []
    for c in cands:
        for name, is_dir, dt in entries:
            if dt is None or dt.date() != c["dt"].date():
                continue
            d = abs((dt - c["dt"]).total_seconds())
            if d <= MAX_DELTA:
                pairs.append((d, c, name, is_dir, dt))
    pairs.sort(key=lambda p: p[0])
    used_r, used_e, plan = set(), set(), []
    for d, c, name, is_dir, dt in pairs:
        if c["row"] in used_r or name in used_e:
            continue
        used_r.add(c["row"]); used_e.add(name)
        plan.append((c, name, is_dir, dt, d))
    plan.sort(key=lambda p: p[3])

    unmatched_sp = [(n, dt) for n, _, dt in entries if dt and n not in used_e]
    print(f"\nmatched: {len(plan)}   sheet-only(empty AD, no SP folder): {len(cands)-len(plan)}   SP-only(not in empty-AD rows): {len(unmatched_sp)}")

    todo = []
    for c, name, is_dir, dt, d in plan:
        stem = f"{c['dt'].strftime('%Y%m%d')}_{sanitize(c['target'])}"
        ex = local_exists(stem, dt)
        state = f"SKIP (exists: {ex})" if ex else "DOWNLOAD"
        print(f"  row {c['row']:>4} id {c['id']:>4} {c['dt']}  <-  {name:<28} Δ={int(d):>2}s  -> {stem}.zip  [{state}]")
        if not ex:
            todo.append((c, name, is_dir, stem))

    print(f"\nto download: {len(todo)}")
    if a.dry_run:
        return
    if a.limit:
        todo = todo[: a.limit]

    TMP_DIR.mkdir(parents=True, exist_ok=True)
    done, failed = [], []
    for c, name, is_dir, stem in todo:
        src = f"{SP_ROOT}/{name}"
        dst = TMP_DIR / name
        if dst.exists():
            shutil.rmtree(dst)
        print(f"\n### {name} -> {stem}.zip")
        cmd = [RCLONE, "copy" if is_dir else "copyto", "--transfers", "8", "--checkers", "8",
               "--retries", "5", "--low-level-retries", "20", "--stats", "30s", "--stats-one-line", "-v",
               src, str(dst if is_dir else dst / name)]
        if subprocess.run(cmd).returncode != 0:
            print("  !! rclone copy failed"); failed.append(name); continue
        files = [p for p in dst.rglob("*") if p.is_file()]
        if not files:
            print("  !! nothing downloaded"); failed.append(name); continue
        zpath = DATA_DIR / f"{stem}.zip"
        tmpz  = DATA_DIR / f"{stem}.zip.part"
        # 최상위 디렉터리 1개(name/) 아래에 파일을 넣는다 → run_band.sh 의 bsdtar --strip-components=1 과 호환
        with zipfile.ZipFile(tmpz, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
            for p in sorted(files):
                z.write(p, arcname=str(Path(name) / p.relative_to(dst)))
        tmpz.rename(zpath)
        shutil.rmtree(dst, ignore_errors=True)
        size = zpath.stat().st_size / 2**20
        print(f"  OK {zpath.name}  {len(files)} files  {size:.1f} MB")
        done.append(zpath.name)

    print(f"\nDONE: {len(done)} zip(s) written to {DATA_DIR}")
    for n in done: print("  ", n)
    if failed:
        print(f"FAILED: {failed}")


if __name__ == "__main__":
    main()
