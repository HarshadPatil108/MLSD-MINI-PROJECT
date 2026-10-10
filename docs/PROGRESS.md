# IncidentOps — Project Progress & Milestone Tracker

## Current Status: Planning & Specification Approved (Step 1 Memory Aligned to ASSIGNMENT.pdf)

---

### Prioritized Vertical Slice Roadmap

#### Tier 1: MUST Slices (Foundational Core — Minimum Viable Demonstration)

| Slice # | Slice Title | Requirements Covered | Scope & Key Deliverables | Tests Passing | Status |
| :---: | :--- | :--- | :--- | :---: | :---: |
| **1** | **Ingestion Contract & Quarantine** | **F1, F2, D1, D4** | Pydantic data contract, range, categorical & cross-field validation, quarantine storage for rejected requests, `.env.example`. | 27 / 27 (100%) | **Completed** |
| **2** | **Corpus Ingestion & Chroma Vector Store** | **D2, L1, F4** | PostgreSQL 18 PDF/markdown parser, 3 custom runbooks, escalation policy, hierarchical section chunker with breadcrumbs & section IDs, CPU `all-MiniLM-L6-v2` embeddings, idempotent Chroma upsert by ID, freshness metrics. | 37 / 37 (100%) | **Completed** |
| **3** | **Multi-Agent Core & Tools** | **F3, A1, A2** | LangGraph 2-agent topology: Triage Agent (extracts entities, candidate cause classes) -> typed hand-off -> Investigator Agent. Tools: `corpus_search`, `get_section`, `get_alert_field`. Bounded loops (steps, tool calls, wall-clock time). | TBD | Pending |
| **4** | **Citation Verifier & Escalation Engine** | **F5, F6, F7, A3** | Mandatory Verifier: checks every citation resolves to retrieved text. Categorical cause classification, severity assignment, and routing (`self-serve runbook`, `page-secondary`, `incident-commander`). Deterministic escalation on ambiguous support (F7, Section 4.1 scenario). | TBD | Pending |
| **5** | **Async API & Redis Worker Queue** | **A4, D3** | FastAPI asynchronous endpoints: `POST /runs` (returns `run_id`), `GET /runs/{id}`, `GET /quarantine`. Redis-backed task queue with background worker. Docker Compose 4-service topology (`api`, `worker`, `redis`, `chroma`) with dependencies and health checks. | TBD | Pending |
| **6** | **Streamlit Web Client UI** | **A8** | Web client submitting alerts and notes, polling run status, displaying routed recommendations with verified citations, or escalation path. | TBD | Pending |

#### Tier 2: NEXT Slices (Reliability, Guardrails & LLMOps)

| Slice # | Slice Title | Requirements Covered | Scope & Key Deliverables | Tests Passing | Status |
| :---: | :--- | :--- | :--- | :---: | :---: |
| **7** | **Guardrails & Injection Defense** | **L4** | Prompt-injection detection on all free-text fields (`on_call_note`), input/output toxicity checks, output authorization filter (no unauthorized determinations or execution commands). | TBD | Pending |
| **8** | **Timeouts & Circuit Breaker** | **A5** | Per-call timeouts, bounded exponential backoff retries, circuit breaker on LLM provider, graceful degradation fallback to safe escalation. | TBD | Pending |
| **9** | **20-Scenario Evaluation Suite** | **L3** | Fixed 20-incident test set (including Section 4.1 replication slot case); evaluates groundedness, context relevance, faithfulness, hallucination rate using TruLens/equivalent. Baseline vs deliberate change before-and-after report. | TBD | Pending |
| **10** | **Observability & Correlation Tracing** | **D5, F8** | Correlation IDs across API and agent steps, OpenTelemetry exported to Jaeger, Prometheus `/metrics`, Grafana dashboard (p50/p95 latency, error rates, container resource usage). | TBD | Pending |
| **11** | **Declared SLO & Locust Load Testing** | **D6** | Declared p95 SLO target. Realistic LLM stub service returning canned responses. Locust load test measuring p50/p95, RPS, and concurrency breakpoint. | TBD | Pending |

#### Tier 3: LATER Slices (Optimization, Scaling & Governance)

| Slice # | Slice Title | Requirements Covered | Scope & Key Deliverables | Tests Passing | Status |
| :---: | :--- | :--- | :--- | :---: | :---: |
| **12** | **Prompt Versioning & Comparison** | **L2** | Prompt versioning artifacts; compare 2 prompt variants on the evaluation set and report metrics. | TBD | Pending |
| **13** | **Cost & Token Attribution** | **L5** | Per-step and per-run prompt/completion token and cost tracking; report cost per 100 runs and top cost driver. | TBD | Pending |
| **14** | **Worker Scaling & Bottleneck Analysis** | **A7** | Benchmark `docker compose up --scale worker=3` against the Locust stub; measure throughput/p95 gains and identify bottlenecks. | TBD | Pending |
| **15** | **Caching & Rate Limiting** | **D7** | Caching of embeddings and run results; per-client rate limiting to safeguard LLM budgets. | TBD | Pending |
| **16** | **User Feedback & Quality Tracking** | **L6** | Endpoint for feedback (satisfactory/unsatisfactory + reason); automated quality scoring of sample live runs over time. | TBD | Pending |
| **17** | **Dashboard Agent Analytics** | **A6** | Dashboard tracking per-agent success rate, tool calls per run, step latencies, retry rate, and container uptime. | TBD | Pending |
| **18** | **Failure Runbooks & Incident Log** | **D8** | Runbooks for top 2 failure modes (symptom, confirmation, recovery) and genuine development incident log entry. | TBD | Pending |

---

### Activity Log
- **2026-10-09:** Completed baseline project memory bootstrap.
- **2026-10-09:** Aligned all architecture and memory specifications to authoritative `docs/ASSIGNMENT.pdf`:
  - Rewrote [`docs/ARCHITECTURE.md`](file:///E:/MLSD_MINI/docs/ARCHITECTURE.md) to reflect pure advisory multi-agent architecture (PostgreSQL, Chroma, Redis worker, 4+ Docker services).
  - Updated [`AGENTS.md`](file:///E:/MLSD_MINI/AGENTS.md) (<100 lines).
  - Replaced `.agents/rules/safety.md` with [`.agents/rules/guardrails.md`](file:///E:/MLSD_MINI/.agents/rules/guardrails.md).
  - Updated [`.agents/rules/llm-gateway.md`](file:///E:/MLSD_MINI/.agents/rules/llm-gateway.md).
  - Rewrote [`docs/DECISIONS.md`](file:///E:/MLSD_MINI/docs/DECISIONS.md) (superseded ADR-001 through ADR-006, added active ADR-007 through ADR-013).
  - Updated [`docs/PROGRESS.md`](file:///E:/MLSD_MINI/docs/PROGRESS.md) with prioritized 18-slice roadmap (MUST, NEXT, LATER).
- **2026-10-10:** Completed **Slice 1: Ingestion Contract & Quarantine** (F1, F2, D1, D4):
  - Created strict Pydantic v2 [`AlertRequest`](file:///E:/MLSD_MINI/src/api/schemas.py) model enforcing types, metric ranges, non-future timestamps, and PG version matching indexed corpus (PostgreSQL 18).
  - Implemented SQLite quarantine repository [`QuarantineStore`](file:///E:/MLSD_MINI/src/api/quarantine.py) with field-level diagnostic persistence and pagination query endpoints.
  - Implemented [`src/api/main.py`](file:///E:/MLSD_MINI/src/api/main.py) with validation exception interception returning HTTP 422 with quarantine IDs, and decoupled [`TaskQueue`](file:///E:/MLSD_MINI/src/worker/queue.py).
  - Published [`docs/DATA_CONTRACT.md`](file:///E:/MLSD_MINI/docs/DATA_CONTRACT.md) and [`docs/openapi.json`](file:///E:/MLSD_MINI/docs/openapi.json).
  - Implemented 27 comprehensive tests in [`tests/`](file:///E:/MLSD_MINI/tests/) verifying valid enqueue vs quarantine isolation without enqueue (100% pass rate, Ruff formatted and verified).
- **2026-10-10:** Completed **Slice 2: Corpus Ingestion & Chroma Vector Store** (D2, L1, F4):
  - Implemented heading-aware [`HierarchicalChunker`](file:///E:/MLSD_MINI/src/rag/chunker.py) (~250-350 tokens) prepending `[Header > Path]` breadcrumbs to all chunks.
  - Authored 3 operational runbooks under [`data/corpus/runbooks/`](file:///E:/MLSD_MINI/data/corpus/runbooks/) and escalation policy in [`data/corpus/policy/escalation_policy.md`](file:///E:/MLSD_MINI/data/corpus/policy/escalation_policy.md).
  - Implemented [`PdfDocParser`](file:///E:/MLSD_MINI/src/rag/parsers.py) extracting target PostgreSQL 18 documentation chapters (Replication Slots, Monitoring, WAL).
  - Built [`ChromaStore`](file:///E:/MLSD_MINI/src/rag/store.py) with CPU `all-MiniLM-L6-v2` embeddings and deterministic ID upsert.
  - Implemented [`BM25Index`](file:///E:/MLSD_MINI/src/rag/bm25.py) and [`HybridRetriever`](file:///E:/MLSD_MINI/src/rag/retriever.py) merging dense and sparse hits via Reciprocal Rank Fusion ($k=60$).
  - Built ingestion CLI [`app/ingest.py`](file:///E:/MLSD_MINI/app/ingest.py) (`python -m app.ingest [--reindex-changed]`) with SHA-256 hash tracking and selective re-indexing (0.06s idempotent rerun).
  - Exposed index build time, chunk count, and throughput on `/health` and Prometheus `/metrics`.
  - Published [`docs/RETRIEVAL.md`](file:///E:/MLSD_MINI/docs/RETRIEVAL.md) addressing the symptom-vs-cause inversion.
  - Verified 37 unit and integration tests in [`tests/`](file:///E:/MLSD_MINI/tests/) with 100% pass rate and ruff compliance.
