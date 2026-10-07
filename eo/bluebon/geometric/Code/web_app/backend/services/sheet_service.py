"""Sheet loading, TIFF scanning, row editing."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..'))

from batch_processing import (
    load_sheet_data,
    scan_tiff_files,
    match_excel_tiff,
    parse_tiff_metadata,
    get_band_count_from_filename,
)
from state import state


def _enrich(raw: dict) -> dict:
    """Add web-app fields to a raw row dict."""
    return {
        **raw,
        "perform": raw.get("perform", True),
        "matched_tiff": None,
        "matched_tiff_path": None,
        "actual_lat": None,
        "actual_lon": None,
        "status": None,
        "result_dir": None,
    }


def load_from_google_sheets(sheet_id: str) -> list:
    """구글 시트에서 직접 CSV를 받아 파싱 후 state에 저장."""
    import io, tempfile, pandas as pd
    from Download_BlueBON import _http_get_with_retry

    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=0"
    response = _http_get_with_retry(url, timeout_sec=60)

    # "Perform" 컬럼이 있는 헤더 행 찾기
    temp_df = pd.read_csv(io.StringIO(response.text), header=None)
    header_row = next(
        (i for i, row in temp_df.iterrows() if "Perform" in row.values),
        -1,
    )
    if header_row == -1:
        raise ValueError("시트에서 'Perform' 컬럼을 찾을 수 없습니다")

    df = pd.read_csv(io.StringIO(response.text), skiprows=header_row)
    df.columns = df.columns.str.strip()

    # 임시 CSV로 저장 후 기존 load_sheet_data 재사용
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8") as f:
        df.to_csv(f, index=False)
        tmp_path = f.name

    rows = load_sheet(tmp_path)

    # Google Sheets 업데이트를 위해 sheet_id와 헤더 위치 저장
    with state.lock:
        state.sheet_id = sheet_id
        state.gs_header_row = header_row

    return rows


def load_sheet(path: str) -> list:
    """Load all rows from Excel/CSV; store in state."""
    raw_rows = load_sheet_data(path, only_perform_o=False)
    rows = [_enrich(r) for r in raw_rows]
    with state.lock:
        state.sheet_path = path
        state.rows = rows
    return rows


def scan_and_match(tiff_dir: str, tolerance_sec: int = 600) -> dict:
    """Scan TIFF dir, match with current rows, update state."""
    tiff_index = scan_tiff_files(tiff_dir)

    # Build raw dicts for match_excel_tiff
    raw_rows = [
        {"row": r["row"], "capture_time": r["capture_time"],
         "target_lat": r["target_lat"], "target_lon": r["target_lon"]}
        for r in state.rows
    ]
    matched = match_excel_tiff(raw_rows, tiff_index, tolerance_sec=tolerance_sec)

    matched_by_row = {m.excel_row: m for m in matched}

    with state.lock:
        state.tiff_dir = tiff_dir
        state.tiff_index = tiff_index
        for row in state.rows:
            m = matched_by_row.get(row["row"])
            if m:
                row["matched_tiff"] = m.tiff_filename
                row["matched_tiff_path"] = m.tiff_path
                row["status"] = "pending"
            else:
                row["matched_tiff"] = None
                row["matched_tiff_path"] = None
                row["status"] = None

    return {
        "total_tiff": len(tiff_index),
        "matched": len(matched),
        "unmatched": len(state.rows) - len(matched),
    }


def update_row(row_idx: int, updates: dict) -> dict:
    """Patch a row's editable fields in state."""
    editable = {"target_lat", "target_lon", "perform"}
    with state.lock:
        for row in state.rows:
            if row["row"] == row_idx:
                for k, v in updates.items():
                    if k in editable:
                        row[k] = v
                return row
    raise KeyError(f"row_idx {row_idx} not found")


def _col_to_letter(col_1idx: int) -> str:
    """1-indexed 열 번호 → A1 문자 (A, B, ..., Z, AA, ...)"""
    result = ""
    while col_1idx > 0:
        col_1idx, rem = divmod(col_1idx - 1, 26)
        result = chr(65 + rem) + result
    return result


def update_google_sheet_results() -> dict:
    """
    처리 완료 행의 actual_lat/lon을 Google Sheet에 직접 업데이트.
    state.sheet_id와 state.gs_header_row가 설정되어 있어야 함.
    반환: {"updated": int, "sheet_id": str}
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from pathlib import Path

    TOKEN_PATH = Path("/mnt/hdd/BlueBON_GC/token.json")
    SCOPES = ["https://www.googleapis.com/auth/drive",
              "https://www.googleapis.com/auth/spreadsheets"]

    sheet_id = state.sheet_id
    if not sheet_id:
        raise ValueError("Google Sheet ID가 없습니다. 먼저 구글 시트를 불러오세요.")

    gs_header_row = state.gs_header_row  # 0-indexed pandas row = GSheets row (gs_header_row+1)
    gs_header_row_1idx = gs_header_row + 1  # GSheets 1-indexed

    # 인증
    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with TOKEN_PATH.open("w") as f:
                f.write(creds.to_json())
        else:
            raise RuntimeError(
                "Google 인증이 필요합니다. Upload_Success.py를 먼저 실행해 token.json을 생성하세요."
            )

    service = build("sheets", "v4", credentials=creds)
    ss = service.spreadsheets()

    # 헤더 행 읽기 (전체 열)
    header_resp = ss.values().get(
        spreadsheetId=sheet_id,
        range=f"A{gs_header_row_1idx}:ZZ{gs_header_row_1idx}",
    ).execute()
    header = header_resp.get("values", [[]])[0]

    # Actual Latitude / Longitude 열 찾기
    lat_col = lon_col = None
    for i, h in enumerate(header, start=1):
        n = str(h or "").strip().lower().replace("\n", " ")
        if "actual" in n and "lat" in n:
            lat_col = i
        if "actual" in n and "lon" in n:
            lon_col = i

    # 없으면 헤더 끝에 추가
    update_header = []
    if lat_col is None:
        lat_col = len(header) + 1
        update_header.append({
            "range": f"{_col_to_letter(lat_col)}{gs_header_row_1idx}",
            "values": [["Actual Latitude"]],
        })
    if lon_col is None:
        lon_col = max(lat_col, len(header)) + 1
        update_header.append({
            "range": f"{_col_to_letter(lon_col)}{gs_header_row_1idx}",
            "values": [["Actual Longitude"]],
        })
    if update_header:
        ss.values().batchUpdate(
            spreadsheetId=sheet_id,
            body={"valueInputOption": "RAW", "data": update_header},
        ).execute()

    lat_letter = _col_to_letter(lat_col)
    lon_letter = _col_to_letter(lon_col)

    # 완료 행들을 배치로 업데이트
    # state row r["row"] (temp CSV 2-based) → GSheets row = r["row"] + gs_header_row
    data = []
    updated = 0
    with state.lock:
        for r in state.rows:
            if r.get("actual_lat") is not None and r.get("actual_lon") is not None:
                gs_row = r["row"] + gs_header_row  # GSheets 1-indexed data row
                data.append({
                    "range": f"{lat_letter}{gs_row}:{lon_letter}{gs_row}",
                    "values": [[r["actual_lat"], r["actual_lon"]]],
                })
                updated += 1

    if data:
        ss.values().batchUpdate(
            spreadsheetId=sheet_id,
            body={"valueInputOption": "RAW", "data": data},
        ).execute()

    print(f"[Google Sheets] {updated}개 행 업데이트 완료 (sheet_id={sheet_id})")
    return {"updated": updated, "sheet_id": sheet_id}


def save_sheet() -> dict:
    """로컬 파일 저장 + Google Sheet 업데이트 (가능한 경우)."""
    path = state.sheet_path
    results = [(r["row"], (r["actual_lat"], r["actual_lon"]) if r["actual_lat"] else None)
               for r in state.rows]

    # 로컬 파일 저장
    local_saved = False
    if path:
        ext = os.path.splitext(path)[1].lower()
        if ext == ".csv":
            from batch_processing import update_csv_with_results
            update_csv_with_results(path, results)
        else:
            from batch_processing import update_excel_with_results
            update_excel_with_results(path, results)
        local_saved = True

    # Google Sheet 업데이트 (sheet_id가 있을 때만)
    gs_result = None
    if state.sheet_id:
        gs_result = update_google_sheet_results()

    return {"local_saved": local_saved, "gs_result": gs_result}
