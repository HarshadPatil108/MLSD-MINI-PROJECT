"""Chroma vector store repository with CPU all-MiniLM-L6-v2 embeddings and ID-based upsert."""

import json
import logging
from pathlib import Path
from typing import Any

import chromadb
from chromadb.api.models.Collection import Collection
from sentence_transformers import SentenceTransformer

from src.rag.schemas import DocumentChunk, IndexManifest

logger = logging.getLogger(__name__)


class ChromaStore:
    """Chroma vector store repository handling idempotent ID-based upsert and dense query."""

    def __init__(
        self,
        persist_directory: str = "data/chroma_db",
        collection_name: str = "incidentops_corpus",
        embedding_model_name: str = "all-MiniLM-L6-v2",
        embedder: Any | None = None,
        client: chromadb.ClientAPI | None = None,
    ):
        self.persist_directory = persist_directory
        self.collection_name = collection_name
        self.embedding_model_name = embedding_model_name

        # Ensure directory exists if persistent
        Path(self.persist_directory).mkdir(parents=True, exist_ok=True)

        if client is not None:
            self.client = client
        else:
            self.client = chromadb.PersistentClient(path=self.persist_directory)

        self.collection: Collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        # Lazy or injected embedder for CPU all-MiniLM-L6-v2
        self._embedder = embedder

    @property
    def embedder(self) -> Any:
        """Lazy load CPU SentenceTransformer model."""
        if self._embedder is None:
            logger.info("Loading SentenceTransformer '%s' on CPU", self.embedding_model_name)
            self._embedder = SentenceTransformer(self.embedding_model_name, device="cpu")
        return self._embedder

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Compute CPU dense vector embeddings for input texts."""
        if not texts:
            return []
        embeddings = self.embedder.encode(
            texts,
            convert_to_numpy=True,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return embeddings.tolist()

    def upsert_chunks(self, chunks: list[DocumentChunk]) -> int:
        """Idempotently upsert document chunks by deterministic chunk_id."""
        if not chunks:
            return 0

        ids = [c.chunk_id for c in chunks]
        documents = [c.content for c in chunks]
        metadatas = [
            {
                "doc_type": c.doc_type,
                "pg_version": c.pg_version,
                "source_file": c.source_file,
                "section_id": c.section_id,
                "header_path": c.header_path,
                "source_hash": c.source_hash,
                "token_count": c.token_count,
            }
            for c in chunks
        ]

        # Compute embeddings on CPU
        embeddings = self.embed_texts(documents)

        # Upsert into Chroma
        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
        )
        return len(chunks)

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        """Remove specified chunk IDs from the collection."""
        if chunk_ids:
            try:
                self.collection.delete(ids=chunk_ids)
            except (ValueError, KeyError, OSError, RuntimeError) as exc:
                logger.warning("Failed to delete chunks: %s", exc)

    def query_dense(
        self,
        query: str,
        top_k: int = 10,
        where_filter: dict[str, Any] | None = None,
    ) -> list[tuple[str, float, str, dict[str, Any]]]:
        """Query vector index using cosine similarity.

        Returns:
            List of (chunk_id, score, document_text, metadata)
        """
        if self.collection.count() == 0:
            return []

        query_emb = self.embed_texts([query])
        kwargs: dict[str, Any] = {
            "query_embeddings": query_emb,
            "n_results": min(top_k, self.collection.count()),
        }
        if where_filter:
            kwargs["where"] = where_filter

        results = self.collection.query(**kwargs)

        hits: list[tuple[str, float, str, dict[str, Any]]] = []
        if results and results["ids"] and len(results["ids"][0]) > 0:
            ids = results["ids"][0]
            distances = results["distances"][0] if results.get("distances") else [0.0] * len(ids)
            docs = results["documents"][0] if results.get("documents") else [""] * len(ids)
            metas = results["metadatas"][0] if results.get("metadatas") else [{}] * len(ids)

            for c_id, dist, doc, meta in zip(ids, distances, docs, metas):
                # Cosine distance to similarity: 1 - dist
                sim = 1.0 - dist if dist is not None else 0.0
                hits.append((c_id, sim, doc, meta or {}))

        return hits

    def count(self) -> int:
        """Return total chunks in collection."""
        return self.collection.count()

    def clear(self) -> None:
        """Clear all records from collection."""
        self.client.delete_collection(self.collection_name)
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name, metadata={"hnsw:space": "cosine"}
        )


class ManifestStore:
    """Manages index build manifest and file hash change detection."""

    def __init__(self, manifest_path: str = "data/index_manifest.json"):
        self.manifest_path = Path(manifest_path)
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)

    def load_manifest(self) -> IndexManifest:
        """Load manifest from disk or return a blank manifest."""
        if not self.manifest_path.exists():
            return IndexManifest()
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return IndexManifest(**data)
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning("Could not read manifest at %s: %s", self.manifest_path, exc)
            return IndexManifest()

    def save_manifest(self, manifest: IndexManifest) -> None:
        """Save manifest to disk."""
        self.manifest_path.write_text(
            json.dumps(manifest.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )
