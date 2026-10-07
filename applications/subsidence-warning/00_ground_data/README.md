# 00_ground_data

지반등급 산정의 입력이 되는 **시추공 자료 수집·정리** 단계임.

| 코드 | 입력 | 출력 |
|---|---|---|
| `download_spt.py` | 국토교통부 지반정보 표준관입시험정보 OpenAPI (`api.odcloud.kr`), 인증키는 환경변수 `DATA_GO_KR_KEY` | 시추공 92,307공 SPT N값 CSV (전량 페이지네이션 수집) |
| `merge_ground_csv.py` | 시추주상도 CSV 다수 (cp949, 깨진 바이트·줄바꿈 포함) | 통합 지반정보 CSV — 공번·좌표·심도별 N값 정규화 |

- 인증키는 코드에 없음. 환경변수로만 읽음
- 원자료 CSV 는 용량과 배포조건 때문에 저장소에 미포함
- 다음 단계: [`02_fusion_poc/geol_grade.py`](../02_fusion_poc/geol_grade.py) 가 N값을 연약(0.6)·주의(0.8)·양호(1.0) 3등급으로 환산함
