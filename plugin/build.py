"""Packs plugin/src into an installable Zotero plugin: dist/caitation-zotero-<version>.xpi

    python plugin/build.py
"""

import json
import zipfile
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
DIST = Path(__file__).resolve().parent.parent / "dist"


def build() -> Path:
    manifest = json.loads((SRC / "manifest.json").read_text(encoding="utf-8"))
    DIST.mkdir(exist_ok=True)
    target = DIST / f"caitation-zotero-{manifest['version']}.xpi"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as xpi:
        for path in sorted(SRC.rglob("*")):
            if path.is_file():
                xpi.write(path, path.relative_to(SRC).as_posix())
    return target


if __name__ == "__main__":
    print(build())
