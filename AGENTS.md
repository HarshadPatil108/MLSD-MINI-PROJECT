# AGENTS.md — IncidentOps System Guidelines

## 1. Technology Stack
- **Runtime & Language:** Python 3.11, Docker, Docker Compose
- **API & Serving:** FastAPI (REST + SSE streaming), Pydantic v2
- **Agent Orchestration:** LangGraph (state machine, native `interrupt()`, checkpointer)
- **LLM Gateway:** LiteLLM (Default: local Ollama `qwen2.5:7b`; Fallbacks: Groq, Gemini)
- **Retrieval & RAG:** Qdrant (dense + FastEmbed native sparse BM25), Cross-Encoder (`ms-marco-MiniLM-L-6-v2`) on CPU
- **Safety & Guardrails:** `bashlex` (shell AST allowlist), `sqlglot` (SQL AST validator)
- **Simulation:** In-memory deterministic telemetry & mock SRE environment
- **Frontend Cockpit:** Streamlit (SSE consumer, backend-persisted state)
- **Testing & Eval:** pytest, RAGAS, deterministic retrieval metrics (Recall@k, MRR, nDCG)

## 2. Repository Layout
```
E:\MLSD_MINI\
├── docker-compose.yml          # Multi-container orchestration
├── Dockerfile.backend          # Multi-stage FastAPI backend build
├── Dockerfile.frontend         # Streamlit UI build
├── pyproject.toml              # Dependencies & build configuration
├── config/                     # settings.yaml, scenarios.yaml
├── data/                       # runbooks/, postmortems/, eval_*.json
├── src/
│   ├── api/                    # FastAPI routes, schemas, SSE streams
│   ├── core/                   # Config, LiteLLM gateway, audit logger
│   ├── sim/                    # Deterministic simulated telemetry engine
│   ├── rag/                    # Chunker, Qdrant hybrid client, reranker
│   ├── guardrails/             # Tiered command safety (bashlex/sqlglot)
│   ├── agent/                  # LangGraph workflow, state, tools, HITL
│   └── eval/                   # Retrieval ablation, classification, safety eval
├── ui/                         # Streamlit SRE Cockpit
├── docs/                       # ARCHITECTURE.md, DECISIONS.md, PROGRESS.md
├── .agents/                    # rules/, workflows/
└── tests/                      # Pytest unit and integration test suite
```

## 3. Exact Commands
```bash
# Run full system with Docker
docker compose up --build

# Run backend standalone
uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload

# Run frontend standalone
streamlit run ui/app.py

# Run all tests
pytest tests/ -v

# Run linting and formatting
ruff check .
ruff format .
```

## 4. Code Conventions
- **Pydantic v2 Everywhere:** All API payloads, tool inputs/outputs, and LLM responses must use strict Pydantic schemas.
- **Strict Typing:** All functions must include complete Python type hints (`typing`).
- **No Direct Shell/SQL Execution:** All command execution runs strictly against the simulated telemetry environment.
- **No Direct Provider SDKs:** LLM calls must route through `src.core.llm.LLMGateway`.
- **Absolute Imports:** Import from `src.<module>` (e.g., `from src.core.config import settings`).

## 5. Pointers & Governance
- Architectural specs & ADRs: See [docs/](file:///E:/MLSD_MINI/docs/) (`docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/PROGRESS.md`).
- Operating rules & workflows: See [.agents/](file:///E:/MLSD_MINI/.agents/) (`.agents/rules/`, `.agents/workflows/slice.md`).
- Ask user confirmation before: adding dependencies, modifying architecture, or deleting files.
