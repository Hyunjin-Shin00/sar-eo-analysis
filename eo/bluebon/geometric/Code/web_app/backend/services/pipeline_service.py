"""Run the geometric correction pipeline with real-time log capture."""
import sys, os, uuid, io, glob, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from concurrent.futures import ThreadPoolExecutor, as_completed
from batch_processing import (
    MatchedData,
    process_single_image,
    parse_tiff_metadata,
    get_band_count_from_filename,
)
from state import state, Job


class _QueueWriter(io.TextIOBase):
    """Redirects print() output into a thread-safe Queue."""
    def __init__(self, q):
        self.q = q

    def write(self, s):
        if s.strip():
            self.q.put(s.rstrip("\n"))
        return len(s)

    def flush(self):
        pass


def _build_matched(row: dict) -> MatchedData:
    tiff_path = row["matched_tiff_path"]
    meta = parse_tiff_metadata(tiff_path) or {}
    return MatchedData(
        excel_row=row["row"],
        capture_time=row["capture_time"],
        target_lat=row["target_lat"],
        target_lon=row["target_lon"],
        tiff_path=tiff_path,
        tiff_filename=os.path.basename(tiff_path),
        match_key=meta.get("date", "unknown") + "_" + meta.get("time", "unknown")[:4],
    )


def _get_result_dir(matched: MatchedData) -> str:
    meta = parse_tiff_metadata(matched.tiff_path)
    if meta:
        folder = f"bb_{meta['level']}_{meta['date']}_{meta['time']}_{meta['band_count']}band"
    else:
        folder = os.path.splitext(matched.tiff_filename)[0]
    return os.path.join(os.path.dirname(matched.tiff_path), folder)


def start_download(save_dir: str, max_workers: int = 3) -> str:
    """구글 드라이브에서 Perform=True 행 TIFF 병렬 다운로드 (rclone)."""
    job_id = uuid.uuid4().hex
    job = Job(job_id=job_id, total=0)
    with state.lock:
        state.jobs[job_id] = job
        state.tiff_dir = save_dir

    thread = threading.Thread(
        target=_run_download,
        args=(job_id, save_dir, max_workers),
        daemon=True,
    )
    thread.start()
    return job_id


def _run_download(job_id: str, save_dir: str, max_workers: int = 3):
    job = state.jobs[job_id]
    old_stdout = sys.stdout
    sys.stdout = _QueueWriter(job.log_queue)
    try:
        # 웹 UI에서 perform=True로 체크된 행만 다운로드
        with state.lock:
            capture_times = [r["capture_time"] for r in state.rows if r.get("perform")]
        print(f">>> Perform 체크된 행: {len(capture_times)}개")
        from Download_BlueBON import run_for_targets
        run_for_targets(capture_times, save_dir=save_dir, max_workers=max_workers)
        job.status = "done"
    except Exception as e:
        print(f"[ERROR] 다운로드 실패: {e}")
        import traceback; traceback.print_exc()
        job.status = "error"
    finally:
        sys.stdout = old_stdout
        job.log_queue.put(None)


def start_job(batch_count: int = 1) -> str:
    """Create a job and run processing in a background thread."""
    rows_to_process = [
        r for r in state.rows
        if r.get("perform") and r.get("matched_tiff_path")
    ]
    if not rows_to_process:
        raise ValueError("처리할 매칭된 행이 없습니다 (Perform=true + TIFF 매칭 필요)")

    job_id = uuid.uuid4().hex
    job = Job(job_id=job_id, total=len(rows_to_process))
    with state.lock:
        state.jobs[job_id] = job

    thread = threading.Thread(
        target=_run_job,
        args=(job_id, rows_to_process, batch_count),
        daemon=True,
    )
    thread.start()
    return job_id


def _run_job(job_id: str, rows: list, batch_count: int):
    job = state.jobs[job_id]
    output_dir = state.tiff_dir

    old_stdout = sys.stdout
    sys.stdout = _QueueWriter(job.log_queue)

    try:
        matched_list = [_build_matched(r) for r in rows]

        # Mark all as processing
        with state.lock:
            for r in rows:
                r["status"] = "processing"

        with ThreadPoolExecutor(max_workers=batch_count) as executor:
            futures = {executor.submit(process_single_image, m, output_dir): m
                       for m in matched_list}
            for future in as_completed(futures):
                matched = futures[future]
                try:
                    excel_row, coords = future.result()
                    with state.lock:
                        for r in state.rows:
                            if r["row"] == excel_row:
                                if coords:
                                    r["actual_lat"], r["actual_lon"] = coords
                                    r["result_dir"] = _get_result_dir(matched)
                                    r["status"] = "done"
                                else:
                                    r["status"] = "error"
                                break
                except Exception as e:
                    print(f"[ERROR] {matched.tiff_filename}: {e}")
                    with state.lock:
                        for r in state.rows:
                            if r["row"] == matched.excel_row:
                                r["status"] = "error"
                                break

                job.progress += 1
                print(f"[{job.progress}/{job.total}] 완료: {matched.tiff_filename}")

        job.status = "done"

        # 처리 완료 후 Google Sheet에 actual lat/lon 자동 업데이트
        if state.sheet_id:
            try:
                from services.sheet_service import update_google_sheet_results
                gs = update_google_sheet_results()
                print(f"[Google Sheets] {gs['updated']}개 행 자동 업데이트 완료")
            except Exception as gs_err:
                print(f"[Google Sheets] 업데이트 실패 (무시): {gs_err}")

    except Exception as e:
        print(f"[FATAL] {e}")
        import traceback; traceback.print_exc()
        job.status = "error"
    finally:
        sys.stdout = old_stdout
        job.log_queue.put(None)  # sentinel
