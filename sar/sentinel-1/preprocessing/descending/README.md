# sar/sentinel-1/preprocessing/descending

하강궤도 전용 수집·코레지. 상승궤도와 설정이 달라 분리했다.

## 코드

| 파일 | 역할 | 입력 | 출력 |
|---|---|---|---|
| `download.py` | 지반침하 분석 - 하강궤도(DSC) Sentinel-1 SLC 일괄 다운로드. | JSON | JSON · 텍스트/로그 |
| `download_orbits.py` | DSC 264장에 대응하는 S1B 정밀궤도(POEORB) 확보. usage: download_orbits_dsc.py [--dry] | JSON · 파일 묶음 | 텍스트/로그 |
| `env_isce2.sh` | DSC 코레지용 ISCE2 topsStack 환경. 기존 env_seoul.sh 가 참조하던 ${PSI_ENV:-<PSI_PACKAGE_ROOT>/env.sh} 는 비어 있어(통합 재구성 이후) | — | — |
| `run_coreg.sh` | SETUP 완료 후 남은 run_files(run_02~run_13) 병렬 코레지. usage: run_coreg_dsc.sh <t061/t134> [NP] DSC_incheon/run_coreg_ | TXT | — |
| `setup_coreg.sh` | DSC 코레지 SETUP + run_01 topo 조기검증.  usage: setup_coreg_dsc.sh <t061/t134> DSC_incheon/setup_coreg.sh 절차를 그대로 따름 | TXT | — |
| `watchdog.sh` | t134 코레지 워치독 - 완주까지 자동 재시작, 이후 SBAS·통합맵까지 자동 연결. 왜 별도 unit 인가 systemd-oomd 는 cgroup 안의 프로세스를 통째로 죽인다(t134e 에서  | — | — |
