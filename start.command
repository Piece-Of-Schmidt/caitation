#!/bin/bash
# Caitation starten (macOS/Linux). Beim ersten Start wird die Python-Umgebung eingerichtet.
cd "$(dirname "$0")" || exit 1

if [ ! -x ".venv/bin/python" ]; then
    echo "Erster Start: richte die Python-Umgebung ein. Das dauert einige Minuten ..."
    if ! command -v python3 >/dev/null; then
        echo "python3 wurde nicht gefunden. Bitte Python 3.11 von https://www.python.org installieren."
        exit 1
    fi
    python3 -m venv .venv || exit 1
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt || {
        echo "Die Installation der Pakete ist fehlgeschlagen. Siehe Meldungen oben."
        exit 1
    }
fi

[ -f .env ] || cp .env.example .env

echo "Caitation startet unter http://127.0.0.1:8000 - dieses Fenster offen lassen."
(sleep 4 && (open http://127.0.0.1:8000 2>/dev/null || xdg-open http://127.0.0.1:8000 2>/dev/null)) &
exec .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
