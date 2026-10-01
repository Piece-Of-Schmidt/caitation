"""Library statistics and a 2D "topic map" of all items (PCA over the
metadata-chunk embeddings) with named KMeans clusters for the dashboard."""

import hashlib
import json
from collections import Counter

import numpy as np
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA

from backend import config
from backend.zotero_reader import ZoteroItem

CLUSTER_NAME_CACHE = config.DATA_DIR / "cluster_names.json"


def library_stats(items: dict[str, ZoteroItem]) -> dict:
    years = Counter()
    types = Counter()
    tags = Counter()
    collections = Counter()
    n_pdf = 0
    n_annotations = 0
    for item in items.values():
        if item.year:
            years[item.year] += 1
        types[item.item_type] += 1
        tags.update(item.tags)
        collections.update(item.collections)
        if item.pdf_paths or item.documents:
            n_pdf += 1
        n_annotations += len(item.annotations)
    return {
        "total_items": len(items),
        "with_pdf": n_pdf,
        "annotations": n_annotations,
        "years": sorted(years.items()),
        "types": types.most_common(),
        "top_tags": tags.most_common(25),
        "top_collections": collections.most_common(25),
    }


def _fallback_label(cluster_items: list[ZoteroItem]) -> str:
    """Most common tag/collection in the cluster as a crude label."""
    counter = Counter()
    for item in cluster_items:
        counter.update(item.tags)
        counter.update(item.collections)
    common = counter.most_common(2)
    return " / ".join(name for name, _ in common) if common else "Sonstiges"


def _claude_labels(samples_per_cluster: list[list[str]]) -> list[str] | None:
    """Asks Claude to name each cluster from sample titles. Returns None on failure."""
    if not config.ANTHROPIC_API_KEY:
        return None
    try:
        from anthropic import Anthropic

        blocks = [
            f"Cluster {i}:\n" + "\n".join(f"- {t}" for t in titles)
            for i, titles in enumerate(samples_per_cluster)
        ]
        prompt = (
            "Hier sind Titel-Stichproben aus Themenclustern einer wissenschaftlichen "
            "Literaturdatenbank. Gib jedem Cluster einen prägnanten deutschen Namen "
            "(2-4 Wörter). Antworte NUR mit einem JSON-Array aus Strings, ein Name pro "
            f"Cluster, in Reihenfolge.\n\n" + "\n\n".join(blocks)
        )
        message = Anthropic(api_key=config.ANTHROPIC_API_KEY).messages.create(
            model=config.ANSWER_MODEL,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in message.content if b.type == "text").strip()
        text = text[text.index("[") : text.rindex("]") + 1]
        labels = json.loads(text)
        if len(labels) == len(samples_per_cluster):
            return [str(l) for l in labels]
    except Exception:
        pass
    return None


def _cluster_labels(
    cache_key: str,
    samples_per_cluster: list[list[str]],
    fallbacks: list[str],
) -> list[str]:
    if CLUSTER_NAME_CACHE.exists():
        try:
            cached = json.loads(CLUSTER_NAME_CACHE.read_text(encoding="utf-8"))
            if cached.get("key") == cache_key:
                return cached["labels"]
        except (json.JSONDecodeError, KeyError):
            pass

    labels = _claude_labels(samples_per_cluster) or fallbacks
    CLUSTER_NAME_CACHE.write_text(
        json.dumps({"key": cache_key, "labels": labels}, ensure_ascii=False),
        encoding="utf-8",
    )
    return labels


_topic_map_cache: dict = {}


def topic_map(collection, items: dict[str, ZoteroItem]) -> dict:
    """Cached wrapper: KMeans + PCA over all embeddings takes seconds, and the result
    only changes when the library or the index does."""
    snapshot_mtime = config.DB_SNAPSHOT.stat().st_mtime if config.DB_SNAPSHOT.exists() else 0
    key = (snapshot_mtime, collection.count())
    if _topic_map_cache.get("key") != key:
        _topic_map_cache.update(key=key, value=_compute_topic_map(collection, items))
    return _topic_map_cache["value"]


def _compute_topic_map(collection, items: dict[str, ZoteroItem]) -> dict:
    """2D projection of every item's metadata embedding plus named KMeans clusters."""
    got = collection.get(
        ids=[f"{key}_meta" for key in items],
        include=["embeddings"],
    )
    if len(got["ids"]) < 10:
        return {"points": [], "clusters": []}

    keys = [chunk_id[: -len("_meta")] for chunk_id in got["ids"]]
    embeddings = np.asarray(got["embeddings"])

    # at most 8: beyond that, cluster colors are no longer reliably distinguishable
    n_clusters = max(4, min(8, len(keys) // 120))
    cluster_ids = KMeans(n_clusters=n_clusters, n_init=4, random_state=42).fit_predict(
        embeddings
    )

    coords = PCA(n_components=2).fit_transform(embeddings)
    mins, maxs = coords.min(axis=0), coords.max(axis=0)
    span = np.where((maxs - mins) == 0, 1, maxs - mins)
    coords = (coords - mins) / span

    points = []
    for key, (x, y), cid in zip(keys, coords, cluster_ids):
        item = items.get(key)
        if item is None:
            continue
        points.append(
            {
                "key": key,
                "x": round(float(x), 4),
                "y": round(float(y), 4),
                "cluster": int(cid),
                "title": item.title[:120],
                "authors": item.authors_str[:100],
                "year": item.year,
                "item_type": item.item_type,
                "collection": item.collections[0] if item.collections else "",
                "zotero_link": item.zotero_link,
                "tags": item.tags[:4],
            }
        )

    # per cluster: centroid (in 2D) + sample titles nearest the embedding centroid
    samples_per_cluster, fallbacks, centroids = [], [], []
    for cid in range(n_clusters):
        mask = cluster_ids == cid
        cluster_keys = [k for k, m in zip(keys, mask) if m]
        cluster_items = [items[k] for k in cluster_keys if k in items]
        centroid_emb = embeddings[mask].mean(axis=0)
        dists = np.linalg.norm(embeddings[mask] - centroid_emb, axis=1)
        nearest = np.argsort(dists)[:12]
        samples_per_cluster.append(
            [cluster_items[i].title[:100] for i in nearest if i < len(cluster_items)]
        )
        fallbacks.append(_fallback_label(cluster_items))
        cx, cy = coords[mask].mean(axis=0)
        centroids.append((float(cx), float(cy)))

    cache_key = hashlib.md5(
        (",".join(sorted(keys)) + f"|k={n_clusters}").encode()
    ).hexdigest()
    labels = _cluster_labels(cache_key, samples_per_cluster, fallbacks)

    clusters = [
        {
            "id": cid,
            "label": labels[cid],
            "x": round(centroids[cid][0], 4),
            "y": round(centroids[cid][1], 4),
            "size": int((cluster_ids == cid).sum()),
        }
        for cid in range(n_clusters)
    ]
    return {"points": points, "clusters": clusters}
