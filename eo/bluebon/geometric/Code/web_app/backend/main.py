"""
BlueBON Geometric Correction — FastAPI Backend

실행:
    cd Code/web_app/backend
    uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from routers.sheet import router as sheet_router
from routers.processing import router as processing_router
from routers.preview import router as preview_router
from routers.upload_router import router as upload_router

app = FastAPI(title="BlueBON Geometric Correction API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sheet_router)
app.include_router(processing_router)
app.include_router(preview_router)
app.include_router(upload_router)


@app.post("/api/debug/inject-result")
def inject_result(tiff_path: str, result_dir: str, row: int = 1,
                  actual_lat: float = 0.0, actual_lon: float = 0.0):
    """결과 영상 탭 테스트용: 처리 완료 행을 state에 직접 주입."""
    import os
    from state import state
    entry = {
        "row": row, "capture_time": "test", "target_lat": actual_lat,
        "target_lon": actual_lon, "perform": True,
        "matched_tiff": os.path.basename(tiff_path),
        "matched_tiff_path": tiff_path,
        "actual_lat": actual_lat, "actual_lon": actual_lon,
        "status": "done", "result_dir": result_dir,
    }
    with state.lock:
        # 이미 같은 row가 있으면 업데이트, 없으면 추가
        for i, r in enumerate(state.rows):
            if r["row"] == row:
                state.rows[i] = entry
                return {"ok": True, "action": "updated"}
        state.rows.append(entry)
    return {"ok": True, "action": "inserted"}

# Production: serve React build
_frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(_frontend_dist):
    app.mount("/", StaticFiles(directory=_frontend_dist, html=True), name="static")
