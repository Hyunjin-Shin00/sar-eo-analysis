"""지점 설정. 환경변수 SITE=GP|HS (기본 GP)"""
import os
SITES = {
    # RDA 관측소 좌표 = Cho et al.(2026) site_info.xlsx
    "GP": dict(name="가평(RDA 가평읍)", lon=127.50063, lat=37.84621, aoi=(127.44, 37.80, 127.56, 37.89), mgrs="52SCG",
               data="<WORK_ROOT>/data", insitu="insitu_rda/GP_daily_2017_2026.csv", out="<WORK_ROOT>/outputs/GP"),
    "HS": dict(name="화성(RDA 장안면)", lon=126.87380, lat=37.07730, aoi=(126.815, 37.030, 126.935, 37.120), mgrs=None,
               data="<WORK_ROOT>/data/HS", insitu="insitu_rda/HS_daily.csv", out="<WORK_ROOT>/outputs/HS"),
}
SITE = os.environ.get("SITE", "GP"); C = SITES[SITE]
