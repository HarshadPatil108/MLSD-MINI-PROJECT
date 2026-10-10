# Architecture Decision Records (ADRs)

## Superseded Decisions (Historical Reference)

### ADR-001: Local Ollama Default Gateway
- **Status:** SUPERSEDED by ADR-013 per `docs/ASSIGNMENT.pdf`
- **Original Context:** System defaulted to local host Ollama `qwen2.5:7b`.
- **Reason for Superseding:** `ASSIGNMENT.pdf` mandates free-tier cloud models via LiteLLM injected purely via environment variables, with zero credentials, endpoints, or model identifiers committed to the repository (D4).

---

### ADR-002: Tiered Command Safety Classifier using `bashlex` and `sqlglot`
- **Status:** SUPERSEDED by ADR-007 per `docs/ASSIGNMENT.pdf`
- **Original Context:** Allowed automated and HITL execution of shell/SQL commands against simulated systems.
- **Reason for Superseding:** `ASSIGNMENT.pdf` Section 2 states: *"The system never executes a remediation. It proposes a cause class and steps with supporting evidence. The on-call engineer decides."* Remediation execution is completely eliminated.

---

### ADR-003: Deterministic Simulated Telemetry Environment
- **Status:** SUPERSEDED by ADR-007 per `docs/ASSIGNMENT.pdf`
- **Original Context:** 8–10 multi-service simulated telemetry scenarios with mock metrics and logs.
- **Reason for Superseding:** Scope narrowed strictly to PostgreSQL documentation, 3 failure runbooks, and 1 escalation policy. No simulated telemetry service.

---

### ADR-004: Native Qdrant Hybrid RAG with Cross-Encoder Reranking
- **Status:** SUPERSEDED by ADR-009 per `docs/ASSIGNMENT.pdf`
- **Original Context:** Qdrant container with FastEmbed sparse BM25 and cross-encoder reranker.
- **Reason for Superseding:** `ASSIGNMENT.pdf` Requirement L1 specifies Chroma (or FAISS) with ID-based upsert so re-embedding does not rebuild the entire index.

---

### ADR-005: Linear LangGraph Workflow with Native HITL Interrupt
- **Status:** SUPERSEDED by ADR-008 per `docs/ASSIGNMENT.pdf`
- **Original Context:** Single-agent linear graph with HITL approval gate for command execution.
- **Reason for Superseding:** Requirements A1 and A2 require at least two distinct agents (Triage $\rightarrow$ Investigator) with a defined hand-off, retrieval as an active tool, and a mandatory Verifier step (A3).

---

### ADR-006: Initial Retrieval Ablation Suite
- **Status:** SUPERSEDED by ADR-009 per `docs/ASSIGNMENT.pdf`
- **Original Context:** Standalone Qdrant RRF ablation table.
- **Reason for Superseding:** Evaluation aligns to L3 requirements (TruLens, groundedness, context relevance, faithfulness, hallucination rate across 20 fixed PostgreSQL incident scenarios).

---

## Active Decisions (Conforming to `docs/ASSIGNMENT.pdf`)

### ADR-007: Pure Advisory SRE Assistant & Removal of Command Execution
- **Status:** Accepted
- **Context:** The system must advise on-call engineers under high cognitive load without introducing risks of automated action execution.
- **Decision:** The system strictly outputs cause classification, verified first-response steps, citations, and routing targets (`self-serve runbook`, `page-secondary`, `incident-commander`). All execution capabilities and command classifiers are completely removed.
- **Consequences:** Eliminates command injection risk; focuses evaluation on diagnostic grounding and citation fidelity.

---

### ADR-008: Multi-Agent Architecture (Triage -> Investigator) with Mandatory Verifier
- **Status:** Accepted
- **Context:** Complex incidents (e.g. section 4.1 replication slot WAL retention) require multi-hop reasoning where symptoms do not match documentation keywords directly.
- **Decision:** Implement a multi-agent topology in LangGraph with:
  1. **Triage Agent:** Analyzes symptoms, extracts entities, hypothesizes candidate cause classes (`saturation`, `contention`, `configuration`, `dependency failure`, `data-volume`), and passes a typed `TriageHandOff`.
  2. **Investigator Agent:** Iteratively searches documentation using tools (`corpus_search`, `get_section`, `get_alert_field`) across modifying provisions.
  3. **Mandatory Verifier:** Formally verifies that all proposed guidance and citations resolve to retrieved text, triggering escalation (F7) on ambiguous or unsupported claims.
- **Consequences:** Satisfies A1, A2, A3, F3, F5, F7.

---

### ADR-009: Chroma Vector Store with ID-Based Upsert & CPU Embeddings
- **Status:** Accepted
- **Context:** Large documentation sets (PostgreSQL chapters) must be indexed efficiently without rebuilding the index on minor runbook edits.
- **Decision:** Deploy Chroma as a dedicated service under Docker Compose. Embed using CPU `sentence-transformers/all-MiniLM-L6-v2`. Use deterministic section IDs (`doc_id#section_id`) for idempotent upserts.
- **Consequences:** Fulfills L1, D2. Low memory footprint on CPU, fast upserts.

---

### ADR-010: Asynchronous Request Pipeline via Redis Task Queue
- **Status:** Accepted
- **Context:** Multi-agent reasoning and multi-hop retrieval take tens of seconds, which would cause HTTP timeouts and tie up web workers if handled synchronously.
- **Decision:** Decouple ingestion from execution. `POST /runs` validates inputs and pushes a job to a Redis task queue, immediately returning a `run_id`. A dedicated `worker` container processes the run. Callers poll `GET /runs/{id}` for status.
- **Consequences:** Satisfies A4 and D3. Enables independent horizontal scaling (`docker compose up --scale worker=3`).

---

### ADR-011: Strict Boundary Validation & Quarantine Storage
- **Status:** Accepted
- **Context:** Malformed or toxic payloads must never consume expensive LLM tokens or trigger worker crashes.
- **Decision:** Enforce a published Pydantic data contract at the FastAPI gateway. Run type, range, categorical, and cross-field checks. Quarantined records with field-level errors are stored in a dedicated quarantine store and never initiate agent runs.
- **Consequences:** Satisfies F1, F2, D1. Protects agent resources.

---

### ADR-012: Multi-Tier Guardrails (Prompt-Injection, Toxicity, Output Authorization)
- **Status:** Accepted
- **Context:** Alerts and on-call notes are untrusted text that may contain malicious instructions designed to alter routing or hijack tools.
- **Decision:** Implement guardrails on input (`on_call_note` prompt-injection and toxicity detection), context (treating tool outputs strictly as data), and output (authorization filter preventing unapproved determinations or commands).
- **Consequences:** Satisfies L4. Secures agentic tool loops.

---

### ADR-013: Cloud Free-Tier LiteLLM Gateway & Strict Secret Isolation
- **Status:** Accepted
- **Context:** The system must run on free-tier LLM providers without committing private credentials, API keys, or endpoints.
- **Decision:** Centralize all model calls behind a LiteLLM gateway with runtime configuration injected via environment variables. Include `.env.example` with zero hardcoded secrets in git. Implement timeouts, retries with exponential backoff, and a circuit breaker.
- **Consequences:** Satisfies D4, A5, and Section 12. Portable across Groq, Gemini, and local models.
