"""ISCE2 2.6.x 의 TOPS Sentinel1 리더에 Sentinel-1D 미션 ID 를 추가한다.

ISCE2 2.6.3 은 S1A/S1B/S1C 만 하드코딩해 S1D SAFE 를 만나면
`ValueError: Encountered unknown mission id S1D` 로 거부한다.
절대궤도 → 상대궤도 변환식 `(orbit - offset) % 175 + 1` 의 S1D offset(42)을 넣는다.

사용:  python apply_s1d_patch.py            # 활성 conda env 의 isce 패키지를 찾아 패치
       python apply_s1d_patch.py --check    # 패치 여부만 확인
원본은 같은 위치에 `.bak_pre_s1d` 로 백업한다. 이미 패치돼 있으면 아무것도 하지 않는다.
"""
import sys, shutil, pathlib, importlib.util

OFFSET = 42
ANCHOR = "            elif mission == 'S1C':\n                burst.trackNumber = (orbitnumber-172)%175 + 1\n"
ADD = ("            elif mission == 'S1D':\n"
       "                # offset 42 derived from CDSE (absolute orbit -> relative orbit)\n"
       f"                burst.trackNumber = (orbitnumber-{OFFSET})%175 + 1\n")


def target():
    spec = importlib.util.find_spec("isce")
    if spec is None or not spec.submodule_search_locations:
        sys.exit("isce 패키지를 찾을 수 없음 — ISCE2 가 설치된 env 를 활성화할 것")
    p = pathlib.Path(list(spec.submodule_search_locations)[0]) / "components/isceobj/Sensor/TOPS/Sentinel1.py"
    if not p.exists():
        sys.exit(f"파일 없음: {p}")
    return p


def main():
    p = target(); src = p.read_text()
    done = "mission == 'S1D'" in src
    if "--check" in sys.argv:
        print(f"{p}\n  S1D 지원: {'예' if done else '아니오'}"); return
    if done:
        print("이미 패치됨 — 변경 없음"); return
    if src.count(ANCHOR) != 1:
        sys.exit("S1C 분기를 정확히 1곳에서 찾지 못함 — ISCE2 버전이 다르다. sentinel1_s1d.patch 를 수동 적용할 것")
    bak = p.with_suffix(p.suffix + ".bak_pre_s1d")
    if not bak.exists():
        shutil.copy2(p, bak)
    p.write_text(src.replace(ANCHOR, ANCHOR + ADD))
    print(f"패치 완료: {p}\n백업: {bak}")


if __name__ == "__main__":
    main()
