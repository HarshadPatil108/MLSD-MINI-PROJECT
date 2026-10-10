"""Data contracts and schemas for corpus chunking, metadata, and retrieval."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

DocType = Literal["pg_docs", "runbook", "policy"]


class DocumentChunk(BaseModel):
    """Hierarchical document chunk with header breadcrumbs and provenance metadata."""

    chunk_id: str = Field(..., description="Deterministic unique identifier for the chunk.")
    doc_type: DocType = Field(..., description="Corpus classification category.")
    pg_version: str = Field(default="18", description="Target PostgreSQL major/dot version.")
    source_file: str = Field(..., description="Relative file path of the source document.")
    section_id: str = Field(
        ..., description="Section slug or locator (e.g. wal_slots#remediation)."
    )
    header_path: str = Field(..., description="Breadcrumb hierarchy path of headings.")
    content: str = Field(..., description="Chunk text prefixed with breadcrumbs [header_path].")
    raw_content: str = Field(..., description="Underlying section text without breadcrumbs.")
    source_hash: str = Field(..., description="SHA-256 hash of the originating source file.")
    token_count: int = Field(..., description="Estimated token count of the chunk.")


class FileManifestEntry(BaseModel):
    """State tracking entry for an individual ingested document."""

    source_file: str = Field(...)
    doc_type: DocType = Field(...)
    source_hash: str = Field(...)
    chunk_count: int = Field(...)
    chunk_ids: list[str] = Field(default_factory=list)
    indexed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class IndexManifest(BaseModel):
    """Manifest recording the state of the Chroma and BM25 index."""

    last_indexed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    pg_version: str = Field(default="18")
    total_chunks: int = Field(default=0)
    build_duration_seconds: float = Field(default=0.0)
    throughput_chunks_per_sec: float = Field(default=0.0)
    files: dict[str, FileManifestEntry] = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    """Standardized retrieval hit returned by dense, sparse, or hybrid search."""

    chunk_id: str = Field(...)
    content: str = Field(...)
    score: float = Field(..., description="Combined RRF or search relevance score.")
    dense_rank: int | None = Field(default=None, description="Rank from vector retrieval.")
    sparse_rank: int | None = Field(default=None, description="Rank from BM25 retrieval.")
    metadata: dict[str, Any] = Field(default_factory=dict)
