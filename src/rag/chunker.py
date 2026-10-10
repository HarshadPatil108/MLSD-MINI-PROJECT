"""Heading-aware hierarchical document chunker (~250-350 tokens) with breadcrumb prepending."""

import re

from src.rag.schemas import DocType, DocumentChunk


def estimate_tokens(text: str) -> int:
    """Estimate token count based on whitespace and punctuation splits (~1.3 tokens/word)."""
    words = len(text.strip().split())
    if words == 0:
        return 0
    return max(1, int(words * 1.3))


def slugify(text: str) -> str:
    """Generate a clean slug for section IDs."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return slug[:48] if slug else "section"


class HierarchicalChunker:
    """Chunks documents by heading hierarchy, maintaining breadcrumb prefixes and token bounds."""

    def __init__(self, target_min_tokens: int = 200, target_max_tokens: int = 350):
        self.target_min_tokens = target_min_tokens
        self.target_max_tokens = target_max_tokens

    def chunk_markdown(
        self,
        markdown_text: str,
        source_file: str,
        doc_type: DocType,
        source_hash: str,
        pg_version: str = "18",
    ) -> list[DocumentChunk]:
        """Parse markdown, extract heading hierarchy, and yield DocumentChunks.

        Prepends '[Breadcrumb > Path]' to every chunk content.
        """
        lines = markdown_text.splitlines()
        chunks: list[DocumentChunk] = []

        # Current heading stack: list of (level, title)
        heading_stack: list[tuple[int, str]] = []
        current_section_lines: list[str] = []

        def flush_section() -> None:
            nonlocal current_section_lines
            raw_text = "\n".join(current_section_lines).strip()
            current_section_lines = []
            if not raw_text:
                return

            header_path = " > ".join(title for _, title in heading_stack) or "General"
            section_slug = slugify(heading_stack[-1][1]) if heading_stack else "root"
            file_stem = slugify(source_file.split("/")[-1].split("\\")[-1].replace(".md", ""))
            section_id = f"{file_stem}#{section_slug}"

            # Split raw_text into windows of ~250-350 tokens
            sub_chunks = self._split_text_to_token_windows(raw_text)
            for sub_idx, sub_text in enumerate(sub_chunks):
                chunk_id = f"{file_stem}_{section_slug}_{sub_idx}"
                prefixed_content = f"[{header_path}]\n\n{sub_text}"
                token_count = estimate_tokens(prefixed_content)

                chunks.append(
                    DocumentChunk(
                        chunk_id=chunk_id,
                        doc_type=doc_type,
                        pg_version=pg_version,
                        source_file=source_file,
                        section_id=f"{section_id}_{sub_idx}",
                        header_path=header_path,
                        content=prefixed_content,
                        raw_content=sub_text,
                        source_hash=source_hash,
                        token_count=token_count,
                    )
                )

        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")

        for line in lines:
            match = heading_pattern.match(line.strip())
            if match:
                # Heading encountered: flush previous section
                flush_section()
                level = len(match.group(1))
                title = match.group(2).strip()

                # Pop headings of equal or greater level
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, title))
            else:
                current_section_lines.append(line)

        # Flush final section
        flush_section()

        return chunks

    def _split_text_to_token_windows(self, text: str) -> list[str]:
        """Split text exceeding target_max_tokens into balanced windows on paragraph or sentence boundaries."""
        total_tokens = estimate_tokens(text)
        if total_tokens <= self.target_max_tokens:
            return [text]

        # Split by paragraphs first
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        if len(paragraphs) <= 1:
            # Paragraph is too long, split by sentences
            sentences = re.split(r"(?<=[.!?])\s+", text)
            return self._accumulate_items(sentences, delimiter=" ")

        return self._accumulate_items(paragraphs, delimiter="\n\n")

    def _accumulate_items(self, items: list[str], delimiter: str) -> list[str]:
        """Accumulate items until target window is reached."""
        result: list[str] = []
        current_group: list[str] = []
        current_tokens = 0

        for item in items:
            item_tokens = estimate_tokens(item)
            if current_group and (current_tokens + item_tokens) > self.target_max_tokens:
                result.append(delimiter.join(current_group))
                current_group = [item]
                current_tokens = item_tokens
            else:
                current_group.append(item)
                current_tokens += item_tokens

        if current_group:
            result.append(delimiter.join(current_group))

        return result
