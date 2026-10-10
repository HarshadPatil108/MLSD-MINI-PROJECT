"""Parsers for PostgreSQL documentation (PDF/Markdown), runbooks, and policies."""

import hashlib
from pathlib import Path
from typing import ClassVar

from pypdf import PdfReader

from src.rag.chunker import HierarchicalChunker
from src.rag.schemas import DocType, DocumentChunk


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 hex digest of a file for change detection."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    return sha.hexdigest()


class MarkdownParser:
    """Parser for Markdown runbooks, policies, and documentation."""

    def __init__(self, chunker: HierarchicalChunker | None = None):
        self.chunker = chunker or HierarchicalChunker()

    def parse_file(
        self,
        file_path: Path,
        doc_type: DocType,
        pg_version: str = "18",
    ) -> list[DocumentChunk]:
        """Parse a markdown file into DocumentChunks with breadcrumbs."""
        source_hash = compute_file_hash(file_path)
        content = file_path.read_text(encoding="utf-8")
        rel_path = file_path.as_posix()

        return self.chunker.chunk_markdown(
            markdown_text=content,
            source_file=rel_path,
            doc_type=doc_type,
            source_hash=source_hash,
            pg_version=pg_version,
        )


class PdfDocParser:
    """Parser for PostgreSQL PDF documentation focusing on Monitoring, WAL, and Replication chapters."""

    # Target chapters and sections from PostgreSQL documentation
    TARGET_CHAPTERS: ClassVar[list[str]] = [
        "Replication Slots",
        "Monitoring Database Activity",
        "Write-Ahead Logging",
        "Explicit Locking",
    ]

    def __init__(self, chunker: HierarchicalChunker | None = None):
        self.chunker = chunker or HierarchicalChunker()

    def parse_pdf(
        self,
        pdf_path: Path,
        pg_version: str = "18",
        max_pages_per_chapter: int = 4,
    ) -> list[DocumentChunk]:
        """Extract relevant sections from PDF and chunk by headings."""
        source_hash = compute_file_hash(pdf_path)
        rel_path = pdf_path.as_posix()

        reader = PdfReader(str(pdf_path))
        num_pages = len(reader.pages)

        # Scan outline for target chapters if available
        target_page_ranges: list[tuple[str, int, int]] = []
        try:
            outline = reader.outline
            if outline:
                # Helper to traverse outline
                flat_outline: list[tuple[str, int]] = []

                def traverse(items: list):
                    for item in items:
                        if isinstance(item, list):
                            traverse(item)
                        elif hasattr(item, "title") and hasattr(item, "page"):
                            title = str(item.title)
                            try:
                                page_num = reader.get_destination_page_number(item)
                                flat_outline.append((title, page_num))
                            except (ValueError, KeyError, AttributeError):
                                pass

                traverse(outline)

                for idx, (title, page_start) in enumerate(flat_outline):
                    if any(target.lower() in title.lower() for target in self.TARGET_CHAPTERS):
                        clean_title = title.replace("\xa0", " ").strip()
                        next_page = (
                            flat_outline[idx + 1][1]
                            if idx + 1 < len(flat_outline)
                            else page_start + 4
                        )
                        # Cap range to max 4 pages per target section
                        end_page = min(page_start + 4, max(page_start + 1, next_page), num_pages)
                        target_page_ranges.append((clean_title, page_start, end_page))
        except (ValueError, KeyError, AttributeError, OSError):
            target_page_ranges = []

        # If outline was found and has targets, extract those pages
        if target_page_ranges:
            markdown_parts: list[str] = []
            for title, start_p, end_p in target_page_ranges:
                markdown_parts.append(f"# PostgreSQL Documentation: {title}\n")
                for p in range(start_p, end_p):
                    text = reader.pages[p].extract_text()
                    if text and text.strip():
                        markdown_parts.append(f"## {title} (Page {p + 1})\n\n{text.strip()}\n")
            combined_md = "\n".join(markdown_parts)
        else:
            # Fallback: Sample first 15 pages or text search
            markdown_parts = [f"# PostgreSQL {pg_version} Core Documentation\n"]
            limit = min(num_pages, 20)
            for p in range(limit):
                text = reader.pages[p].extract_text()
                if text and text.strip():
                    markdown_parts.append(f"## Section {p + 1}\n\n{text.strip()}\n")
            combined_md = "\n".join(markdown_parts)

        return self.chunker.chunk_markdown(
            markdown_text=combined_md,
            source_file=rel_path,
            doc_type="pg_docs",
            source_hash=source_hash,
            pg_version=pg_version,
        )
