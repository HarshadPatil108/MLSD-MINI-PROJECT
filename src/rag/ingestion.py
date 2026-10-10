"""Corpus Ingestion Orchestrator and CLI for PostgreSQL docs, runbooks, and policies (D2, L1)."""

import argparse
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

from src.rag.bm25 import BM25Index
from src.rag.chunker import HierarchicalChunker
from src.rag.parsers import MarkdownParser, PdfDocParser, compute_file_hash
from src.rag.schemas import DocType, DocumentChunk, FileManifestEntry, IndexManifest
from src.rag.store import ChromaStore, ManifestStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


class CorpusIngestionPipeline:
    """Manages parsing, hierarchical chunking, CPU MiniLM embedding, and selective re-indexing."""

    def __init__(
        self,
        corpus_dir: str = "data/corpus",
        chroma_store: ChromaStore | None = None,
        bm25_index: BM25Index | None = None,
        manifest_store: ManifestStore | None = None,
        pg_version: str = "18",
    ):
        self.corpus_dir = Path(corpus_dir)
        self.chroma_store = chroma_store or ChromaStore()
        self.bm25_index = bm25_index or BM25Index()
        self.manifest_store = manifest_store or ManifestStore()
        self.pg_version = pg_version
        self.chunker = HierarchicalChunker(target_min_tokens=200, target_max_tokens=350)
        self.md_parser = MarkdownParser(chunker=self.chunker)
        self.pdf_parser = PdfDocParser(chunker=self.chunker)

    def scan_source_files(self) -> list[tuple[Path, DocType]]:
        """Discover documentation, runbook, and policy files under corpus_dir."""
        files: list[tuple[Path, DocType]] = []
        if not self.corpus_dir.exists():
            logger.warning("Corpus directory '%s' does not exist.", self.corpus_dir)
            return files

        # 1. Runbooks
        runbooks_dir = self.corpus_dir / "runbooks"
        if runbooks_dir.exists():
            for f in runbooks_dir.glob("*.md"):
                files.append((f, "runbook"))

        # 2. Policy
        policy_dir = self.corpus_dir / "policy"
        if policy_dir.exists():
            for f in policy_dir.glob("*.md"):
                files.append((f, "policy"))

        # 3. PostgreSQL docs (PDF and markdown)
        pg_docs_dir = self.corpus_dir / "pg_docs"
        if pg_docs_dir.exists():
            for f in pg_docs_dir.glob("*.md"):
                files.append((f, "pg_docs"))
            for f in pg_docs_dir.glob("*.pdf"):
                files.append((f, "pg_docs"))

        return sorted(files, key=lambda x: str(x[0]))

    def run_ingestion(
        self,
        reindex_changed: bool = True,
        force: bool = False,
        max_pdf_pages: int | None = 20,
    ) -> IndexManifest:
        """Execute ingestion pipeline.

        Args:
            reindex_changed: If True, skip files whose SHA-256 hash matches the manifest.
            force: If True, re-embed all files unconditionally.
            max_pdf_pages: Limit PDF page extraction for performance.

        Returns:
            Updated IndexManifest.
        """
        start_time = time.perf_counter()
        manifest = (
            self.manifest_store.load_manifest()
            if not force
            else IndexManifest(pg_version=self.pg_version)
        )
        self.bm25_index.load()

        all_sources = self.scan_source_files()
        logger.info("Discovered %d source file(s) in '%s'", len(all_sources), self.corpus_dir)

        files_to_process: list[tuple[Path, DocType, str]] = []  # (path, doc_type, hash)
        skipped_files: list[str] = []

        for file_path, doc_type in all_sources:
            current_hash = compute_file_hash(file_path)
            rel_path = file_path.as_posix()

            if not force and reindex_changed and rel_path in manifest.files:
                cached_entry = manifest.files[rel_path]
                if cached_entry.source_hash == current_hash:
                    skipped_files.append(rel_path)
                    continue

            files_to_process.append((file_path, doc_type, current_hash))

        logger.info(
            "Identified %d file(s) to process (%d skipped as unchanged)",
            len(files_to_process),
            len(skipped_files),
        )

        total_embedded_chunks = 0
        newly_generated_chunks: list[DocumentChunk] = []

        for file_path, doc_type, current_hash in files_to_process:
            rel_path = file_path.as_posix()
            logger.info("Processing [%s]: %s", doc_type, rel_path)

            # If re-indexing an existing file, delete its old chunks from Chroma and BM25
            if rel_path in manifest.files:
                old_entry = manifest.files[rel_path]
                self.chroma_store.delete_chunks(old_entry.chunk_ids)

            # Parse and chunk file
            chunks: list[DocumentChunk] = []
            if file_path.suffix.lower() == ".pdf":
                chunks = self.pdf_parser.parse_pdf(
                    file_path, pg_version=self.pg_version, max_pages_per_chapter=max_pdf_pages or 4
                )
            else:
                chunks = self.md_parser.parse_file(
                    file_path, doc_type=doc_type, pg_version=self.pg_version
                )

            logger.info("Generated %d chunk(s) from %s", len(chunks), rel_path)

            if chunks:
                # Embed and upsert into Chroma
                upserted = self.chroma_store.upsert_chunks(chunks)
                total_embedded_chunks += upserted
                newly_generated_chunks.extend(chunks)

            # Update file manifest entry
            manifest.files[rel_path] = FileManifestEntry(
                source_file=rel_path,
                doc_type=doc_type,
                source_hash=current_hash,
                chunk_count=len(chunks),
                chunk_ids=[c.chunk_id for c in chunks],
                indexed_at=datetime.now(UTC),
            )

        # Update BM25 index with all chunks or new chunks
        if newly_generated_chunks or force:
            # Rebuild BM25 with updated chunks
            all_chunks = self._collect_all_chunks(manifest)
            self.bm25_index.build_index(all_chunks)

        duration = time.perf_counter() - start_time
        total_chunks = self.chroma_store.count()
        throughput = (
            round(total_embedded_chunks / duration, 2)
            if duration > 0 and total_embedded_chunks > 0
            else 0.0
        )

        manifest.last_indexed_at = datetime.now(UTC)
        manifest.pg_version = self.pg_version
        manifest.total_chunks = total_chunks
        manifest.build_duration_seconds = round(duration, 3)
        manifest.throughput_chunks_per_sec = throughput

        self.manifest_store.save_manifest(manifest)

        logger.info(
            "Ingestion complete in %.3fs. Total Chunks: %d. Newly Embedded: %d. Throughput: %.2f chunks/s",
            duration,
            total_chunks,
            total_embedded_chunks,
            throughput,
        )

        return manifest

    def _collect_all_chunks(self, manifest: IndexManifest) -> list[DocumentChunk]:
        """Collect all active chunks across all files in manifest."""
        chunks: list[DocumentChunk] = []
        for file_path_str, entry in manifest.files.items():
            path = Path(file_path_str)
            if not path.exists():
                continue
            if path.suffix.lower() == ".pdf":
                chunks.extend(
                    self.pdf_parser.parse_pdf(
                        path, pg_version=self.pg_version, max_pages_per_chapter=4
                    )
                )
            else:
                chunks.extend(
                    self.md_parser.parse_file(
                        path, doc_type=entry.doc_type, pg_version=self.pg_version
                    )
                )
        return chunks


def main() -> None:
    """CLI entrypoint for corpus ingestion."""
    parser = argparse.ArgumentParser(
        description="IncidentOps Knowledge Corpus Ingestion CLI (D2, L1)"
    )
    parser.add_argument(
        "--reindex-changed",
        action="store_true",
        default=True,
        help="Only re-index files that have changed since last build (default: True).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Force complete re-indexing of all files.",
    )
    parser.add_argument(
        "--corpus-dir",
        type=str,
        default="data/corpus",
        help="Path to corpus directory (default: data/corpus).",
    )
    parser.add_argument(
        "--pg-version",
        type=str,
        default="18",
        help="Target PostgreSQL version (default: 18).",
    )

    args = parser.parse_args()
    pipeline = CorpusIngestionPipeline(corpus_dir=args.corpus_dir, pg_version=args.pg_version)
    pipeline.run_ingestion(reindex_changed=args.reindex_changed, force=args.force)


if __name__ == "__main__":
    main()
