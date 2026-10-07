"""
Google Drive 업로드 서비스.
Upload_Success.py의 로직을 WebSocket 로그 스트리밍에 맞게 적용.
"""
import io
import re
import queue
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from state import state

CREDENTIALS_PATH = Path("/mnt/hdd/BlueBON_GC/credentials.json")
TOKEN_PATH       = Path("/mnt/hdd/BlueBON_GC/token.json")
SCOPES           = ["https://www.googleapis.com/auth/drive"]

# job_id → {"status": ..., "log_queue": Queue, "thread": Thread}
_jobs: dict = {}
_jobs_lock = threading.Lock()


# ── Logger (queue 기반) ────────────────────────────────────────────────────────

class _QueueLogger:
    def __init__(self, q: queue.Queue):
        self._q = q
        self.counts = {"ok": 0, "overwrite": 0, "skip_nofile": 0, "skip_parse": 0, "error": 0}

    def _put(self, line: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._q.put(f"[{ts}] {line}")

    def header(self, total: int):
        self._put("=" * 50)
        self._put(f"업로드 시작  |  총 씬: {total}개")
        self._put("=" * 50)

    def scene(self, idx: int, total: int, name: str):
        self._put("")
        self._put(f"[{idx}/{total}] {name}")

    def ok(self, filename: str):
        self.counts["ok"] += 1
        self._put(f"  [OK]          {filename}")

    def overwrite(self, filename: str):
        self.counts["overwrite"] += 1
        self._put(f"  [OVERWRITE]   {filename}")

    def skip_nofile(self, filepath: Path):
        self.counts["skip_nofile"] += 1
        self._put(f"  [SKIP-NOFILE] {filepath.name}")

    def skip_parse(self, name: str):
        self.counts["skip_parse"] += 1
        self._put(f"  [SKIP-PARSE]  {name}  ← 폴더명 파싱 실패")

    def error(self, filename: str, exc: Exception):
        self.counts["error"] += 1
        self._put(f"  [ERROR]       {filename}  ← {exc}")

    def error_folder(self, name: str, exc: Exception):
        self.counts["error"] += 1
        self._put(f"  [ERROR-FOLDER] {name}  ← {exc}")

    def footer(self, start: datetime):
        elapsed = datetime.now() - start
        s = int(elapsed.total_seconds())
        h, m, sec = s // 3600, (s % 3600) // 60, s % 60
        self._put("")
        self._put("=" * 50)
        self._put(f"완료  |  소요: {h}시간 {m}분 {sec}초")
        self._put(f"  업로드 성공    : {self.counts['ok']}개")
        self._put(f"  덮어쓰기(재업로드): {self.counts['overwrite']}개")
        self._put(f"  파일 없음(스킵): {self.counts['skip_nofile']}개")
        self._put(f"  파싱 실패(스킵): {self.counts['skip_parse']}개")
        self._put(f"  오류           : {self.counts['error']}개")
        self._put("=" * 50)
        self._q.put("__DONE__")


# ── Google Drive helpers ───────────────────────────────────────────────────────

def _get_drive_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google.auth.exceptions import TransportError
    from googleapiclient.discovery import build

    creds: Optional[Credentials] = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with TOKEN_PATH.open("w") as f:
                f.write(creds.to_json())
        else:
            raise RuntimeError(
                "Google Drive 인증이 필요합니다. "
                "서버에서 먼저 Upload_Success.py를 직접 실행해 token.json을 생성하세요."
            )

    return build("drive", "v3", credentials=creds)


def _find_leop_folder(service) -> str:
    response = service.files().list(
        q="mimeType='application/vnd.google-apps.folder' and name='LEOP' and trashed=false",
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
        fields="files(id, name)",
    ).execute()
    files = response.get("files", [])
    if not files:
        raise ValueError("LEOP 폴더를 찾을 수 없습니다.")
    return files[0]["id"]


def _get_or_create_folder(service, name: str, parent_id: str, log: _QueueLogger) -> Optional[str]:
    query = (
        f"mimeType='application/vnd.google-apps.folder' "
        f"and name='{name}' and '{parent_id}' in parents and trashed=false"
    )
    try:
        res = service.files().list(
            q=query,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            fields="files(id)",
        ).execute()
        files = res.get("files", [])
        if files:
            return files[0]["id"]
        folder = service.files().create(
            body={"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]},
            fields="id",
            supportsAllDrives=True,
        ).execute()
        return folder["id"]
    except Exception as exc:
        log.error_folder(name, exc)
        return None


def _find_existing_file(service, name: str, parent_id: str) -> Optional[str]:
    res = service.files().list(
        q=f"name='{name}' and '{parent_id}' in parents and trashed=false",
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
        fields="files(id)",
    ).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def _upload_file(service, local_path: Path, parent_id: str, log: _QueueLogger) -> None:
    from googleapiclient.http import MediaFileUpload

    if not local_path.exists():
        log.skip_nofile(local_path)
        return

    name = local_path.name
    existing_id = _find_existing_file(service, name, parent_id)
    suffix = local_path.suffix.lower()
    mime = "image/tiff" if suffix in {".tif", ".tiff"} else "text/plain"
    media = MediaFileUpload(str(local_path), mimetype=mime, resumable=True)

    try:
        if existing_id:
            service.files().update(
                fileId=existing_id, media_body=media, supportsAllDrives=True,
            ).execute()
            log.overwrite(name)
        else:
            service.files().create(
                body={"name": name, "parents": [parent_id]},
                media_body=media,
                fields="id",
                supportsAllDrives=True,
            ).execute()
            log.ok(name)
    except Exception as exc:
        log.error(name, exc)


def _upload_scene(service, scene_dir: Path, leop_id: str, log: _QueueLogger) -> None:
    m = re.match(r"bb_l1a_(\d{8}_\d{6})_(\w+)", scene_dir.name)
    if not m:
        log.skip_parse(scene_dir.name)
        return

    date_str, band_str = m.group(1), m.group(2)
    l1c_prefix  = f"bb_l1c_{date_str}_{band_str}"
    folder_date = date_str[2:]  # YYYYMMDD_HHMMSS → YYMMDD_HHMMSS

    date_id   = _get_or_create_folder(service, folder_date, leop_id, log)
    if not date_id:
        return
    l1c_id    = _get_or_create_folder(service, "level-1C", date_id, log)
    if not l1c_id:
        return
    bottom_id = _get_or_create_folder(service, "bottom", l1c_id, log)
    center_id = _get_or_create_folder(service, "center", l1c_id, log)
    top_id    = _get_or_create_folder(service, "top",    l1c_id, log)

    # 전체 합성 TIFF → level-1C/
    _upload_file(service, scene_dir / f"{l1c_prefix}.tiff", l1c_id, log)

    # 각 파트 TIFF + RPB
    for part, folder_id in [("Bottom", bottom_id), ("Center", center_id), ("Top", top_id)]:
        if not folder_id:
            continue
        final_dir = scene_dir / part / "07_Final_results"
        _upload_file(service, final_dir / f"{l1c_prefix}_{part.lower()}.tiff", folder_id, log)
        _upload_file(service, final_dir / f"{l1c_prefix}_{part.lower()}.RPB",  folder_id, log)


# ── Public API ─────────────────────────────────────────────────────────────────

def start_upload(row_indices: list[int]) -> str:
    """선택된 row_indices의 result_dir을 Google Drive에 업로드. job_id 반환."""
    job_id = str(uuid.uuid4())[:8]
    log_queue: queue.Queue = queue.Queue()

    with _jobs_lock:
        _jobs[job_id] = {"status": "running", "log_queue": log_queue}

    t = threading.Thread(target=_run_upload, args=(job_id, row_indices, log_queue), daemon=True)
    t.start()
    with _jobs_lock:
        _jobs[job_id]["thread"] = t

    return job_id


def _run_upload(job_id: str, row_indices: list[int], log_queue: queue.Queue):
    log = _QueueLogger(log_queue)
    start = datetime.now()

    try:
        # 대상 씬 수집
        with state.lock:
            target_rows = [
                r for r in state.rows
                if r["row"] in row_indices and r.get("result_dir")
            ]

        if not target_rows:
            log_queue.put("[ERROR] 업로드할 결과 없음 (result_dir 없는 행)")
            log_queue.put("__DONE__")
            with _jobs_lock:
                _jobs[job_id]["status"] = "error"
            return

        log.header(len(target_rows))
        service = _get_drive_service()
        leop_id = _find_leop_folder(service)

        for i, row in enumerate(target_rows, 1):
            scene_dir = Path(row["result_dir"])
            log.scene(i, len(target_rows), scene_dir.name)
            _upload_scene(service, scene_dir, leop_id, log)

        log.footer(start)
        with _jobs_lock:
            _jobs[job_id]["status"] = "done"

    except Exception as exc:
        log_queue.put(f"[FATAL] {exc}")
        log_queue.put("__DONE__")
        with _jobs_lock:
            _jobs[job_id]["status"] = "error"


def get_job(job_id: str) -> Optional[dict]:
    with _jobs_lock:
        return _jobs.get(job_id)
