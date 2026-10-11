# IncidentOps — Project Progress & Milestone Tracker

## Current Status: Planning & Specification Approved (Step 1 Memory Aligned to ASSIGNMENT.pdf)

---

### Prioritized Vertical Slice Roadmap

#### Tier 1: MUST Slices (Foundational Core — Minimum Viable Demonstration)

| Slice # | Slice Title | Requirements Covered | Scope & Key Deliverables | Tests Passing | Status |
| :---: | :--- | :--- | :--- | :---: | :---: |
| **1** | **Ingestion Contract & Quarantine** | **F1, F2, D1, D4** | Pydantic data contract, range, categorical & cross-field validation, quarantine storage for rejected requests, `.env.example`. | 27 / 27 (100%) | **Completed** |
| **2** | **Corpus Ingestion & Chroma Vector Store** | **D2, L1, F4** | PostgreSQL 18 PDF/markdown parser, 3 custom runbooks, escalation policy, hierarchical section chunker with breadcrumbs & section IDs, CPU `all-MiniLM-L6-v2` embeddings, idempotent Chroma upsert by ID, freshness metrics. | 37 / 37 (100%) | **Completed** |
| **3** | **Multi-Agent Core & Tools** | **F3, A1, A2** | LangGraph 2-agent topology: Triage Agent (extracts entities, candidate cause classes) -> typed hand-off -> Investigator Agent. Tools: `corpus_search`, `get_section`, `get_alert_field`. Bounded loops (steps, tool calls, wall-clock time). | 43 / 43 (100%) | **Completed** |
| **4** | **Citation Verifier & Escalation Engine** | **F5, F6, F7, A3** | Mandatory Verifier: checks every citation resolves to retrieved text. Categorical cause classification, severity assignment, and routing (`self-serve runbook`, `page-secondary`, `incident-commander`). Deterministic escalation on ambiguous support (F7, Section 4.1 scenario). | 52 / 52 (100%) | **Completed** |
| **5** | **Async API & Redis Worker Queue** | **A4, D3** | FastAPI asynchronous endpoints: `POST /runs` (returns `run_id`), `GET /runs/{id}`, `GET /quarantine`. Redis-backed task queue with background worker. Docker Compose 4-service topology (`api`, `worker`, `redis`, `chroma`) with dependencies and health checks. | TBD | Pending |
| **6** | **Streamlit Web Client UI** | **A8** | Web client submitting alerts and notes, polling run status, displaying routed recommendations with verified citations, or escalation path. | TBD | Pending |

#### Tier 2: NEXT Slices (Reliability, Guardrails & LLMOps)

| Slice # | Slice Title | Requirements Covered | Scope & Key Deliverables | Tests Passing | Status |
| :---: | :--- | :--- | :--- | :---: | :---: |
| **7** | **Guardrails & Injection Defense** | **L4** | Prompt-injection detection on all free-text fields (`on_call_note`), input/output toxicity checks, output authorization filter (no unauthorized determinations or execution commands). | TBD | Pending |
| **8** | **Timeouts & Circuit Breaker** | **A5** | Per-call timeouts, bounded exponential backoff retries, circuit breaker on LLM provider, graceful degradation fallback to safe escalation. | TBD | Pending |
| **9** | **20-Scenario Evaluation Suite** | **L3** | Fixed benchmark suite (`data/eval/scenarios.jsonl`, 10 active synthetic scenarios, target 20) with scientific evaluation CLI `app.eval.run` measuring cause-class accuracy, route accuracy, escalation precision/recall, and citation-resolves rate. | 55 / 55 (100%) | **Milestone 1 Completed (10/20)** |
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
- **2026-10-10:** Completed **Slice 3: Multi-Agent Core & Tools** (F3, A1, A2):
  - Designed typed state models [`AgentState`](file:///E:/MLSD_MINI/src/agent/state.py), [`TriageHandOff`](file:///E:/MLSD_MINI/src/agent/state.py), and [`InvestigationOutput`](file:///E:/MLSD_MINI/src/agent/state.py).
  - Built LLM Gateway [`LiteLLMGateway`](file:///E:/MLSD_MINI/src/gateway/client.py) with structured Pydantic outputs, prompt versioning tracking (`triage-v1.0.0`, `investigator-v1.0.0`), and SQLite response caching.
  - Implemented Triage Agent [`TriageAgent`](file:///E:/MLSD_MINI/src/agent/triage.py) classifying cause classes and entities.
  - Implemented Investigator Agent [`InvestigatorAgent`](file:///E:/MLSD_MINI/src/agent/investigator.py) and tools [`AgentToolExecutor`](file:///E:/MLSD_MINI/src/agent/tools.py) (`corpus_search`, `get_section`, `get_alert_field`) with bounded step/tool call counts and wall-clock timeout safety.
  - Implemented multi-hop reasoning loop: search -> read -> modifying provision check -> derived search -> grounded citation synthesis.
  - Built LangGraph pipeline [`create_incident_graph`](file:///E:/MLSD_MINI/src/agent/graph.py) with resilient fallback routing to page secondary with SEV2 on timeout or error.
  - Published [`docs/TOPOLOGY.md`](file:///E:/MLSD_MINI/docs/TOPOLOGY.md) documenting agent graph topology, transitions, and fallback paths.
  - Added 6 dedicated unit and acceptance tests in [`tests/test_agents.py`](file:///E:/MLSD_MINI/tests/test_agents.py) verifying Section 4.1 scenario reaches replication-slot cause with grounded citations (43/43 tests passing across suite).
- **2026-10-11:** Completed **Slice 4: Citation Verifier & Escalation Engine** (F5, F6, F7, A3):
  - Extended typed state contracts in [`src/agent/state.py`](file:///E:/MLSD_MINI/src/agent/state.py) with [`VerificationResult`](file:///E:/MLSD_MINI/src/agent/state.py), `verified: bool`, `escalation_reason: str | None`, and `verification_retry_count: int`.
  - Built [`CitationVerifier`](file:///E:/MLSD_MINI/src/agent/verifier.py) enforcing exact and passage-level citation resolution to text retrieved during the run, verifying claim support, detecting out-of-corpus alerts, and catching multi-cause ambiguity (F7).
  - Implemented alternate retrieval strategy re-search in [`InvestigatorAgent`](file:///E:/MLSD_MINI/src/agent/investigator.py) (`re_search_with_alternate_strategy`) utilizing runbook filtering and targeted keyword queries upon initial citation verification failure.
  - Extended LangGraph pipeline in [`src/agent/graph.py`](file:///E:/MLSD_MINI/src/agent/graph.py) with `verifier`, `research` (re-search retry loop capped at 1), and `escalate` (deterministic safe human escalation to `page-secondary` or `incident-commander` with stated reasons).
  - Enforced fundamental invariant: Never return an unverified answer to on-call engineers.
  - Authored 9 comprehensive tests in [`tests/test_verifier.py`](file:///E:/MLSD_MINI/tests/test_verifier.py) verifying: (a) Section 4.1 scenario passes verification with grounded citations, (b) out-of-corpus alerts escalate to human with stated reasons, (c) forced bad citations are caught and trigger re-search / escalation, and (d) multi-cause ambiguity triggers deterministic escalation (52/52 tests passing across full suite, 100% pass rate, Ruff checked and formatted).
- **2026-10-11:** Completed **Synthetic Evaluation Suite & Architecture Review Milestone** (L3, eval-integrity.md, Review 1):
  - Created [`data/eval/scenarios.jsonl`](file:///E:/MLSD_MINI/data/eval/scenarios.jsonl) containing 10 benchmark scenarios (all labeled synthetic): Section 4.1 replication slot case, 2 out-of-corpus cases (Kafka, Redis), 1 ambiguous multi-cause case, 2 prompt-injection cases, and 4 standard runbook incidents.
  - Built defensive [`PromptInjectionGuardrail`](file:///E:/MLSD_MINI/src/guardrails/injection.py) in `src/guardrails/injection.py` intercepting adversarial instructions before LLM tool loops and routing safely to `page-secondary`.
  - Built scientific evaluation CLI [`app/eval/run.py`](file:///E:/MLSD_MINI/app/eval/run.py) (`python -m app.eval.run`) and runner [`ScenarioEvaluator`](file:///E:/MLSD_MINI/src/eval/runner.py) reporting 100% cause-class accuracy (5/5), 100% route accuracy (10/10), 100% escalation precision/recall, and 100% citation resolution rate.
  - Authored comprehensive architectural milestone report [`docs/REVIEW1.md`](file:///E:/MLSD_MINI/docs/REVIEW1.md) detailing corpus and PG 18 selection, exact Section 4.1 passages and section IDs, test values, deployment boundary architecture diagram (mermaid), agent topology, declared p95 SLO placeholder, and priority roadmap.
  - Implemented unit tests in [`tests/test_eval_cli.py`](file:///E:/MLSD_MINI/tests/test_eval_cli.py) with 55/55 tests passing across the suite (100% pass rate, Ruff checked and formatted).


