# eo/bluebon/geometric/Code/web_app/backend/routers

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `__init__.py` | API 라우터 패키지 초기화 | — | — |
| `preview.py` | 처리 결과 미리보기 API | GeoTIFF · 파일 묶음 | — |
| `processing.py` | 처리 작업 실행·상태 조회 API | — | — |
| `sheet.py` | 작업 목록 시트 연동 API | — | — |
| `upload_router.py` | 파일 업로드 API | — | — |

---

## 실행

> 새 영상·새 자료가 들어왔을 때 이 모듈만으로 결과까지 가는 순서임.
> 아래 인자와 상수는 코드에서 그대로 뽑은 것임.

### 환경

```bash
conda activate pyps      # geopandas · rasterio
```

- 환경 정의: [`environment/`](../../../../../../../environment/)

### 환경변수

| 이름 | 설명 |
|---|---|
| `BLUEBON_SHEET_ID` | 미션 시트 ID |
