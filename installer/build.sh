#!/bin/bash
# Builds dist/Caitation-Setup-<version>.exe with Inno Setup (Windows, Git Bash / CI).
# The version comes from the plugin manifest, so app and plugin are released together.
set -euo pipefail
cd "$(dirname "$0")/.."
version=$(python -c "import json; print(json.load(open('plugin/src/manifest.json'))['version'])")
iscc=$(command -v iscc || true)
default="/c/Program Files (x86)/Inno Setup 6/ISCC.exe"
if [ -z "$iscc" ]; then
    [ -x "$default" ] || choco install innosetup -y --no-progress
    iscc=$default
fi
"$iscc" //Qp "//DAppVersion=$version" installer/caitation.iss
echo "dist/Caitation-Setup-$version.exe"
