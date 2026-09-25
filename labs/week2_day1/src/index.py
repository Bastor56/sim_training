"""The two indexes hybrid search needs, behind small interfaces (spec.md "Index interface").

ChromaIndex  vector search: one persistent collection per parser x chunker x
             embedding revision, cosine distance, all chunk metadata stored
             for filtering and citation.
BM25Index    keyword search: rank_bm25 over the same chunk texts, pickled.

Both take the same small filter format and translate it themselves:
    {"tenant": "retail", "sensitivity_not_in": ["restricted"], "is_current": True}
so the query path never writes Chroma-specific syntax, and swapping Chroma
for pgvector later means one new class, nothing else.
"""

from __future__ import annotations

import pickle
import re
from pathlib import Path
from typing import Protocol

from config import DEFAULT_PARAMS, INDEX_DIR, model_spec
from golden import normalise
from models import Chunk

Hit = tuple[str, float]  # (chunk_id, score); higher is better


class IndexRevisionMismatch(RuntimeError):
    """The index was built with a different embedding model revision than the manifest pins."""


class VectorIndex(Protocol):
    def add(self, chunks: list[Chunk]) -> None: ...
    def query(self, vector: list[float], n: int, where: dict | None = None) -> list[Hit]: ...
    def count(self) -> int: ...


class LexicalIndex(Protocol):
    def build(self, chunks: list[Chunk]) -> None: ...
    def query(self, text: str, n: int, where: dict | None = None) -> list[Hit]: ...


# ---------------------------------------------------------------- the shared filter format

def matches_where(metadata: dict, where: dict | None) -> bool:
    """The filter as a plain Python check (used by BM25, and to test Chroma's translation)."""
    for key, value in (where or {}).items():
        if key.endswith("_not_in"):
            if metadata[key[: -len("_not_in")]] in value:
                return False
        elif key.endswith("_in"):
            if metadata[key[: -len("_in")]] not in value:
                return False
        elif metadata[key] != value:
            return False
    return True


def to_chroma_where(where: dict | None) -> dict | None:
    clauses = []
    for key, value in (where or {}).items():
        if key.endswith("_not_in"):
            clauses.append({key[: -len("_not_in")]: {"$nin": list(value)}})
        elif key.endswith("_in"):
            clauses.append({key[: -len("_in")]: {"$in": list(value)}})
        else:
            clauses.append({key: {"$eq": value}})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def _ranked(hits: list[Hit], n: int) -> list[Hit]:
    """Best first; ties broken by chunk_id so the order is deterministic."""
    return sorted(hits, key=lambda h: (-h[1], h[0]))[:n]


# ---------------------------------------------------------------- Chroma

def collection_name(parser: str, chunker: str, revision: str | None = None) -> str:
    revision = revision or model_spec("embedder")["revision"]
    return f"harbor__{parser}__{chunker}__{revision[:8]}"


def _client(path: Path):
    import chromadb
    from chromadb.config import Settings

    return chromadb.PersistentClient(path=str(path), settings=Settings(anonymized_telemetry=False))


class ChromaIndex:
    def __init__(self, name: str, path: Path = INDEX_DIR / "chroma"):
        self.name = name
        self.client = _client(path)
        self.collection = None

    def create(self, cache_key: str) -> None:
        """Replace any existing collection of this name with an empty one."""
        spec = model_spec("embedder")
        if self.name in [c.name for c in self.client.list_collections()]:
            self.client.delete_collection(self.name)
        self.collection = self.client.create_collection(
            self.name,
            configuration={"hnsw": {"space": "cosine"}},
            metadata={"embedding_model": spec["model"], "embedding_revision": spec["revision"], "cache_key": cache_key},
            embedding_function=None,  # never let Chroma embed with its own default model
        )

    def open(self) -> "ChromaIndex":
        """Open an existing collection, refusing one built with another model revision."""
        self.collection = self.client.get_collection(self.name, embedding_function=None)
        built_with = self.collection.metadata.get("embedding_revision")
        pinned = model_spec("embedder")["revision"]
        if built_with != pinned:
            raise IndexRevisionMismatch(f"{self.name} was built with embedding revision {built_with}, "
                                        f"but model_manifest.json pins {pinned}; rebuild the index")
        return self

    def cache_key(self) -> str | None:
        try:
            return self.client.get_collection(self.name, embedding_function=None).metadata.get("cache_key")
        except Exception:  # collection doesn't exist
            return None

    def add(self, chunks: list[Chunk], batch: int = 256) -> None:
        for i in range(0, len(chunks), batch):
            part = chunks[i:i + batch]
            self.collection.add(ids=[c.chunk_id for c in part], embeddings=[c.embedding for c in part],
                                documents=[c.text for c in part], metadatas=[c.metadata for c in part])

    def query(self, vector: list[float], n: int, where: dict | None = None) -> list[Hit]:
        n = min(n, self.count())
        if n == 0:
            return []
        result = self.collection.query(query_embeddings=[vector], n_results=n, where=to_chroma_where(where),
                                       include=["distances"])
        # Cosine distance = 1 - cosine similarity; report similarity so higher is better.
        return _ranked([(cid, round(1.0 - d, 6)) for cid, d in zip(result["ids"][0], result["distances"][0])], n)

    def count(self) -> int:
        return self.collection.count()

    def get(self, ids: list[str]) -> dict[str, dict]:
        """chunk_id -> {"text", "metadata"}, for building results with citations."""
        got = self.collection.get(ids=ids, include=["documents", "metadatas"])
        return {cid: {"text": doc, "metadata": meta}
                for cid, doc, meta in zip(got["ids"], got["documents"], got["metadatas"])}

    def all_texts(self) -> list[str]:
        return self.collection.get(include=["documents"])["documents"]


# ---------------------------------------------------------------- BM25

_TOKEN = re.compile(r"[a-z0-9$][a-z0-9$%.\-/,]*[a-z0-9%]|[a-z0-9$%]")


def tokenize(text: str) -> list[str]:
    """Golden-set normalisation, then tokens that keep "4.05%", "$30.00",
    "hcu-dsp-114" and "5/1/5" whole. No stemming, no stopword removal."""
    return _TOKEN.findall(normalise(text))


class BM25Index:
    def __init__(self, name: str, path: Path = INDEX_DIR / "bm25", params: dict = DEFAULT_PARAMS["bm25"]):
        self.file = path / f"{name}.pkl"
        self.params = params
        self.chunk_ids: list[str] = []
        self.metadata: list[dict] = []
        self.bm25 = None
        self.key: str | None = None

    def build(self, chunks: list[Chunk], cache_key: str = "") -> None:
        from rank_bm25 import BM25Okapi

        self.chunk_ids = [c.chunk_id for c in chunks]
        self.metadata = [c.metadata for c in chunks]
        self.bm25 = BM25Okapi([tokenize(c.text) for c in chunks], k1=self.params["k1"], b=self.params["b"])
        self.key = cache_key
        self.file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.file, "wb") as f:
            pickle.dump({"chunk_ids": self.chunk_ids, "metadata": self.metadata, "bm25": self.bm25,
                         "params": self.params, "cache_key": cache_key}, f)

    def open(self) -> "BM25Index":
        with open(self.file, "rb") as f:
            state = pickle.load(f)
        self.chunk_ids, self.metadata, self.bm25, self.key = (
            state["chunk_ids"], state["metadata"], state["bm25"], state["cache_key"])
        return self

    def cache_key(self) -> str | None:
        return self.open().key if self.file.exists() else None

    def query(self, text: str, n: int, where: dict | None = None) -> list[Hit]:
        """Score every chunk, drop those failing the filter, *then* take the top n.

        rank_bm25 has no filter support. Truncating first would return fewer
        than n results whenever a high-scoring chunk is filtered out.
        """
        scores = self.bm25.get_scores(tokenize(text))
        hits = [(cid, round(float(s), 6)) for cid, s, meta in zip(self.chunk_ids, scores, self.metadata)
                if s > 0 and matches_where(meta, where)]
        return _ranked(hits, n)
