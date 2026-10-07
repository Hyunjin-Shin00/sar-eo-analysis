@echo on
REM TELEPIX Dehazing GUI - Windows build script
REM Prerequisites:
REM   1) Miniconda/Anaconda installed and on PATH
REM   2) conda env created:  conda env create -f environment.yml

REM Move to script's own directory (safe even if double-clicked)
cd /d "%~dp0"

setlocal enabledelayedexpansion
set LOG=build.log

REM Reset log
echo === build start %DATE% %TIME% === > "%LOG%"
echo CWD=%CD% >> "%LOG%"
echo. >> "%LOG%"

echo.
echo CWD = %CD%
echo LOG = %CD%\%LOG%
echo.

echo [1/4] conda activate dehaze_gui ...
where conda
if errorlevel 1 (
    echo [ERROR] "conda" not found in PATH.
    echo   - run from "Anaconda Prompt" / "Miniconda3 Prompt"
    echo   - or add Miniconda Scripts folder to PATH
    goto :end
)

call conda activate dehaze_gui >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [ERROR] conda env "dehaze_gui" activation failed.
    echo   create it first:  conda env create -f environment.yml
    goto :showlog
)

echo [2/4] python / pyinstaller version
where python       >> "%LOG%" 2>&1
python --version
python --version       >> "%LOG%" 2>&1
where pyinstaller  >> "%LOG%" 2>&1
pyinstaller --version
pyinstaller --version  >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [ERROR] pyinstaller not found in active env.
    echo   install:  conda install -n dehaze_gui pyinstaller
    goto :showlog
)

echo [3/4] dependency import check
python -c "import osgeo.gdal as g, PyQt5, netCDF4, scipy, skimage, numpy, PIL; print('osgeo', g.__version__); print('ok')"
python -c "import osgeo.gdal as g, PyQt5, netCDF4, scipy, skimage, numpy, PIL; print('osgeo', g.__version__); print('ok')" >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [ERROR] dependency import failed.
    goto :showlog
)

echo [4/4] PyInstaller build
pyinstaller dehaze_gui.spec --noconfirm --clean >> "%LOG%" 2>&1
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed.
    goto :showlog
)

echo.
echo === build done ===
if exist dist\DehazingGUI\DehazingGUI.exe (
    echo [OK]  dist\DehazingGUI\DehazingGUI.exe
) else (
    echo [MISSING] dist\DehazingGUI\DehazingGUI.exe
)
echo --- proj.db / gdal_datums.csv / qwindows.dll location ---
where /r dist\DehazingGUI proj.db          2>nul
where /r dist\DehazingGUI gdal_datums.csv  2>nul
where /r dist\DehazingGUI qwindows.dll     2>nul
echo.
echo deploy: copy entire "dist\DehazingGUI" folder to offline PC
goto :end

:showlog
echo.
echo --- build.log last 60 lines ---
powershell -NoProfile -Command "Get-Content '%LOG%' -Tail 60"

:end
endlocal
echo.
echo (press any key to close)
pause >nul
