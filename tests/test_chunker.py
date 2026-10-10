"""Unit tests for heading-aware hierarchical chunker (D2, L1)."""

from src.rag.chunker import HierarchicalChunker, estimate_tokens, slugify


def test_slugify():
    """Test slugification of headings and section names."""
    assert slugify("Replication Slots & Standby") == "replication_slots_standby"
    assert slugify("### Step 1: Check Inactive") == "step_1_check_inactive"
    assert slugify("") == "section"


def test_estimate_tokens():
    """Test token estimation."""
    assert estimate_tokens("") == 0
    assert estimate_tokens("hello world") == 2
    assert estimate_tokens(" ".join(["word"] * 100)) == 130


def test_hierarchical_chunker_breadcrumbs_and_bounds():
    """Test that headings create breadcrumbs prepended to each chunk."""
    markdown_doc = """# Runbook: Replication Lag
## Symptoms and Metrics
Disk space on pg_wal volume is filling rapidly. Check replication lag bytes.
## Root Cause Analysis
### Replication Slot Inactivity
A logical replication slot is inactive. PostgreSQL keeps WAL files until all slots consume them.
### Remediation Steps
Drop the slot using pg_drop_replication_slot.
"""
    chunker = HierarchicalChunker(target_min_tokens=20, target_max_tokens=350)
    chunks = chunker.chunk_markdown(
        markdown_text=markdown_doc,
        source_file="data/corpus/runbooks/test_lag.md",
        doc_type="runbook",
        source_hash="mock_hash_123",
        pg_version="18",
    )

    assert len(chunks) >= 3

    # Verify first section has correct breadcrumbs
    c0 = chunks[0]
    assert c0.header_path == "Runbook: Replication Lag > Symptoms and Metrics"
    assert c0.content.startswith("[Runbook: Replication Lag > Symptoms and Metrics]\n\n")
    assert "Disk space on pg_wal volume" in c0.content
    assert c0.doc_type == "runbook"
    assert c0.pg_version == "18"
    assert c0.source_hash == "mock_hash_123"

    # Verify sub-heading breadcrumb
    c1 = chunks[1]
    assert (
        c1.header_path
        == "Runbook: Replication Lag > Root Cause Analysis > Replication Slot Inactivity"
    )
    assert c1.content.startswith(
        "[Runbook: Replication Lag > Root Cause Analysis > Replication Slot Inactivity]\n\n"
    )

    # Verify chunk IDs are deterministic
    for c in chunks:
        assert c.chunk_id.startswith("test_lag_")
        assert c.token_count > 0


def test_hierarchical_chunker_large_section_splitting():
    """Test that sections exceeding target_max_tokens are split into windows preserving the header path."""
    long_paragraph = (
        "PostgreSQL write-ahead logging ensures durability by recording changes before writing to disk. "
        * 30
    )
    markdown_doc = f"""# WAL Architecture
## Deep Dive
{long_paragraph}
"""
    chunker = HierarchicalChunker(target_min_tokens=50, target_max_tokens=100)
    chunks = chunker.chunk_markdown(
        markdown_text=markdown_doc,
        source_file="data/corpus/pg_docs/wal.md",
        doc_type="pg_docs",
        source_hash="hash_wal_001",
    )

    # Should be split into multiple sub-chunks
    assert len(chunks) > 1
    for c in chunks:
        assert c.content.startswith("[WAL Architecture > Deep Dive]\n\n")
        assert c.header_path == "WAL Architecture > Deep Dive"
