import asyncio
import queue as queue_module

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from services.upload_service import start_upload, get_job

router = APIRouter(prefix="/api/upload", tags=["upload"])


class UploadRequest(BaseModel):
    row_indices: list[int]


@router.post("/start")
def upload_start(body: UploadRequest):
    if not body.row_indices:
        return {"error": "업로드할 행을 선택하세요"}
    job_id = start_upload(body.row_indices)
    return {"job_id": job_id}


@router.websocket("/ws/{job_id}")
async def upload_ws(websocket: WebSocket, job_id: str):
    await websocket.accept()
    loop = asyncio.get_event_loop()

    job = get_job(job_id)
    if not job:
        await websocket.send_text("__ERROR__ job not found")
        await websocket.close()
        return

    log_queue: queue_module.Queue = job["log_queue"]

    try:
        while True:
            msg = await loop.run_in_executor(None, lambda: log_queue.get(timeout=60))
            if msg == "__DONE__":
                await websocket.send_text("__DONE__")
                break
            await websocket.send_text(msg)
    except queue_module.Empty:
        await websocket.send_text("__DONE__")
    except WebSocketDisconnect:
        pass
