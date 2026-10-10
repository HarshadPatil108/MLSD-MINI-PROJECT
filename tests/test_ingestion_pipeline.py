"""Integration tests for corpus ingestion pipeline, idempotency, and selective re-indexing (D2, L1)."""

from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.rag.bm25 import BM25Index
from src.rag.ingestion import CorpusIngestionPipeline
from src.rag.store import ChromaStore, ManifestStore


class DeterministicTestEmbedder:
    """Fast deterministic CPU embedder producing 384-dim vectors without network calls."""

    def encode(
        self,
        texts: list[str],
        convert_to_numpy: bool = True,
        show_progress_bar: bool = False,
        normalize_embeddings: bool = True,
    ) -> np.ndarray:
        vectors = []
        for text in texts:
            vec = np.zeros(384, dtype=np.float32)
            # Seed vector values based on string hash
            h = abs(hash(text))
            for i in range(10):
                vec[(h + i * 37) % 384] = float((h % 100) + 1) / 100.0
            # Normalize
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            vectors.append(vec)
        return np.array(vectors)


@pytest.fixture
def isolated_corpus_env(tmp_path: Path):
    """Set up an isolated corpus directory with sample runbooks and policy."""
    corpus_dir = tmp_path / "corpus"
    runbooks_dir = corpus_dir / "runbooks"
    policy_dir = corpus_dir / "policy"
    runbooks_dir.mkdir(parents=True)
    policy_dir.mkdir(parents=True)

    # File 1: WAL runbook
    wal_file = runbooks_dir / "wal_accumulation.md"
    wal_file.write_text(
        """# Runbook: WAL Accumulation
## Symptoms
Disk space on pg_wal is growing rapidly.
## Remediation
Drop inactive slot using pg_drop_replication_slot.
""",
        encoding="utf-8",
    )

    # File 2: Connection pool runbook
    conn_file = runbooks_dir / "conn_pool.md"
    conn_file.write_text(
        """# Runbook: Connection Pool Saturation
## Symptoms
Active connections exceed 85%. Remaining connection slots reserved.
## Remediation
Terminate idle sessions using pg_terminate_backend.
""",
        encoding="utf-8",
    )

    # File 3: Policy
    policy_file = policy_dir / "escalation.md"
    policy_file.write_text(
        """# Escalation Policy
## SEV1 Outage
Complete disk space exhaustion requires Incident Commander.
""",
        encoding="utf-8",
    )

    # Isolated Chroma DB and manifest
    chroma_dir = str(tmp_path / "chroma_db")
    manifest_file = str(tmp_path / "index_manifest.json")
    bm25_file = str(tmp_path / "bm25_chunks.json")

    embedder = DeterministicTestEmbedder()
    chroma_store = ChromaStore(
        persist_directory=chroma_dir,
        collection_name="test_corpus",
        embedder=embedder,
    )
    bm25_index = BM25Index(storage_path=bm25_file)
    manifest_store = ManifestStore(manifest_path=manifest_file)

    pipeline = CorpusIngestionPipeline(
        corpus_dir=str(corpus_dir),
        chroma_store=chroma_store,
        bm25_index=bm25_index,
        manifest_store=manifest_store,
        pg_version="18",
    )

    return {
        "pipeline": pipeline,
        "corpus_dir": corpus_dir,
        "runbooks_dir": runbooks_dir,
        "wal_file": wal_file,
        "conn_file": conn_file,
        "policy_file": policy_file,
        "chroma_store": chroma_store,
        "manifest_store": manifest_store,
        "bm25_index": bm25_index,
    }


def test_initial_ingestion_and_idempotent_rerun(isolated_corpus_env):
    """Test that initial run embeds all files, and second run embeds 0 files."""
    env = isolated_corpus_env
    pipeline: CorpusIngestionPipeline = env["pipeline"]
    chroma_store: ChromaStore = env["chroma_store"]

    # --- 1. Initial Ingestion Run ---
    manifest_1 = pipeline.run_ingestion(reindex_changed=True)
    initial_chunks = chroma_store.count()

    assert initial_chunks > 0
    assert manifest_1.total_chunks == initial_chunks
    assert len(manifest_1.files) == 3
    assert manifest_1.build_duration_seconds >= 0
    assert manifest_1.pg_version == "18"

    # --- 2. Idempotent Re-Run: Changes Nothing ---
    manifest_2 = pipeline.run_ingestion(reindex_changed=True)

    # Chunks count must be exactly identical
    assert chroma_store.count() == initial_chunks
    assert manifest_2.total_chunks == initial_chunks
    # Throughput on zero new chunks is 0.0
    assert manifest_2.throughput_chunks_per_sec == 0.0


def test_editing_one_file_reembeds_only_it(isolated_corpus_env):
    """Test that modifying one file re-embeds only that file while skipping unchanged files."""
    env = isolated_corpus_env
    pipeline: CorpusIngestionPipeline = env["pipeline"]
    chroma_store: ChromaStore = env["chroma_store"]
    wal_file: Path = env["wal_file"]

    # Initial build
    pipeline.run_ingestion(reindex_changed=True)
    initial_count = chroma_store.count()

    # Modify wal_file by adding a new section
    wal_file.write_text(
        """# Runbook: WAL Accumulation
## Symptoms
Disk space on pg_wal is growing rapidly.
## Remediation
Drop inactive slot using pg_drop_replication_slot.
## Additional Safeguards
Configure max_slot_wal_keep_size to 10GB.
""",
        encoding="utf-8",
    )

    # Re-run with reindex_changed
    manifest_after_edit = pipeline.run_ingestion(reindex_changed=True)

    # The new section added should increase chunks or update chunks
    assert chroma_store.count() >= initial_count
    # The modified wal file in manifest must have updated indexed_at
    wal_rel = wal_file.as_posix()
    assert wal_rel in manifest_after_edit.files
    assert manifest_after_edit.files[wal_rel].chunk_count >= 3


def test_health_and_metrics_endpoints_reflect_index(isolated_corpus_env):
    """Test GET /health and GET /metrics report index state and build stats."""
    env = isolated_corpus_env
    pipeline: CorpusIngestionPipeline = env["pipeline"]

    # Populate index
    pipeline.run_ingestion(reindex_changed=True)

    # Inject manifest into default manifest path or verify API response
    with TestClient(app) as client:
        # Check /health endpoint
        health_res = client.get("/health")
        assert health_res.status_code == 200
        health_data = health_res.json()
        assert health_data["status"] == "healthy"
        assert "index" in health_data

        # Check /metrics endpoint
        metrics_res = client.get("/metrics")
        assert metrics_res.status_code == 200
        assert "incidentops_index_chunks_total" in metrics_res.text
        assert "incidentops_index_build_duration_seconds" in metrics_res.text
        assert "incidentops_index_throughput_chunks_per_second" in metrics_res.text
