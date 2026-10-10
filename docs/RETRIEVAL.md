# Knowledge Corpus Retrieval & Grounding Strategy (D2, L1)

## 1. Executive Summary

IncidentOps uses a hybrid retrieval architecture combining dense vector embeddings (`all-MiniLM-L6-v2` executed on CPU) and sparse lexical retrieval (BM25) over PostgreSQL 18 official documentation, operational runbooks, and escalation policy. Candidates are merged using **Reciprocal Rank Fusion (RRF)**.

All documents undergo **heading-aware hierarchical chunking** (~250–350 tokens) with prepended breadcrumb paths. Ingestion is fully idempotent and supports selective hash-based re-indexing (`--reindex-changed`), ensuring unchanged documents are never re-embedded.

---

## 2. The Symptom-vs-Cause Inversion in SRE Incident Diagnostics

### 2.1 The Problem
In production database incident management, there is a fundamental vocabulary and semantic mismatch between how incidents are observed versus how root causes and solutions are documented:

```
+------------------------------------+          +--------------------------------------+
|       Observability Symptoms       |          |         PostgreSQL Documentation     |
|   (Alerts, Metrics, On-Call Note)  |          |       & Operational Runbooks         |
+------------------------------------+          +--------------------------------------+
| • "pg_wal directory full"          |          | • "Replication Slots"                |
| • "Disk space critical (92%)"      |  VS      | • "restart_lsn retention"            |
| • "replication_lag_bytes climbing" |          | • "pg_replication_slots.active"      |
| • "Out of disk space on primary"   |          | • "max_slot_wal_keep_size"           |
+------------------------------------+          +--------------------------------------+
```

1. **Vocabulary Divergence:** Alerts report *symptoms* (e.g. disk exhaustion, IO spikes, connection timeouts). Official documentation is organized by *architectural subsystem* (e.g., Chapter 26 "Replication", Chapter 28 "Write-Ahead Logging"). The official documentation for replication slots does not prominently repeat words like "catastrophic disk outage" or "alert triggered".
2. **Failure of Naive Keyword Search (BM25 alone):** Searching purely for `"disk space critical"` will return disk capacity planning or VACUUM documentation, completely bypassing the replication slot section where the actual retention mechanism is described.
3. **Failure of Unanchored Dense Search (Vector alone):** While dense embeddings understand that "disk full" relates to "WAL retention", dense models often lose precision on exact catalog queries and function names (e.g., `pg_drop_replication_slot()`, `pg_replication_slots`, `max_connections`). Furthermore, isolated text fragments lose their context without heading hierarchy.

### 2.2 How Our Strategy Bridges the Inversion

Our architecture resolves the symptom-vs-cause inversion through three complementary mechanisms:

#### Mechanism 1: Hierarchical Heading Paths Prepended to Every Chunk
When a chunk is generated from an operational runbook or PostgreSQL documentation chapter, its full breadcrumb hierarchy is prepended to the chunk content:

```text
[Runbook: PostgreSQL Inactive Replication Slot WAL Accumulation > Root Cause Analysis]

Write-ahead log (WAL) segments are retained on the primary server when a replication
slot is configured, because PostgreSQL guarantees that WAL needed by any existing
replication slot will not be removed before the slot consumes it...
```

Prepending the breadcrumb path `[Runbook > Inactive Replication Slot WAL Accumulation > ...]` injects high-level semantic tokens into both the dense embedding and BM25 index. When an alert queries for "WAL accumulation", the breadcrumb guarantees a direct hit regardless of whether the specific paragraph mentions the word "accumulation".

#### Mechanism 2: Hybrid Retrieval with Reciprocal Rank Fusion (RRF)
- **Dense Embeddings (`all-MiniLM-L6-v2`, CPU):** Captures conceptual and semantic proximity. It understands that an alert mentioning *"disk space running out due to WAL files"* is semantically proximate to runbook explanations of *"retained WAL segments due to lagging replicas"*.
- **Sparse BM25:** Accurately matches exact system identifiers, SQL functions, views, and error strings (e.g., `pg_replication_slots`, `active = false`, `restart_lsn`, `max_slot_wal_keep_size`).
- **Reciprocal Rank Fusion:** Combines ranks from both retrievers using constant $k=60$:
  $$\text{RRF\_Score}(d) = \frac{1}{60 + \text{Rank}_{\text{dense}}(d)} + \frac{1}{60 + \text{Rank}_{\text{sparse}}(d)}$$
  RRF is invariant to arbitrary score scaling differences between cosine similarities and BM25 scores, preventing either dense or sparse retrieval from dominating the outcome.

---

## 3. Chunking Specification

- **Target Size:** 250 to 350 tokens per chunk (~190–270 words).
- **Heading Boundaries:** Chunk splits occur on markdown headings (`#`, `##`, `###`), preserving semantic units.
- **Sub-Chunking with Windowing:** When a single section exceeds 350 tokens, it is split across paragraph and sentence boundaries, retaining the complete breadcrumb header prefix.
- **Deterministic Chunk IDs:** `f"{source_file_stem}_{section_slug}_{chunk_idx}"`.
  *Example:* `wal_replication_slot_accumulation_remediation_steps_0`.

### Chunk Metadata Schema

| Field | Type | Description |
|---|---|---|
| `chunk_id` | `string` | Deterministic unique ID for idempotent upsert. |
| `doc_type` | `string` | Categorical source type: `pg_docs`, `runbook`, or `policy`. |
| `pg_version` | `string` | Indexed corpus version (e.g. `18`). |
| `source_file` | `string` | Path relative to workspace. |
| `section_id` | `string` | Section anchor identifier. |
| `header_path` | `string` | Breadcrumb hierarchy path (e.g. `Runbook > Diagnosis`). |
| `source_hash` | `string` | SHA-256 fingerprint of the source document. |
| `token_count` | `integer` | Estimated token length. |

---

## 4. Ingestion Lifecycle & Selective Re-Indexing

### 4.1 CLI Usage
The ingestion CLI can be triggered via either:
```bash
python -m app.ingest [--reindex-changed] [--force]
# or
python -m src.rag.ingestion [--reindex-changed] [--force]
```

### 4.2 Selective Hash-Based Re-indexing (`--reindex-changed`)
1. On each execution, the pipeline computes the SHA-256 hash of all discovered documents in `data/corpus/`.
2. Hashes are compared against `data/index_manifest.json`.
3. **Unchanged Files:** Skipped immediately without chunking or embedding computation.
4. **Modified or New Files:**
   - Previous chunk IDs associated with the modified file are removed from the Chroma collection.
   - New chunks are generated, embedded via `all-MiniLM-L6-v2`, and upserted into Chroma by deterministic ID.
   - The BM25 index is updated and re-persisted to `data/bm25_chunks.json`.
   - The index manifest is updated with build duration and throughput metrics.

---

## 5. Telemetry & Observability Exposure

Ingestion build statistics are recorded in `data/index_manifest.json` and exposed on the API:

- **`GET /health`:** Reports corpus index status, indexed PostgreSQL version, total chunk count, build duration, and throughput.
- **`GET /metrics`:** Exposes Prometheus gauges:
  - `incidentops_index_chunks_total`
  - `incidentops_index_build_duration_seconds`
  - `incidentops_index_throughput_chunks_per_second`
