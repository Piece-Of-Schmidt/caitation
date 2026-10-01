import json
import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# Keep the (large, several GB) HuggingFace model cache next to the index in data/
# instead of the user profile, which often sits on a small system drive.
# Must be set before sentence_transformers/huggingface_hub is imported anywhere.
os.environ.setdefault("HF_HOME", str(DATA_DIR / "hf_cache"))
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

from dotenv import load_dotenv  # noqa: E402

# override=True: this app's own .env should win over any ANTHROPIC_API_KEY that
# happens to already be set in the shell (e.g. from other local tooling).
load_dotenv(override=True)

def _zotero_prefs() -> list[str]:
    """Contents of Zotero's profile prefs.js files (Windows, macOS and Linux locations)."""
    home = Path.home()
    profile_roots = [
        Path(os.environ.get("APPDATA", home / "AppData" / "Roaming")) / "Zotero" / "Zotero" / "Profiles",
        home / "Library" / "Application Support" / "Zotero" / "Profiles",
        home / ".zotero" / "zotero",
    ]
    return [
        prefs.read_text(encoding="utf-8", errors="ignore")
        for root in profile_roots
        for prefs in root.glob("*/prefs.js")
    ]


def _pref(prefs_text: str, name: str):
    """Value of user_pref("name", value) in a prefs.js text (JS literal), or None."""
    match = re.search(
        rf'user_pref\("{re.escape(name)}", ("(?:[^"\\]|\\.)*"|true|false|-?\d+)\);', prefs_text
    )
    return json.loads(match.group(1)) if match else None  # e.g. "E:\\Zotero" -> E:\Zotero


def _zotero_data_dir() -> Path:
    """ZOTERO_DATA_DIR from .env wins; otherwise the custom data directory Zotero
    itself remembers in its profile prefs (so moving the library, e.g. to another
    drive, needs no config change here); otherwise Zotero's default location."""
    if os.environ.get("ZOTERO_DATA_DIR"):
        return Path(os.environ["ZOTERO_DATA_DIR"])
    for prefs in _zotero_prefs():
        if _pref(prefs, "extensions.zotero.useDataDir") is not True:
            continue
        path = _pref(prefs, "extensions.zotero.dataDir")
        if path and (Path(path) / "zotero.sqlite").exists():
            return Path(path)
    return Path.home() / "Zotero"


def _zotero_base_attachment_dir() -> Path | None:
    """Base directory for linked files stored as relative "attachments:" paths
    (Zotero: Settings > Files and Folders > Linked Attachment Base Directory)."""
    if os.environ.get("ZOTERO_BASE_ATTACHMENT_DIR"):
        return Path(os.environ["ZOTERO_BASE_ATTACHMENT_DIR"])
    for prefs in _zotero_prefs():
        path = _pref(prefs, "extensions.zotero.baseAttachmentPath")
        if path:
            return Path(path)
    return None


ZOTERO_DATA_DIR = _zotero_data_dir()
ZOTERO_STORAGE = ZOTERO_DATA_DIR / "storage"
ZOTERO_BASE_ATTACHMENT_DIR = _zotero_base_attachment_dir()

# Copy of Zotero's database written by Caitation up to v0.1. Read once by the upgrade to
# the local API (see indexer._migrate_state), then deleted.
DB_SNAPSHOT = DATA_DIR / "zotero_snapshot.sqlite"
FTS_DB = DATA_DIR / "fts.sqlite"  # keyword index, model-independent

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")

# Cross-encoder reranker for precise re-sorting of the top candidates.
# Set RERANKER_MODEL= (empty) to disable, or point at a bigger model like
# BAAI/bge-reranker-v2-m3 if search latency is acceptable.
RERANKER_MODEL = os.environ.get(
    "RERANKER_MODEL", "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
)
RERANK_TOP_N = 50

# Vector index and its skip-state are per embedding model, so a new model can be
# built in parallel while the server keeps serving the old index. The original
# e5-small generation keeps its legacy file names.
_model_slug = EMBEDDING_MODEL.split("/")[-1]
if _model_slug == "multilingual-e5-small":
    CHROMA_DIR = DATA_DIR / "chroma"
    STATE_FILE = DATA_DIR / "state.json"
else:
    CHROMA_DIR = DATA_DIR / f"chroma-{_model_slug}"
    STATE_FILE = DATA_DIR / f"state-{_model_slug}.json"

# ~2000 chars ≈ 500 tokens: fits within the e5 models' 512-token embedding window,
# so the whole chunk actually contributes to its embedding.
CHUNK_SIZE_CHARS = 2000
CHUNK_OVERLAP_CHARS = 300

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANSWER_MODEL = "claude-haiku-4-5-20251001"

DATA_DIR.mkdir(parents=True, exist_ok=True)
