#!/bin/bash
# Caitation starten (macOS/Linux). Der erste Start richtet alles ein; ein vorinstalliertes
# Python ist nicht nötig. Python 3.11 und alle Pakete landen in den Unterordnern .tools
# und .venv dieses Ordners: Zum Deinstallieren genügt es, den Ordner zu löschen.
cd "$(dirname "$0")" || exit 1

# uv (github.com/astral-sh/uv) installiert Python und die Pakete; feste Version mit Prüfsumme.
UV_VERSION=0.12.21
UV="$PWD/.tools/uv"
export UV_CACHE_DIR="$PWD/.tools/uv-cache"
export UV_PYTHON_INSTALL_DIR="$PWD/.tools/python"

fail() {
    echo "$1"
    exit 1
}

if [ ! -x "$UV" ]; then
    case "$(uname -s)-$(uname -m)" in
        Darwin-arm64) asset=uv-aarch64-apple-darwin
            sha256=b88bda573e566ef9bced66b155fe0408626fbbc053aee1c30ba686f0728c9447 ;;
        Darwin-x86_64) asset=uv-x86_64-apple-darwin
            sha256=2b336763b396ec6afa20c5a8b083538ca7402445b868311979d740a4344c17d8 ;;
        Linux-x86_64) asset=uv-x86_64-unknown-linux-gnu
            sha256=23f02075b652bb1df64178cfae41b5caf160822e720e2663568f3f5d63bc52c0 ;;
        Linux-aarch64) asset=uv-aarch64-unknown-linux-gnu
            sha256=030b69227b40af8c1981b7301793dc66e71ed3c796ea8688209dd268bd91ec51 ;;
        *) fail "Dieses System wird nicht unterstützt: $(uname -sm)" ;;
    esac
    echo "Erster Start: lade das Installationswerkzeug uv ..."
    mkdir -p .tools
    curl -fsSL --retry 3 -o .tools/uv.tar.gz \
        "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$asset.tar.gz" \
        || fail "Der Download von uv ist fehlgeschlagen. Bitte die Internetverbindung prüfen und erneut starten."
    actual=$( (shasum -a 256 .tools/uv.tar.gz 2>/dev/null || sha256sum .tools/uv.tar.gz) | cut -d' ' -f1)
    if [ "$actual" != "$sha256" ]; then
        rm -f .tools/uv.tar.gz
        fail "Die Prüfsumme von uv stimmt nicht; Einrichtung abgebrochen."
    fi
    tar -xzf .tools/uv.tar.gz -C .tools --strip-components=1 "$asset/uv" && rm .tools/uv.tar.gz
fi

setup_failed="Die Einrichtung ist fehlgeschlagen, siehe Meldungen oben. Ein erneuter Start versucht es noch einmal."

if [ ! -x ".venv/bin/python" ]; then
    echo "Richte Python 3.11 ein ..."
    "$UV" venv --python 3.11 --managed-python .venv || fail "$setup_failed"
fi

# Pakete nur installieren, wenn sich requirements.txt seit der letzten Einrichtung geändert hat.
if ! cmp -s requirements.txt .venv/caitation-requirements.txt; then
    echo "Installiere die Pakete. Beim ersten Mal dauert das einige Minuten ..."
    if [ "$(uname -s)" = Linux ] && ! command -v nvidia-smi >/dev/null; then
        # PyTorch von PyPI bringt unter Linux mehrere GB GPU-Bibliotheken mit; ohne
        # NVIDIA-Karte reicht die deutlich kleinere CPU-Version.
        "$UV" pip install --python .venv torch --index-url https://download.pytorch.org/whl/cpu \
            || fail "$setup_failed"
    fi
    "$UV" pip install --python .venv -r requirements.txt || fail "$setup_failed"
    cp requirements.txt .venv/caitation-requirements.txt
fi

[ -f .env ] || cp .env.example .env
[ -n "$CAITATION_SETUP_ONLY" ] && exit 0

echo "Caitation startet unter http://127.0.0.1:8000 - dieses Fenster offen lassen."
(sleep 4 && (open http://127.0.0.1:8000 2>/dev/null || xdg-open http://127.0.0.1:8000 2>/dev/null)) &
exec .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
