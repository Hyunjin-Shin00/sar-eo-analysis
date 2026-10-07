"""Global in-memory application state."""
import threading
import queue
from dataclasses import dataclass, field
from typing import Optional, List

@dataclass
class Job:
    job_id: str
    status: str = "running"   # running | done | error
    progress: int = 0
    total: int = 0
    log_queue: queue.Queue = field(default_factory=queue.Queue)
    results: list = field(default_factory=list)

class AppState:
    def __init__(self):
        self.lock = threading.Lock()
        self.sheet_path: Optional[str] = None
        self.sheet_id: Optional[str] = None       # Google Sheet ID
        self.gs_header_row: int = 0               # 0-indexed pandas row where "Perform" header was found
        self.rows: List[dict] = []                # enriched row dicts
        self.tiff_dir: str = "/mnt/hdd/BB"
        self.tiff_index: dict = {}                # match_key → tiff_path
        self.jobs: dict[str, Job] = {}

state = AppState()
