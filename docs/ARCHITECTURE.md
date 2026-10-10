# Architecture: Production Incident Triage and Runbook Assistant

Status: Approved v2 (Supercedes draft v1 per `docs/ASSIGNMENT.pdf`). Decisions live in `docs/DECISIONS.md`. Progress lives in `docs/PROGRESS.md`.

## 1. Purpose and Scope

An advisory multi-agent SRE assistant that accepts an alert payload and on-call note for PostgreSQL incidents, validates and quarantines malformed inputs, retrieves relevant guidance from official PostgreSQL documentation and operational runbooks using tools, determines a cause class and severity, verifies all citations against retrieved text, and routes the incident.

**Core Invariant:** The system **never executes a remediation**. It proposes a cause class and first-response steps with supporting evidence and citations. The on-call engineer decides.

### Non-goals
- No execution of commands against live or simulated production systems.
- No multi-tenant auth or real PagerDuty/Slack webhooks.
- No model fine-tuning; no unconstrained agent swarms.

---

## 2. Service Topology (Docker Compose)

Under requirement D3, the system runs with at least four interdependent services orchestrated via Docker Compose (`docker compose up` from a clean clone):

| Service | Technology | Role & Boundary Justification |
|---|---|---|
| `api` | FastAPI | REST gateway, request validation, quarantine storage, async run submission (`POST /runs`), run status (`GET /runs/{id}`), metrics. |
| `worker` | Python Worker | Background consumer pulling runs from Redis queue. Executes the multi-agent graph (Triage $\rightarrow$ Investigator $\rightarrow$ Verifier). Decoupled for independent scaling (`--scale worker=3`). |
| `redis` | Redis 7 | High-performance task queue broker and run state/status cache. Isolates API latency from agent execution time. |
| `chroma` | Chroma DB | Dedicated vector database supporting ID-based upsert (re-embedding without index rebuild) and metadata filtering. Runs CPU embeddings (`all-MiniLM-L6-v2`). |
| `frontend` | Streamlit | Thin web client (A8). Submits requests, polls run status, and displays recommendations with verified citations and escalation paths. Holds no run state. |

```
[Browser / Streamlit] --HTTP--> [api (FastAPI)]
                                  |
                                  ├──> [Quarantine Store (Rejects)]
                                  │
                                  └──> [redis (Queue & State)]
                                         ▲
                                         │ Dequeues run_id
                                         ▼
                                       [worker (Multi-Agent)]
                                         ├──> LiteLLM (Cloud Free-Tier via Env)
                                         └──> [chroma (Vector DB)]
```

---

## 3. Data Contract & Ingestion Boundary (D1, F1, F2)

Every external interface enforces a strict, published data contract. Validation runs at the ingestion boundary **before any agent starts**.

### Alert Ingestion Contract (`POST /runs`)
```python
class AlertPayload(BaseModel):
    alert_id: str = Field(..., pattern=r"^[A-Za-z0-9_-]{8,64}$")
    timestamp: datetime
    service: str = Field(..., min_length=2, max_length=64)
    pg_version: str = Field(..., pattern=r"^1[4-8](\.[0-9]+)?$")
    metric_name: str = Field(..., min_length=2, max_length=64)
    metric_value: float = Field(..., ge=0.0)
    threshold: float = Field(..., ge=0.0)
    severity_hint: Literal["CRITICAL", "WARNING", "INFO"]
    on_call_note: str = Field(..., min_length=5, max_length=2000)
    tags: dict[str, str] = Field(default_factory=dict)
```

### Validation & Quarantine Policy
- **Boundary Checks:** Type enforcement, numeric ranges (`metric_value >= 0`), categorical checks, timestamp non-future check, and cross-field consistency.
- **Quarantine:** Any rejected request is immediately recorded in quarantine storage with field-level error details. A malformed request **never starts an agent run**.

---

## 4. Corpus & Grounding (Section 3)

The knowledge base is composed strictly of:
1. **PostgreSQL Documentation for One Major Version:** Specifically chapters on monitoring, write-ahead logging (WAL), and replication (sourced from `data/corpus/pg_docs/postgresql-18-A4.pdf`).
2. **Three Custom Runbooks:** Written in consistent markdown format covering common failure modes:
   - Runbook 1: PostgreSQL Unused/Abandoned Replication Slot WAL Accumulation.
   - Runbook 2: Connection Pool Saturation and Backend Starvation.
   - Runbook 3: Lock Contention and Long-Running Transaction Serialization Deadlocks.
3. **Severity & Escalation Policy:** Defining unambiguous rules for severity classification (`SEV1`–`SEV4`) and routing targets (`self-serve runbook`, `page-secondary`, `incident-commander`).

### Chunking & Storage (L1, D2)
- Header-aware hierarchical chunking (250–350 tokens) preserving breadcrumbs and section IDs (`pg18/replication/slots#1`).
- Embeddings: CPU `sentence-transformers/all-MiniLM-L6-v2`.
- Indexed in Chroma with document and section IDs, enabling idempotent upsert without full rebuilds.

---

## 5. Multi-Agent Reasoning Architecture (A1, A2, A3, Section 5)

Reasoning is orchestrated as a multi-agent system in LangGraph with distinct responsibilities, explicit hand-offs, and tool bounds.

```mermaid
flowchart TD
    Q[Redis Task Queue] --> W[Worker Dequeues Run]
    W --> G1[Guardrail: Input Prompt-Injection & Toxicity Check]
    G1 -->|Clean| A1[Agent 1: Triage Agent]
    G1 -->|Flagged| QUAR[Quarantine / Security Abort]

    subgraph Triage ["Agent 1: Triage"]
        A1 -->|Analyze Alert & Extract Entities| Handoff[TriageHandOff Contract]
    end

    Handoff --> A2[Agent 2: Investigator Agent]

    subgraph Investigation ["Agent 2: Investigator (Tool Loop)"]
        A2 <--> T1["tool: corpus_search(query, filters)"]
        A2 <--> T2["tool: get_section(section_id)"]
        A2 <--> T3["tool: get_alert_field(field_name)"]
        A2 -->|Capped: max 5 steps, max 6 tool calls, 45s wall-clock| Hypo[Proposed Diagnosis & Steps]
    end

    Hypo --> A3[Mandatory Verifier Step]

    subgraph Verification ["Verification & Grounding"]
        A3 --> VCheck{Every citation resolves to text & clear single cause?}
        VCheck -->|Verified| G2[Guardrail: Output Authorization Filter]
        VCheck -->|Unverified / Multi-Cause Ambiguity| Escalate[Escalate to Human (F7)]
        VCheck -->|Retry Warranted| A2
    end

    G2 --> Res[Store Final Result in Redis & Return]
```

### Agent 1: Triage Agent
- **Responsibility:** Ingests the validated alert and on-call note. Classifies the symptom into candidate cause classes: `saturation`, `contention`, `configuration`, `dependency failure`, or `data-volume`. Extracts key operational entities (e.g. `pg_version`, `metric_name`, error patterns).
- **Hand-off Contract (`TriageHandOff`):** Passes candidate causes, extracted entities, and initial search queries to the Investigator.

### Agent 2: Investigator Agent (Tool-Calling Agent)
- Retrieval is **a tool the agent chooses to call**, not a fixed pipeline stage.
- **Tools Provided:**
  1. `corpus_search(query: str, doc_type: str = None)`: Semantic search over Chroma.
  2. `get_section(section_id: str)`: Exact retrieval of a full documentation clause or runbook section by ID.
  3. `get_alert_field(field_name: str)`: Inspects raw alert metadata and on-call notes.
- **Multi-Hop Investigation Loop (Section 5):**
  1. Retrieves the provision that appears to apply.
  2. Determines whether modifying provisions exist (e.g., alert notes "disk climbing", storage docs retrieved, but agent identifies WAL retention by replication slots).
  3. Searches again with a query derived from what it has learned.
- **Bounds:** Capped at max 5 steps, max 6 tool calls, and a 45-second wall-clock timeout.

### Mandatory Verifier Step (A3)
- Validates every factual statement in the proposed guidance against the retrieved text.
- **Verification Rule:** Every citation must resolve to actual retrieved text in the run's context.
- **Escalation Trigger (F7):** If citations do not resolve, or if the symptom has equal support across multiple cause classes, or falls outside the corpus, the system **escalates to human** (`route: page-secondary` or `incident-commander`) rather than returning an ungrounded answer.

---

## 6. Guardrails & Security Layer (L4)

Implemented in `src/guardrails/`:
1. **Prompt-Injection Defense:** Sanitizes and detects jailbreaks / override attempts on all free-text fields (`on_call_note`) before reaching the model. Tool output is treated strictly as data.
2. **Toxicity Detection:** Scans both inputs and model outputs for toxic or adversarial phrasing.
3. **Output Authorization Filter:** Verifies that the agent never produces unauthorized determinations or command execution scripts. Enforces categorical outputs (`cause_class`, `severity`, `route`).

---

## 7. LLM Gateway & Reliability (A5, D4, Section 12)

- Routed through `LiteLLM` using free-tier cloud providers (e.g., Groq, Gemini) configured solely through environment variables.
- **Zero Secrets In Repo:** No API keys, endpoints, or model IDs are hardcoded. Documented via `.env.example`.
- **Reliability:** Timeouts on every LLM call, bounded retries with exponential backoff, and a circuit breaker pattern. If the provider fails, the system triggers graceful degradation to a safe escalation response.

---

## 8. Asynchronous API Surface (A4, F8)

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/runs` | Accepts `AlertPayload`, validates, quarantines rejects, enqueues run, returns `{ "run_id": "...", "status": "QUEUED" }`. |
| `GET` | `/runs/{id}` | Returns current status (`QUEUED`, `RUNNING`, `COMPLETED`, `ESCALATED`, `FAILED`) and full `RunResult`. |
| `GET` | `/quarantine` | Lists quarantined alert submissions with field-level rejection reasons. |
| `GET` | `/health` | Liveness and dependency checks (Redis, Chroma, Gateway). |
| `GET` | `/metrics` | Prometheus metrics (request rates, latency p50/p95, agent tool calls, cache hits). |

---

## 9. Evaluation & Observability (L3, D5, D6)

- **Scenario Evaluation (L3):** Fixed benchmark of at least 20 scenarios (including Section 4.1 replication slot disk saturation case) reporting groundedness, context relevance, faithfulness, and hallucination rate using an LLM judge with pinned temperature 0.
- **SLO & Load Testing (D6):** Declared p95 SLO. Load tested with Locust using an LLM stub service returning realistic fixed responses to benchmark queuing and retrieval latency independent of provider rate limits.
- **Observability (D5):** Structured JSON logs with unique `correlation_id` across API and worker. OpenTelemetry traces exported to Jaeger.
