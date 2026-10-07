import os
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
import tempfile, shutil, os

from services.sheet_service import load_sheet, load_from_google_sheets, scan_and_match, update_row, save_sheet
from state import state

router = APIRouter(prefix="/api/sheet", tags=["sheet"])

DEFAULT_SHEET_ID = os.environ.get("BLUEBON_SHEET_ID", "")


class GoogleSheetRequest(BaseModel):
    sheet_id: str = DEFAULT_SHEET_ID


@router.post("/from-google")
def from_google(req: GoogleSheetRequest):
    try:
        rows = load_from_google_sheets(req.sheet_id)
        return {"rows": rows, "sheet_id": req.sheet_id, "count": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload")
async def upload_sheet(file: UploadFile = File(...)):
    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    try:
        rows = load_sheet(tmp_path)
        # Keep temp file as the working copy
        state.sheet_path = tmp_path
        return {"rows": rows, "sheet_path": file.filename, "count": len(rows)}
    except Exception as e:
        os.unlink(tmp_path)
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/data")
def get_data():
    return {
        "rows": state.rows,
        "sheet_path": state.sheet_path,
        "tiff_dir": state.tiff_dir,
    }


class ScanRequest(BaseModel):
    tiff_dir: str
    tolerance_sec: int = 600


@router.post("/scan")
def scan(req: ScanRequest):
    if not state.rows:
        raise HTTPException(status_code=400, detail="먼저 시트를 업로드하세요")
    try:
        result = scan_and_match(req.tiff_dir, req.tolerance_sec)
        return {**result, "rows": state.rows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class RowUpdate(BaseModel):
    target_lat: Optional[float] = None
    target_lon: Optional[float] = None
    perform: Optional[bool] = None


@router.patch("/row/{row_idx}")
def patch_row(row_idx: int, body: RowUpdate):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        updated = update_row(row_idx, updates)
        return {"row": updated}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/save")
def save():
    if not state.sheet_path and not state.sheet_id:
        raise HTTPException(status_code=400, detail="로드된 시트 없음")
    try:
        result = save_sheet()
        gs = result.get("gs_result")
        msg = "로컬 저장 완료"
        if gs:
            msg += f" + Google Sheets {gs['updated']}개 행 업데이트"
        return {"ok": True, "message": msg, "gs_result": gs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
