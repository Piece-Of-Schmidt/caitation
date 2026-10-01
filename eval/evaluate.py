"""Measures search quality against eval/queries.json, using the running Caitation server.

    python eval/evaluate.py                # with the reranker (as users see it)
    python eval/evaluate.py --no-rerank    # hybrid retrieval only, for comparison

Each case lists a query and the titles (or title beginnings) of papers that must be
found. Reported per query: rank of the first expected paper among the top 8, and overall
hit rate (share of queries with an expected paper in the top 8) and MRR (mean reciprocal
rank; 1.0 = always first).
"""

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

CASES = Path(__file__).with_name("queries.json")


def search(server: str, query: str, rerank: bool, top_k: int) -> list[dict]:
    params = urllib.parse.urlencode({"q": query, "top_k": top_k, "rerank": str(rerank).lower()})
    request = urllib.request.Request(f"{server}/api/search?{params}", headers={"X-Caitation-Client": "eval"})
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.load(response)["results"]


def first_hit(results: list[dict], expected: list[str]) -> int | None:
    wanted = [title.casefold() for title in expected]
    for rank, result in enumerate(results, start=1):
        title = (result.get("title") or "").casefold()
        if any(title.startswith(w) or w in title for w in wanted):
            return rank
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--no-rerank", action="store_true")
    parser.add_argument("--top-k", type=int, default=8)
    args = parser.parse_args()

    cases = json.loads(CASES.read_text(encoding="utf-8"))
    reciprocal_ranks, hits = [], 0
    for case in cases:
        results = search(args.server, case["query"], not args.no_rerank, args.top_k)
        rank = first_hit(results, case["expected_titles"])
        hits += rank is not None
        reciprocal_ranks.append(1 / rank if rank else 0.0)
        shown = f"#{rank}" if rank else "–"
        print(f"{shown:>4}  {case['query'][:70]}")
        if rank is None and results:
            print(f"      erwartet: {case['expected_titles'][0][:60]} | Platz 1: {results[0]['title'][:60]}")

    n = len(cases)
    print(f"\nTreffer in den Top {args.top_k}: {hits}/{n} ({hits / n:.0%})   MRR: {sum(reciprocal_ranks) / n:.2f}")
    return 0 if hits == n else 1


if __name__ == "__main__":
    sys.exit(main())
