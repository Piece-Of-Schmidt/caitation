@echo off
rem Caitation starten (Windows). Beim ersten Start wird die Python-Umgebung eingerichtet.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Erster Start: richte die Python-Umgebung ein. Das dauert einige Minuten ...
    python -m venv .venv || (
        echo Python wurde nicht gefunden. Bitte Python 3.11 von https://www.python.org installieren.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (
        echo Die Installation der Pakete ist fehlgeschlagen. Siehe Meldungen oben.
        pause
        exit /b 1
    )
)

if not exist ".env" copy ".env.example" ".env" >nul

echo Caitation startet unter http://127.0.0.1:8000 - dieses Fenster offen lassen.
start "" cmd /c "timeout /t 4 >nul & start http://127.0.0.1:8000"
".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
pause
