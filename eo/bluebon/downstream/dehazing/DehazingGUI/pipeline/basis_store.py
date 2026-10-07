"""사용자가 폴리라인으로 저장한 basis를 JSON으로 관리.

저장 위치: exe (또는 main.py) 와 같은 폴더의 user_bases.json.
스키마:
  {"version": 1,
   "bases": [
     {"id": "user:<uuid>", "name": "...", "sensor": "msi_20m",
      "nbands": 10, "array": [[...]], "created_at": "...", "updated_at": "..."}
   ]}
"""
import json
import os
import sys
import uuid
from datetime import datetime
import numpy as np


def default_store_path() -> str:
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..')
        )
    return os.path.join(base, 'user_bases.json')


class BasisStoreError(Exception):
    pass


class BasisStore:
    def __init__(self, path: str | None = None):
        self.path = path or default_store_path()
        self._data = self._load()

    def _load(self) -> dict:
        if not os.path.isfile(self.path):
            return {'version': 1, 'bases': []}
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                d = json.load(f)
            if not isinstance(d, dict) or not isinstance(d.get('bases'), list):
                return {'version': 1, 'bases': []}
            return d
        except Exception:
            return {'version': 1, 'bases': []}

    def _save(self) -> None:
        d = os.path.dirname(self.path) or '.'
        try:
            os.makedirs(d, exist_ok=True)
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except OSError as e:
            raise BasisStoreError(
                f'사용자 basis 파일 저장 실패: {self.path}\n  {e}'
            )

    def list(self, sensor: str | None = None) -> list:
        items = list(self._data.get('bases', []))
        if sensor is not None:
            items = [b for b in items if b.get('sensor') == sensor]
        items.sort(key=lambda b: b.get('created_at', ''))
        return items

    def add(self, name: str, sensor: str, array: np.ndarray,
            u_h: np.ndarray | None = None,
            u_l: np.ndarray | None = None,
            u_norm: np.ndarray | None = None) -> str:
        if array.ndim != 2:
            raise ValueError(f'array shape (K, nbands) 기대, 실제: {array.shape}')
        bid = f'user:{uuid.uuid4()}'
        now = datetime.now().isoformat(timespec='seconds')
        entry = {
            'id': bid,
            'name': name,
            'sensor': sensor,
            'nbands': int(array.shape[1]),
            'array': array.astype(np.float32).tolist(),
            'u_h':    u_h.astype(np.float32).tolist()    if u_h    is not None else None,
            'u_l':    u_l.astype(np.float32).tolist()    if u_l    is not None else None,
            'u_norm': u_norm.astype(np.float32).tolist() if u_norm is not None else None,
            'created_at': now,
            'updated_at': now,
        }
        self._data.setdefault('bases', []).append(entry)
        self._save()
        return bid

    def rename(self, bid: str, new_name: str) -> bool:
        for b in self._data.get('bases', []):
            if b.get('id') == bid:
                b['name'] = new_name
                b['updated_at'] = datetime.now().isoformat(timespec='seconds')
                self._save()
                return True
        return False

    def delete(self, bid: str) -> bool:
        items = self._data.get('bases', [])
        kept = [b for b in items if b.get('id') != bid]
        if len(kept) == len(items):
            return False
        self._data['bases'] = kept
        self._save()
        return True

    def get(self, bid: str) -> dict | None:
        for b in self._data.get('bases', []):
            if b.get('id') == bid:
                return b
        return None

    def get_array(self, bid: str) -> np.ndarray | None:
        b = self.get(bid)
        if b is None:
            return None
        return np.array(b['array'], dtype=np.float32)

    def get_u(self, bid: str) -> np.ndarray | None:
        """저장된 정규화 aerosol spectrum u_norm. 없으면 None (legacy entry)."""
        b = self.get(bid)
        if b is None:
            return None
        u = b.get('u_norm')
        if u is None:
            return None
        return np.array(u, dtype=np.float32)
