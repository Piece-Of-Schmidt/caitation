import json
import logging
import sqlite3
import threading
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, HTTPException
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import config, duplicates, indexer, rag, zotero_reader
from backend.bibtex import items_to_bibtex
from backend.security import LocalOnlyMiddleware

# Errors and timings also go to data/caitation.log, so colleagues can send it along
# when something goes wrong (the console window is often closed by then).
LOG_FILE = config.DATA_DIR / "caitation.log"
log = logging.getLogger("uvicorn.error")
if not any(isinstance(h, RotatingFileHandler) for h in log.handlers):
    _file_handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    _file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(_file_handler)
    log.setLevel(logging.INFO)

_reindex_lock = threading.Lock()


def _start_reindex() -> bool:
    # Take the lock before the thread starts: no window in which the status reports
    # "not running" and no chance for two concurrent runs.
    if not _reindex_lock.acquire(blocking=False):
        return False

    def _run():
        try:
            indexer.run_reindex()
        except Exception as error:
            log.exception("Reindex failed")
            indexer.report_error(f"{type(error).__name__}: {error}")
        finally:
            _reindex_lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return True


def _snapshot_stale() -> bool:
    if indexer.reindex_incomplete():
        return True
    try:
        zotero_mtime = config.ZOTERO_SQLITE.stat().st_mtime
    except OSError:
        return False
    return (
        not config.DB_SNAPSHOT.exists()
        or zotero_mtime > config.DB_SNAPSHOT.stat().st_mtime
    )


DEVICE = indexer.compute_device()
_DEVICE_LABELS = {"cuda": "GPU (CUDA)", "mps": "Apple-Grafikchip (MPS)", "cpu": "CPU"}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log.info("Caitation: Modelle rechnen auf %s", _DEVICE_LABELS.get(DEVICE, DEVICE))
    # Load models and warm caches in the background so the first search is fast.
    threading.Thread(target=rag.warmup, daemon=True, name="warmup").start()
    # Incremental reindex if the Zotero library changed since the last snapshot;
    # unchanged items are skipped by hash, so this is cheap.
    if _snapshot_stale():
        _start_reindex()
    yield


app = FastAPI(title="Caitation", lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1000)  # skips SSE streams
app.add_middleware(LocalOnlyMiddleware)  # added last = runs first


class AskRequest(BaseModel):
    query: str
    history: list[dict] | None = None
    mode: str = "answer"  # "answer" | "evidence"
    year_from: int | None = None
    year_to: int | None = None
    item_type: str | None = None
    tag: str | None = None
    collection: str | None = None
    library: str | None = None
    annotations_only: bool | None = False


def _filters(year_from, year_to, item_type, tag, collection, annotations_only=False, library=None) -> dict:
    return {
        "year_from": year_from,
        "year_to": year_to,
        "item_type": item_type,
        "tag": tag,
        "collection": collection,
        "library": library,
        "annotations_only": annotations_only,
    }


@app.get("/api/search")
def api_search(
    q: str,
    top_k: int = 8,
    year_from: int | None = None,
    year_to: int | None = None,
    item_type: str | None = None,
    tag: str | None = None,
    collection: str | None = None,
    library: str | None = None,
    annotations_only: bool = False,
    rerank: bool = True,
):
    filters = _filters(year_from, year_to, item_type, tag, collection, annotations_only, library)
    results = rag.search(q, top_k=top_k, filters=filters, rerank=rerank)
    for r in results:
        r.pop("_context", None)  # LLM context only, not needed by the browser
    return {"results": results, "reranked": rerank and bool(config.RERANKER_MODEL)}


@app.post("/api/ask")
def api_ask(req: AskRequest):
    filters = _filters(
        req.year_from, req.year_to, req.item_type, req.tag, req.collection, req.annotations_only,
        req.library,
    )
    return rag.ask(req.query, filters=filters, history=req.history, mode=req.mode)


@app.post("/api/ask/stream")
def api_ask_stream(req: AskRequest):
    filters = _filters(
        req.year_from, req.year_to, req.item_type, req.tag, req.collection, req.annotations_only,
        req.library,
    )

    def event_stream():
        for event in rag.ask_stream(
            req.query, filters=filters, history=req.history, mode=req.mode
        ):
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/bibtex")
def api_bibtex(keys: str):
    info = rag.get_item_info()
    items = [info[k] for k in keys.split(",") if k in info]
    if not items:
        raise HTTPException(status_code=404, detail="Keine passenden Einträge.")
    return PlainTextResponse(
        items_to_bibtex(items),
        media_type="application/x-bibtex",
        headers={"Content-Disposition": "attachment; filename=caitation-export.bib"},
    )


@app.get("/api/related/{item_key}")
def api_related(item_key: str, top_k: int = 6):
    return {"results": rag.related(item_key, top_k=top_k)}


@app.get("/api/duplicates")
def api_duplicates():
    groups = duplicates.find_duplicate_groups(rag.get_item_info())
    return {"groups": groups, "count": len(groups)}


@app.get("/api/stats")
def api_stats():
    from backend import stats

    info = rag.get_item_info()
    return {
        "stats": stats.library_stats(info),
        "topic_map": stats.topic_map(rag._get_collection(), info),
    }


@app.get("/api/filters")
def api_filters():
    """Available filter values (item types, tags, collections, year range)."""
    items = rag.get_item_info().values()
    types, tags, collections, libraries, years = set(), set(), set(), set(), []
    for item in items:
        types.add(item.item_type)
        tags.update(item.tags)
        collections.update(item.collections)
        libraries.add(item.library_name)
        if item.year:
            years.append(item.year)
    return {
        "item_types": sorted(types),
        "tags": sorted(tags),
        "collections": sorted(collections),
        "libraries": sorted(libraries),
        "year_min": min(years) if years else None,
        "year_max": max(years) if years else None,
    }


@app.get("/api/pdf/{item_key}")
def api_pdf(item_key: str):
    item = rag.get_item_info().get(item_key)
    if item is None or not item.pdf_paths:
        raise HTTPException(status_code=404, detail="Kein PDF für dieses Item.")
    return FileResponse(item.pdf_paths[0], media_type="application/pdf")


@app.post("/api/reindex")
def api_reindex():
    if not _start_reindex():
        return {"started": False, "message": "Reindex läuft bereits."}
    return {"started": True}


@app.get("/api/reindex/status")
def api_reindex_status():
    progress = indexer.get_progress()
    progress["running"] = _reindex_lock.locked()
    progress["ready"] = rag.is_ready()
    progress["device"] = DEVICE
    progress["warning"] = _schema_warning()
    return progress


_schema_cache: dict = {}


def _schema_warning() -> str | None:
    """Warning if Zotero's database is newer than the tested layout (cached per snapshot)."""
    try:
        mtime = config.DB_SNAPSHOT.stat().st_mtime
    except OSError:
        return None
    if _schema_cache.get("mtime") != mtime:
        try:
            version = zotero_reader.schema_version(config.DB_SNAPSHOT)
        except sqlite3.Error:
            version = None
        _schema_cache.update(mtime=mtime, warning=zotero_reader.schema_warning(version))
        if _schema_cache["warning"]:
            log.warning(_schema_cache["warning"])
    return _schema_cache["warning"]


class _RevalidatingStaticFiles(StaticFiles):
    """Frontend files are tiny and local: always revalidate (cheap 304 via ETag) so
    a changed app.js/style.css is picked up without cache-busting query strings."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount(
    "/",
    _RevalidatingStaticFiles(directory=str(config.PROJECT_ROOT / "frontend"), html=True),
    name="frontend",
)

