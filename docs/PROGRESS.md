# IncidentOps — Project Progress & Milestone Tracker

## Current Status: Step 1 Complete (Project Memory Bootstrapped)

---

### Vertical Slice Roadmap

| Slice # | Slice Description | Target Scope | Tests Passing | Status |
| :---: | :--- | :--- | :---: | :---: |
| **0** | **Project Memory & Governance** | `AGENTS.md`, `.agents/rules/`, `.agents/workflows/`, `docs/` | N/A | **COMPLETED** |
| **1** | **Packaging & Container Foundation** | `pyproject.toml`, `.env.example`, `docker-compose.yml`, Dockerfiles | TBD | Pending |
| **2** | **Simulated SRE Telemetry Environment** | 8–10 deterministic scenarios, logs, metrics, deploy history | TBD | Pending |
| **3** | **Tiered Command Safety Classifier** | `bashlex` + `sqlglot` AST allowlist (READ_ONLY, MUTATING, FORBIDDEN) | TBD | Pending |
| **4** | **Hierarchical Chunker & Runbook Ingestion** | Header breadcrumbs, parent ID tracking, SHA256 idempotent indexing | TBD | Pending |
| **5** | **Native Qdrant Hybrid RAG & Reranker** | Dense + FastEmbed sparse, server-side RRF, Cross-Encoder reranker | TBD | Pending |
| **6** | **LiteLLM Gateway & Triage Classifier** | Centralized gateway, Pydantic schemas, P1–P4 severity classifier | TBD | Pending |
| **7** | **LangGraph Incident Commander & HITL** | Linear state graph, capped tool loop, native `interrupt()` checkpointer | TBD | Pending |
| **8** | **FastAPI Gateway & SSE Streaming** | REST endpoints, SSE token streaming, audit logging | TBD | Pending |
| **9** | **Streamlit Incident Cockpit UI** | Live replay, thought chain stream, HITL approval button | TBD | Pending |
| **10** | **Comprehensive Evaluation & Ablation Suite** | Retrieval Recall/MRR/nDCG ablation, Severity F1, Adversarial safety | TBD | Pending |

---

### Recent Activity Log
- **2026-10-09:** Completed **Step 1 (Project Memory Bootstrap)**:
  - Created [AGENTS.md](file:///E:/MLSD_MINI/AGENTS.md) (<100 lines).
  - Created [.agents/rules/safety.md](file:///E:/MLSD_MINI/.agents/rules/safety.md), [.agents/rules/llm-gateway.md](file:///E:/MLSD_MINI/.agents/rules/llm-gateway.md), [.agents/rules/eval-integrity.md](file:///E:/MLSD_MINI/.agents/rules/eval-integrity.md).
  - Created [.agents/workflows/slice.md](file:///E:/MLSD_MINI/.agents/workflows/slice.md).
  - Created [docs/DECISIONS.md](file:///E:/MLSD_MINI/docs/DECISIONS.md) and initialized [docs/PROGRESS.md](file:///E:/MLSD_MINI/docs/PROGRESS.md).
