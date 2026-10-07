# sar/sentinel-1/insar/psinsar/descending

하강궤도 PS 처리 체인.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `download.sh` | ASF SLC 내려받기. wget 은 datapool -> CloudFront 리다이렉트에서 자격증명을 넘기지 못해 403 이 남. curl 로 쿠키자를 유지하면서 리다이렉트를 따라가야 함. | TXT | — |
| `get_orbits.py` | S1C 정밀궤도(POEORB) 확보. | JSON | 텍스트/로그 |
| `run_coreg.sh` | DSC topsStack run_01~08 순차 실행. 각 단계 내부만 xargs -P 로 병렬. GNU parallel 은 이 환경에 없다 — 기존 CSK run_step.sh 와 같은 xargs | — | — |
| `run_crop.sh` | DSC 병합 스택을 서울 창으로 잘라냄. ASC 와 같은 crop_s1.py 를 환경변수로 가리켜 재사용. | — | — |
| `run_mintpy.sh` | MintPy SBAS 실행 (하강궤도) | — | — |
| `run_sbas.sh` | DSC 간섭도 130쌍. ASC 와 동일한 run_sbas_s1.sh 를 S1_ROOT 만 바꿔 재사용함. | — | — |
| `setup_stack.sh` | DSC path32 topsStack 코레지 설정. -W slc 로 코레지된 SLC 스택만 만들고, 간섭도는 ASC 때 검증된 sbas_lib_s1.py 를 그대로 써서 따로 만든다(멀티룩 8rg  | — | — |
