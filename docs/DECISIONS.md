# Architecture Decision Records (ADRs)

## ADR-001: Centralized LiteLLM Gateway
- **Status:** Accepted
- **Context:** The system needs to run on free cloud LLMs (Groq, Gemini) during development and switch seamlessly to a local 8GB GPU instance (Ollama `qwen2.5:7b`) for offline testing without changing business logic.
- **Decision:** Route all LLM requests through a centralized LiteLLM gateway with Pydantic structured output validation and automatic schema repair.
- **Consequences:** Eliminates vendor lock-in, unifies retry/fallback handling, and prevents provider SDK sprawl across modules.

---

## ADR-002: Tiered Command Safety Classifier using `bashlex` and `sqlglot`
- **Status:** Accepted
- **Context:** A naive regex or blocklist (`rm -rf`, `DROP TABLE`) is trivially bypassed by shell formatting, flags, and subshells.
- **Decision:** Implement a 3-tier AST allowlist classifier using `bashlex` for shell commands and `sqlglot` for SQL:
  - `READ_ONLY`: Allowlisted inspection commands (auto-run in simulation).
  - `MUTATING`: Allowlisted state-modifying commands (gated behind HITL approval).
  - `FORBIDDEN`: Unparseable syntax, subshells `$(...)`, backticks, pipes to `sh`/`bash`, base64 decoders, destructive verbs (always rejected).
- **Consequences:** Strong execution safety boundary; rejects obfuscated and unparseable commands deterministically.

---

## ADR-003: Deterministic Simulated Telemetry Environment
- **Status:** Accepted
- **Context:** Real execution of production remediation commands is dangerous and makes tests non-deterministic.
- **Decision:** Build an in-memory simulated telemetry service serving canned logs, Prometheus metrics, and deployment history across 8–10 realistic incident scenarios with ground-truth root causes.
- **Consequences:** 100% safe, reproducible, testable, and deterministic evaluation benchmark.

---

## ADR-004: Native Qdrant Hybrid RAG with Cross-Encoder Reranking
- **Status:** Accepted
- **Context:** Naive vector search misses exact keyword errors (e.g., error codes, pod exit statuses), while managing separate in-memory BM25 indexes causes synchronization drift.
- **Decision:** Use Qdrant's native FastEmbed sparse BM25 + dense vector search with server-side Reciprocal Rank Fusion (RRF), followed by a CPU-based `cross-encoder/ms-marco-MiniLM-L-6-v2` reranker filtering top 20 candidates down to top 5.
- **Consequences:** High retrieval precision, zero index drift, fast CPU reranking, and clear ablation evaluation.

---

## ADR-005: Linear LangGraph Workflow with Native HITL Interrupt
- **Status:** Accepted
- **Context:** Agent loops can become unpredictable, and Human-in-the-Loop approval state is lost if the UI reruns or reconnects.
- **Decision:** Use a compact, linear LangGraph state machine with capped tool iterations (max 4 cycles), Pydantic schema validation per node, and native LangGraph `interrupt()` backed by a memory checkpointer.
- **Consequences:** Predictable diagnostic paths, resilient state persistence across Streamlit reruns, and strict token budget enforcement.

---

## ADR-006: Deterministic Retrieval Benchmark & LLM Evaluation Integrity
- **Status:** Accepted
- **Context:** Flaky LLM-as-a-judge scores and ungrounded claims harm project credibility.
- **Decision:** Emphasize deterministic, LLM-free retrieval metrics (Recall@k, MRR, nDCG) on hand-labeled query-chunk pairs, alongside 40–60 gold-labeled synthetic alerts for Severity F1 classification. Any LLM-as-a-judge metric must use pinned models, temperature 0, and caching.
- **Consequences:** Produces a defensible, reproducible ablation table for the project report and resume.
