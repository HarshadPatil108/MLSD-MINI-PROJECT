"""BM25 sparse retriever over document chunks."""

import json
import logging
import re
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

from src.rag.schemas import DocumentChunk

logger = logging.getLogger(__name__)


def tokenize_text(text: str) -> list[str]:
    """Tokenize query and documents for BM25 with lowercase alphanumeric words and identifiers."""
    return re.findall(r"[a-zA-Z0-9_]+", text.lower())


class BM25Index:
    """In-memory BM25 index with JSON serialization for fast rehydration."""

    def __init__(self, storage_path: str = "data/bm25_chunks.json"):
        self.storage_path = Path(storage_path)
        self.chunks: dict[str, DocumentChunk] = {}
        self.chunk_ids: list[str] = []
        self._bm25: BM25Okapi | None = None

    def build_index(self, chunks: list[DocumentChunk]) -> None:
        """Fit BM25 model on supplied DocumentChunks and persist."""
        self.chunks = {c.chunk_id: c for c in chunks}
        self.chunk_ids = list(self.chunks.keys())

        if not self.chunk_ids:
            self._bm25 = None
            return

        corpus_tokens = [tokenize_text(c.content) for c in self.chunks.values()]
        self._bm25 = BM25Okapi(corpus_tokens)
        self.save()

    def update_chunks(
        self, new_or_updated: list[DocumentChunk], removed_ids: list[str] | None = None
    ) -> None:
        """Selectively update chunks and rebuild BM25 model."""
        if removed_ids:
            for rid in removed_ids:
                self.chunks.pop(rid, None)

        for c in new_or_updated:
            self.chunks[c.chunk_id] = c

        self.build_index(list(self.chunks.values()))

    def query_sparse(
        self,
        query: str,
        top_k: int = 10,
        doc_type_filter: str | None = None,
    ) -> list[tuple[str, float, str, dict[str, Any]]]:
        """Execute BM25 search over corpus chunks.

        Returns:
            List of (chunk_id, bm25_score, content, metadata)
        """
        if not self._bm25 or not self.chunk_ids:
            return []

        query_tokens = tokenize_text(query)
        if not query_tokens:
            return []

        scores = self._bm25.get_scores(query_tokens)

        # Pair up chunk_id and score
        results: list[tuple[str, float, str, dict[str, Any]]] = []
        for c_id, score in zip(self.chunk_ids, scores):
            if score <= 0.0:
                continue
            chunk = self.chunks[c_id]
            if doc_type_filter and chunk.doc_type != doc_type_filter:
                continue
            meta = {
                "doc_type": chunk.doc_type,
                "pg_version": chunk.pg_version,
                "source_file": chunk.source_file,
                "section_id": chunk.section_id,
                "header_path": chunk.header_path,
                "source_hash": chunk.source_hash,
                "token_count": chunk.token_count,
            }
            results.append((c_id, float(score), chunk.content, meta))

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def save(self) -> None:
        """Persist chunk corpus to disk for reload."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        data = {c_id: c.model_dump(mode="json") for c_id, c in self.chunks.items()}
        self.storage_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load(self) -> bool:
        """Load chunks from disk and initialize BM25Okapi."""
        if not self.storage_path.exists():
            return False
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
            loaded_chunks = [DocumentChunk(**item) for item in data.values()]
            self.chunks = {c.chunk_id: c for c in loaded_chunks}
            self.chunk_ids = list(self.chunks.keys())
            if self.chunk_ids:
                corpus_tokens = [tokenize_text(c.content) for c in self.chunks.values()]
                self._bm25 = BM25Okapi(corpus_tokens)
            return True
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning("Failed to load BM25 index from %s: %s", self.storage_path, exc)
            return False

    def count(self) -> int:
        """Return total chunks in BM25 index."""
        return len(self.chunks)
