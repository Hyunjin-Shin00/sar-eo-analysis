"""이름 짓기 — 주소를 폴더 이름으로.

예전에는 `run.py` 안에 있었고 패키지가 그것을 거꾸로 들여왔다(`from run import slug`).
진입점이 셋이 되면서(`run.py` · `demo.py` · `hand_writting.py`) 그 방향이 성립하지 않는다 —
어느 진입점에서 들어와도 같은 이름이 나와야 하므로 **패키지 쪽에 둔다.**
"""
from __future__ import annotations

import re
import unicodedata


def slug(address):
    """주소 → 폴더 이름. 한글은 그대로 두고 공백·기호만 정리한다 — 나중에 폴더만 보고
    어느 주소인지 알아야 하므로 해시나 타임스탬프로 바꾸지 않는다."""
    s = unicodedata.normalize("NFC", address).strip()
    s = re.sub(r"[\\/:*?\"<>|]", "", s)
    s = re.sub(r"\s+", "_", s)
    return s[:80] or "unnamed"


def read_addresses(path):
    """주소 목록 파일 → 주소들. 한 줄에 하나, `#` 뒤는 주석.

    세 진입점이 같은 규칙으로 읽어야 한다 — 예전에는 `run.py` · `for_demo.py` ·
    `for_compare.py` 가 같은 네 줄을 각자 적어 두고 있었다.
    """
    from pathlib import Path
    out = []
    for ln in Path(path).read_text("utf-8").splitlines():
        ln = ln.split("#", 1)[0].strip()      # 인라인 주석 제거 — 안 지우면 주소에 붙는다
        if ln:
            out.append(ln)
    return out
