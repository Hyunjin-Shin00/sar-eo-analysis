@echo off
REM 가상환경 설정 스크립트 (Windows)

echo ==========================================
echo 기하보정 파이프라인 가상환경 설정
echo ==========================================

REM Python 버전 확인
echo.
echo [INFO] Python 버전 확인 중...
python --version
if errorlevel 1 (
    echo [ERROR] Python이 설치되어 있지 않거나 PATH에 없습니다.
    pause
    exit /b 1
)

REM 가상환경 생성
set VENV_NAME=venv
if exist "%VENV_NAME%" (
    echo.
    echo [WARNING] 가상환경 '%VENV_NAME%'가 이미 존재합니다.
    set /p DELETE="   삭제하고 다시 만들까요? (y/n): "
    if /i "%DELETE%"=="y" (
        echo     기존 가상환경 삭제 중...
        rmdir /s /q "%VENV_NAME%"
    ) else (
        echo     기존 가상환경을 사용합니다.
        call "%VENV_NAME%\Scripts\activate.bat"
        python -m pip install --upgrade pip
        pip install -r requirements.txt
        echo.
        echo [SUCCESS] 가상환경 설정 완료!
        echo.
        echo 가상환경 활성화:
        echo     %VENV_NAME%\Scripts\activate.bat
        pause
        exit /b 0
    )
)

echo.
echo [INFO] 가상환경 생성 중...
python -m venv "%VENV_NAME%"

REM 가상환경 활성화
echo [INFO] 가상환경 활성화 중...
call "%VENV_NAME%\Scripts\activate.bat"

REM pip 업그레이드
echo.
echo [INFO] pip 업그레이드 중...
python -m pip install --upgrade pip setuptools wheel

REM GDAL 확인
echo.
echo [INFO] GDAL 설치 확인 중...
where gdal-config >nul 2>&1
if errorlevel 1 (
    echo     [WARNING] GDAL이 시스템에 설치되어 있지 않습니다.
    echo.
    echo     Windows에서 GDAL 설치 방법:
    echo        1. OSGeo4W 설치: https://trac.osgeo.org/osgeo4w/
    echo        2. 또는 conda 사용: conda install -c conda-forge gdal
    echo.
    set /p CONTINUE="   계속 진행하시겠습니까? (y/n): "
    if /i not "%CONTINUE%"=="y" (
        echo     설치가 취소되었습니다.
        deactivate
        pause
        exit /b 1
    )
) else (
    echo     [SUCCESS] GDAL이 설치되어 있습니다.
    echo     GDAL Python 바인딩 설치 중...
    for /f "tokens=*" %%i in ('gdal-config --version') do set GDAL_VERSION=%%i
    pip install gdal==%GDAL_VERSION%
)

REM requirements.txt 설치
echo.
echo [INFO] 패키지 설치 중...
echo     이 과정은 몇 분이 소요될 수 있습니다...
pip install -r requirements.txt

echo.
echo ==========================================
echo [SUCCESS] 가상환경 설정 완료!
echo ==========================================
echo.
echo 가상환경 활성화:
echo     %VENV_NAME%\Scripts\activate.bat
echo.
echo GUI 앱 실행:
echo     python gui_app.py
echo.
echo 파이프라인 직접 실행:
echo     python geometric_correction.py
echo.
echo 가상환경 비활성화:
echo     deactivate
echo.
pause

