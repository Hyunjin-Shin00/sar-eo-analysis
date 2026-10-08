"""sitecheck — 주소 하나로 네 가지 판정을 내는 파이프라인의 코드.

바깥에는 진입점(`run.py`)과 설치 목록만 두고, 코드는 전부 여기 있다.

    settings.py   경로 · 키 · 영상 등록부 · 모델 구성 (폴더 밖을 가리키는 것은 여기만)
    rules.py      판정 기준 (A1 이격 · A3 대장 · A4·A5 야적) — 법령 조문과 임계값
    schema.py     결과 형식 (result.json · GeoJSON 네 장 · summary.md)
    draw.py       그림 규칙 (팔레트 · 선 · 라벨 · 항목별 레이어)
    steps/        단계별 처리 — s0 주소 → s1 건물 → s2 야적 → s3 이격 → s4 대장 (+ 정합)
    vendor/       외부에서 가져온 것의 사본 — API 클라이언트 · 분광 · 그림자 · 모델 코드
    tools/        사람이 직접 돌리는 것 — 점검 · 데모 · 영상 등록

호출은 어디서나 `from sitecheck import settings as config` 처럼 패키지 이름을 붙여서 한다.
예전에는 파일이 모두 저장소 뿌리에 있어 `import settings` 로 불렀는데, 그러면 같은 이름의
다른 모듈과 부딪히고 어디까지가 이 도구인지 폴더만 봐서는 알 수 없었다.
"""
