import asyncio
import json
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from services.pipeline_service import start_job, start_download
from state import state

router = APIRouter(tags=["processing"])


class StartRequest(BaseModel):
    batch_count: int = 1


class DownloadRequest(BaseModel):
    save_dir: str = "/mnt/hdd/BB"
    max_workers: int = 3


@router.post("/api/download/start")
def download_start(req: DownloadRequest):
    try:
        job_id = start_download(req.save_dir, req.max_workers)
        return {"job_id": job_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/process/start")
def process_start(req: StartRequest):
    try:
        job_id = start_job(req.batch_count)
        return {"job_id": job_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/process/{job_id}")
def process_status(job_id: str):
    job = state.jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job_id,
        "status": job.status,
        "progress": job.progress,
        "total": job.total,
    }


@router.websocket("/ws/{job_id}")
async def ws_logs(websocket: WebSocket, job_id: str):
    await websocket.accept()
    job = state.jobs.get(job_id)
    if not job:
        await websocket.send_text(json.dumps({"type": "error", "message": "Job not found"}))
        await websocket.close()
        return

    loop = asyncio.get_event_loop()
    try:
        while True:
            # Read from thread-safe queue without blocking the event loop
            msg = await loop.run_in_executor(None, job.log_queue.get)
            if msg is None:  # sentinel → job finished
                await websocket.send_text(json.dumps({
                    "type": "done",
                    "status": job.status,
                    "progress": job.progress,
                    "total": job.total,
                }))
                break
            await websocket.send_text(json.dumps({"type": "log", "message": msg}))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
        except Exception:
            pass
