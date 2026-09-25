"""The query path: filter -> BM25 + vector -> RRF fusion -> cross-encoder rerank -> top-k.

    uv run python src/retrieval.py "What is the fee for a stop payment?" --mode hybrid_rerank

Modes (spec.md "Retrieval: modes, fusion, reranking"):
  bm25           keyword search only
  vector         embedding search only
  hybrid         both, merged with Reciprocal Rank Fusion
  hybrid_rerank  hybrid, then the cross-encoder re-scores the fused top 30

The access filter is applied *inside* each retriever, before anything is
truncated, so a filtered-out chunk can never take a slot in the top k.
Every result carries its full metadata (for the citation) and the score it
got at each stage (for explaining why it ranked where it did).
"""

from __future__ import annotations

import argparse
import time
from dataclasses import dataclass, field

import embedding
from config import DEFAULT_PARAMS, INDEX_DIR, load_reranker
from embedding import embed_query
from index import BM25Index, ChromaIndex, Hit, collection_name

MODES = ("bm25", "vector", "hybrid", "hybrid_rerank")


def rrf(ranked_lists: list[list[str]], k: int = 60) -> list[Hit]:
    """Reciprocal Rank Fusion: each list adds 1 / (k + rank) for every chunk in it.

    Only ranks are used, so BM25 scores (0-30ish) and cosine similarities
    (0-1) never have to be put on the same scale. Ties go to chunk_id order.
    """
    scores: dict[str, float] = {}
    for ranking in ranked_lists:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def access_filter(tenant: str, allow_restricted: bool = False, current_only: bool = True) -> dict:
    """The member-facing contact-centre filter (spec "Tenant, access and special queries")."""
    where: dict = {"tenant": tenant}
    if not allow_restricted:
        where["sensitivity_not_in"] = ["restricted"]
    if current_only:
        where["is_current"] = True
    return where


@dataclass
class Result:
    chunk_id: str
    rank: int
    score: float  # the score of the final stage that ordered it
    stage_scores: dict
    text: str
    metadata: dict

    def citation(self) -> str:
        m = self.metadata
        parts = [m["title"]]
        if m.get("version"):
            parts.append(m["version"])
        if m.get("page_start", -1) > 0:
            parts.append(f"p.{m['page_start']}" + (f"-{m['page_end']}" if m["page_end"] != m["page_start"] else ""))
        if m.get("section_path"):
            parts.append(m["section_path"].split(" > ")[-1])
        return ", ".join(parts)


@dataclass
class Response:
    query: str
    mode: str
    where: dict
    results: list[Result]
    timings_ms: dict = field(default_factory=dict)


class Retriever:
    """One parser x chunker index pair, ready to query."""

    _reranker = None  # shared: loading the cross-encoder takes a few seconds

    def __init__(self, parser: str, chunker: str, params: dict = DEFAULT_PARAMS["retrieval"],
                 index_dir=INDEX_DIR):
        name = collection_name(parser, chunker)
        self.params = params
        self.vector = ChromaIndex(name, path=index_dir / "chroma").open()
        self.bm25 = BM25Index(name, path=index_dir / "bm25").open()
        embedding.model()  # load now, so query timings measure search, not model start-up

    @classmethod
    def reranker(cls):
        if cls._reranker is None:
            cls._reranker = load_reranker()
        return cls._reranker

    def search(self, query: str, mode: str = "hybrid_rerank", tenant: str = "retail",
               allow_restricted: bool = False, current_only: bool = True, top_k: int | None = None) -> Response:
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}; choose from {MODES}")
        p = self.params
        top_k = top_k or p["top_k"]
        where = access_filter(tenant, allow_restricted, current_only)
        depth = top_k if mode in ("bm25", "vector") else p["candidates_per_retriever"]
        timings: dict[str, float] = {}
        stage_scores: dict[str, dict] = {}

        bm25_hits: list[Hit] = []
        vector_hits: list[Hit] = []
        if mode != "vector":
            t = time.perf_counter()
            bm25_hits = self.bm25.query(query, depth, where)
            timings["bm25"] = (time.perf_counter() - t) * 1000
        if mode != "bm25":
            t = time.perf_counter()
            vector_hits = self.vector.query(embed_query(query), depth, where)
            timings["vector"] = (time.perf_counter() - t) * 1000  # includes embedding the query
        for name, hits in (("bm25", bm25_hits), ("vector", vector_hits)):
            for rank, (cid, score) in enumerate(hits, start=1):
                stage_scores.setdefault(cid, {})[f"{name}_rank"] = rank
                stage_scores[cid][f"{name}_score"] = score

        if mode == "bm25":
            ranked = bm25_hits
        elif mode == "vector":
            ranked = vector_hits
        else:
            t = time.perf_counter()
            fused = rrf([[c for c, _ in bm25_hits], [c for c, _ in vector_hits]], p["rrf_k"])
            timings["fusion"] = (time.perf_counter() - t) * 1000
            for cid, score in fused:
                stage_scores[cid]["rrf"] = round(score, 6)
            ranked = fused
            if mode == "hybrid_rerank":
                reranker = self.reranker()  # loaded once, outside the timed section
                t = time.perf_counter()
                candidates = [cid for cid, _ in fused[: p["rerank_candidates"]]]
                texts = self.vector.get(candidates)
                scores = reranker.predict([(query, texts[cid]["text"]) for cid in candidates], show_progress_bar=False)
                ranked = sorted(((cid, round(float(s), 6)) for cid, s in zip(candidates, scores)),
                                key=lambda h: (-h[1], h[0]))
                for cid, score in ranked:
                    stage_scores[cid]["rerank"] = score
                timings["rerank"] = (time.perf_counter() - t) * 1000

        top = ranked[:top_k]
        stored = self.vector.get([cid for cid, _ in top])
        results = [Result(cid, rank, score, stage_scores.get(cid, {}), stored[cid]["text"], stored[cid]["metadata"])
                   for rank, (cid, score) in enumerate(top, start=1)]
        timings["total"] = sum(timings.values())
        return Response(query, mode, where, results, {k: round(v, 1) for k, v in timings.items()})


def main() -> None:
    ap = argparse.ArgumentParser(description="Query the Harbor indexes and print cited results.")
    ap.add_argument("query")
    ap.add_argument("--mode", choices=MODES, default="hybrid_rerank")
    ap.add_argument("--parser", choices=["naive", "layout"], default="layout")
    ap.add_argument("--chunker", choices=["A_fixed", "B_structure"], default="B_structure")
    ap.add_argument("--tenant", default="retail")
    ap.add_argument("--allow-restricted", action="store_true")
    ap.add_argument("--include-superseded", action="store_true")
    ap.add_argument("-k", type=int, default=5)
    args = ap.parse_args()

    response = Retriever(args.parser, args.chunker).search(
        args.query, args.mode, args.tenant, args.allow_restricted, not args.include_superseded, args.k)
    print(f"{args.mode} over {args.parser}/{args.chunker}, filter {response.where}")
    for r in response.results:
        stages = ", ".join(f"{k}={v}" for k, v in r.stage_scores.items() if k.endswith(("rank", "rrf", "rerank")))
        snippet = " ".join(r.text.split())[:160]
        print(f"\n{r.rank}. [{r.score}] {r.citation()}\n   {r.chunk_id}  ({stages})\n   {snippet}...")
    print(f"\ntimings (ms): {response.timings_ms}")


if __name__ == "__main__":
    main()
