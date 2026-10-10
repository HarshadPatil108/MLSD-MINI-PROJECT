"""Hybrid Retriever combining dense Chroma vector search and sparse BM25 via Reciprocal Rank Fusion (RRF)."""

import logging
from collections import defaultdict
from typing import Any

from src.rag.bm25 import BM25Index
from src.rag.schemas import RetrievalResult
from src.rag.store import ChromaStore

logger = logging.getLogger(__name__)


class HybridRetriever:
    """Combines dense vector search (Chroma) and sparse keyword search (BM25) using RRF."""

    def __init__(
        self,
        chroma_store: ChromaStore,
        bm25_index: BM25Index,
        rrf_k: int = 60,
    ):
        self.chroma_store = chroma_store
        self.bm25_index = bm25_index
        self.rrf_k = rrf_k

    def search(
        self,
        query: str,
        top_k: int = 5,
        doc_type_filter: str | None = None,
    ) -> list[RetrievalResult]:
        """Perform hybrid dense + sparse retrieval and merge with Reciprocal Rank Fusion.

        Args:
            query: The search query string (alert description, error message, symptoms).
            top_k: Number of combined results to return.
            doc_type_filter: Optional filter ('pg_docs', 'runbook', 'policy').

        Returns:
            List of RetrievalResult sorted by descending RRF score.
        """
        where_filter: dict[str, Any] | None = None
        if doc_type_filter:
            where_filter = {"doc_type": doc_type_filter}

        # 1. Dense retrieval
        dense_hits = self.chroma_store.query_dense(
            query=query, top_k=top_k * 2, where_filter=where_filter
        )

        # 2. Sparse BM25 retrieval
        sparse_hits = self.bm25_index.query_sparse(
            query=query, top_k=top_k * 2, doc_type_filter=doc_type_filter
        )

        # Maps for rank, content, and metadata
        dense_ranks: dict[str, int] = {}
        for rank, (chunk_id, _, _, _) in enumerate(dense_hits, start=1):
            dense_ranks[chunk_id] = rank

        sparse_ranks: dict[str, int] = {}
        for rank, (chunk_id, _, _, _) in enumerate(sparse_hits, start=1):
            sparse_ranks[chunk_id] = rank

        chunk_contents: dict[str, str] = {}
        chunk_metas: dict[str, dict[str, Any]] = {}

        for chunk_id, _, content, meta in dense_hits:
            chunk_contents[chunk_id] = content
            chunk_metas[chunk_id] = meta

        for chunk_id, _, content, meta in sparse_hits:
            chunk_contents[chunk_id] = content
            chunk_metas[chunk_id] = meta

        # 3. Reciprocal Rank Fusion
        rrf_scores: dict[str, float] = defaultdict(float)
        all_chunk_ids = set(dense_ranks.keys()) | set(sparse_ranks.keys())

        for c_id in all_chunk_ids:
            if c_id in dense_ranks:
                rrf_scores[c_id] += 1.0 / (self.rrf_k + dense_ranks[c_id])
            if c_id in sparse_ranks:
                rrf_scores[c_id] += 1.0 / (self.rrf_k + sparse_ranks[c_id])

        # Sort by RRF score descending
        sorted_ids = sorted(rrf_scores.keys(), key=lambda cid: rrf_scores[cid], reverse=True)

        results: list[RetrievalResult] = []
        for c_id in sorted_ids[:top_k]:
            results.append(
                RetrievalResult(
                    chunk_id=c_id,
                    content=chunk_contents.get(c_id, ""),
                    score=round(rrf_scores[c_id], 6),
                    dense_rank=dense_ranks.get(c_id),
                    sparse_rank=sparse_ranks.get(c_id),
                    metadata=chunk_metas.get(c_id, {}),
                )
            )

        return results
