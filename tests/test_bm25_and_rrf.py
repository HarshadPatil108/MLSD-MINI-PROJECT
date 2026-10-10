"""Unit and integration tests for BM25 sparse index and Hybrid RRF Retriever (D2, L1)."""

from unittest.mock import MagicMock

from src.rag.bm25 import BM25Index, tokenize_text
from src.rag.retriever import HybridRetriever
from src.rag.schemas import DocumentChunk


def test_tokenize_text():
    """Test text tokenization for BM25."""
    tokens = tokenize_text("SELECT pg_drop_replication_slot('slot_1');")
    assert "select" in tokens
    assert "pg_drop_replication_slot" in tokens
    assert "slot_1" in tokens


def test_bm25_index_build_and_query(tmp_path):
    """Test BM25 keyword matching and persistence."""
    chunks = [
        DocumentChunk(
            chunk_id="chunk_wal_1",
            doc_type="runbook",
            pg_version="18",
            source_file="runbooks/wal.md",
            section_id="wal#remediation",
            header_path="Runbook > Remediation",
            content="[Runbook > Remediation]\n\nDrop the inactive slot with pg_drop_replication_slot.",
            raw_content="Drop the inactive slot with pg_drop_replication_slot.",
            source_hash="hash1",
            token_count=15,
        ),
        DocumentChunk(
            chunk_id="chunk_conn_1",
            doc_type="runbook",
            pg_version="18",
            source_file="runbooks/conn.md",
            section_id="conn#starvation",
            header_path="Runbook > Starvation",
            content="[Runbook > Starvation]\n\nTerminate idle sessions with pg_terminate_backend.",
            raw_content="Terminate idle sessions with pg_terminate_backend.",
            source_hash="hash2",
            token_count=15,
        ),
        DocumentChunk(
            chunk_id="chunk_policy_1",
            doc_type="policy",
            pg_version="18",
            source_file="policy/escalation.md",
            section_id="policy#sev1",
            header_path="Policy > SEV1",
            content="[Policy > SEV1]\n\nPage Incident Commander for complete disk exhaustion.",
            raw_content="Page Incident Commander for complete disk exhaustion.",
            source_hash="hash3",
            token_count=15,
        ),
    ]

    index_path = str(tmp_path / "bm25_test.json")
    bm25 = BM25Index(storage_path=index_path)
    bm25.build_index(chunks)
    assert bm25.count() == 3

    # Query for replication slot keyword
    hits = bm25.query_sparse("pg_drop_replication_slot")
    assert len(hits) >= 1
    assert hits[0][0] == "chunk_wal_1"

    # Query with doc_type filter
    policy_hits = bm25.query_sparse("exhaustion", doc_type_filter="policy")
    assert len(policy_hits) == 1
    assert policy_hits[0][0] == "chunk_policy_1"

    # Test load from persisted JSON
    loaded_bm25 = BM25Index(storage_path=index_path)
    assert loaded_bm25.load() is True
    assert loaded_bm25.count() == 3
    loaded_hits = loaded_bm25.query_sparse("pg_drop_replication_slot")
    assert len(loaded_hits) >= 1
    assert loaded_hits[0][0] == "chunk_wal_1"


def test_hybrid_retriever_rrf_merging(tmp_path):
    """Test Reciprocal Rank Fusion correctly combines and ranks dense and sparse hits."""
    # Mock Chroma store
    mock_chroma = MagicMock()
    # Dense results: chunk_wal_1 at rank 1, chunk_conn_1 at rank 2
    mock_chroma.query_dense.return_value = [
        ("chunk_wal_1", 0.92, "[WAL]\n\nWAL accumulation content", {"doc_type": "runbook"}),
        ("chunk_conn_1", 0.65, "[Conn]\n\nConnection content", {"doc_type": "runbook"}),
    ]

    # BM25 index with real chunks
    bm25 = BM25Index(storage_path=str(tmp_path / "bm25_rrf.json"))
    bm25.chunks = {
        "chunk_wal_1": DocumentChunk(
            chunk_id="chunk_wal_1",
            doc_type="runbook",
            pg_version="18",
            source_file="wal.md",
            section_id="wal#0",
            header_path="WAL",
            content="[WAL]\n\nWAL accumulation content",
            raw_content="WAL accumulation content",
            source_hash="h1",
            token_count=10,
        ),
        "chunk_policy_1": DocumentChunk(
            chunk_id="chunk_policy_1",
            doc_type="policy",
            pg_version="18",
            source_file="policy.md",
            section_id="policy#0",
            header_path="Policy",
            content="[Policy]\n\nPolicy content",
            raw_content="Policy content",
            source_hash="h2",
            token_count=10,
        ),
    }
    bm25.chunk_ids = ["chunk_wal_1", "chunk_policy_1"]
    # Mock BM25 return
    bm25.query_sparse = MagicMock(
        return_value=[
            ("chunk_wal_1", 4.5, "[WAL]\n\nWAL accumulation content", {"doc_type": "runbook"}),
            ("chunk_policy_1", 2.1, "[Policy]\n\nPolicy content", {"doc_type": "policy"}),
        ]
    )

    retriever = HybridRetriever(chroma_store=mock_chroma, bm25_index=bm25, rrf_k=60)
    results = retriever.search("disk full WAL replication lag", top_k=3)

    assert len(results) >= 1
    # chunk_wal_1 was rank 1 in both dense and sparse, so it must be top ranked by RRF
    assert results[0].chunk_id == "chunk_wal_1"
    assert results[0].dense_rank == 1
    assert results[0].sparse_rank == 1
    # RRF score = 1/(60+1) + 1/(60+1) = 2/61 ~= 0.032787
    assert results[0].score > 0.03
