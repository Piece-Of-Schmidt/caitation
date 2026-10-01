@echo off
rem Caitation starten (Windows). Der erste Start richtet alles ein; ein vorinstalliertes
rem Python ist nicht noetig. Python 3.11 und alle Pakete landen in den Unterordnern .tools
rem und .venv dieses Ordners: Zum Deinstallieren genuegt es, den Ordner zu loeschen.
setlocal
cd /d "%~dp0"
title Caitation

rem Laeuft Caitation schon (z.B. zweiter Klick im Startmenue)? Dann nur den Browser oeffnen.
if not defined CAITATION_SETUP_ONLY (
    curl.exe -fs -o nul --max-time 2 http://127.0.0.1:8000/api/reindex/status >nul 2>&1 && (
        start http://127.0.0.1:8000
        exit /b 0
    )
)

rem uv (github.com/astral-sh/uv) installiert Python und die Pakete; feste Version mit Pruefsumme.
set "UV_VERSION=0.12.21"
set "UV=%CD%\.tools\uv.exe"
set "UV_CACHE_DIR=%CD%\.tools\uv-cache"
set "UV_PYTHON_INSTALL_DIR=%CD%\.tools\python"

if exist "%UV%" goto have_uv
echo Erster Start: lade das Installationswerkzeug uv ...
set "UV_ASSET=uv-x86_64-pc-windows-msvc.zip"
set "UV_SHA256=5d223efa0bf00208c3853246af09420419dfbd352536aa6bb8163d6170e23890"
if /i "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
    set "UV_ASSET=uv-aarch64-pc-windows-msvc.zip"
    set "UV_SHA256=93ed53b94e9cec000cacdfd18ca67bc4cb2b6a5f5ec041edd7f2a3dae365ce79"
)
if not exist ".tools" mkdir ".tools"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue';" ^
    "[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12;" ^
    "Invoke-WebRequest -UseBasicParsing -OutFile '.tools\uv.zip' -Uri 'https://github.com/astral-sh/uv/releases/download/%UV_VERSION%/%UV_ASSET%';" ^
    "if ((Get-FileHash '.tools\uv.zip' -Algorithm SHA256).Hash -ne '%UV_SHA256%') { Remove-Item '.tools\uv.zip'; throw 'Pruefsumme stimmt nicht' }" ^
    "Expand-Archive '.tools\uv.zip' '.tools' -Force; Remove-Item '.tools\uv.zip'"
if errorlevel 1 goto fail_download
:have_uv

if exist ".venv\Scripts\python.exe" goto have_venv
echo Richte Python 3.11 ein ...
"%UV%" venv --python 3.11 --managed-python .venv || goto fail_setup
:have_venv

rem Pakete nur installieren, wenn sich requirements.txt seit der letzten Einrichtung geaendert hat.
fc /b requirements.txt ".venv\caitation-requirements.txt" >nul 2>&1 && goto installed
echo Installiere die Pakete. Beim ersten Mal dauert das einige Minuten ...
where nvidia-smi >nul 2>&1 && (
    echo NVIDIA-Grafikkarte gefunden: PyTorch mit GPU-Unterstuetzung wird installiert.
    "%UV%" pip install --python .venv torch --index-url https://download.pytorch.org/whl/cu126 || goto fail_setup
)
"%UV%" pip install --python .venv -r requirements.txt || goto fail_setup
copy /y requirements.txt ".venv\caitation-requirements.txt" >nul
:installed

if not exist ".env" copy ".env.example" ".env" >nul
if defined CAITATION_SETUP_ONLY exit /b 0

echo Caitation startet unter http://127.0.0.1:8000 - dieses Fenster offen lassen.
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8000"
".venv\Scripts\python.exe" -m backend
pause
exit /b 0

:fail_download
echo Der Download von uv ist fehlgeschlagen. Bitte die Internetverbindung pruefen und erneut starten.
goto fail
:fail_setup
echo Die Einrichtung ist fehlgeschlagen, siehe Meldungen oben. Ein erneuter Start versucht es noch einmal.
:fail
if not defined CAITATION_SETUP_ONLY pause
exit /b 1
