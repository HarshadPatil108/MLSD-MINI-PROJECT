# AGENTS.md — IncidentOps System Guidelines

## 1. Technology Stack
- **Runtime & Orchestration:** Python 3.11, Docker, Docker Compose (at least 4 services)
- **API & Task Queue:** FastAPI (async REST), Redis 7 (broker, state & cache), Python background worker
- **Multi-Agent Orchestration:** LangGraph (Triage Agent -> Investigator Agent -> Mandatory Verifier)
- **Vector DB & Retrieval:** Chroma (ID-based upsert, metadata filtering), CPU `sentence-transformers/all-MiniLM-L6-v2`
- **LLM Gateway:** LiteLLM (free-tier cloud models via environment variables; zero credentials in repo)
- **Guardrails:** Prompt-injection defense on free-text inputs, input/output toxicity detection, output authorization filter
- **Observability & Testing:** OpenTelemetry (Jaeger), Prometheus, Grafana, pytest, Locust (with LLM stub)
- **Frontend Client:** Streamlit (thin async polling client)

## 2. Repository Layout
```
E:\MLSD_MINI\
├── docker-compose.yml          # Multi-service setup (api, worker, redis, chroma, frontend)
├── Dockerfile.api              # FastAPI ingestion & management build
├── Dockerfile.worker           # Async agent worker build
├── Dockerfile.frontend         # Streamlit client build
├── pyproject.toml              # Dependencies & build configuration
├── .env.example                # Documented runtime environment template (no secrets in repo)
├── config/                     # Settings and policy definitions
├── data/                       # pg_docs/ (PostgreSQL 18 docs), runbooks/, eval/
├── src/
│   ├── api/                    # Ingestion contract, validation, quarantine, endpoints
│   ├── worker/                 # Redis task queue consumer & run lifecycle manager
│   ├── agent/                  # LangGraph multi-agent graph (Triage, Investigator, Verifier)
│   ├── rag/                    # PDF/Markdown parser, chunker, Chroma store, retrieval tools
│   ├── guardrails/             # Prompt-injection defense, toxicity filter, output authorization
│   ├── gateway/                # LiteLLM client with circuit breaker & timeout handling
│   └── eval/                   # Scenario evaluation suite, TruLens/faithfulness, Locust stubs
├── frontend/                   # Streamlit web UI
├── docs/                       # ARCHITECTURE.md, DECISIONS.md, PROGRESS.md, ASSIGNMENT.pdf
├── .agents/                    # rules/ (guardrails.md, llm-gateway.md, eval-integrity.md), workflows/
└── tests/                      # Pytest unit, integration, and guardrail tests
```

## 3. Exact Commands
```bash
# Run full system (at least 4 containers)
docker compose up --build

# Ingest & index PostgreSQL documentation and runbooks
python -m src.rag.ingestion

# Run all unit and integration tests
pytest tests/ -v

# Run linting and formatting
ruff check .
ruff format .
```

## 4. Code Conventions
- **Pydantic v2 Everywhere:** All external boundaries, tool inputs/outputs, and LLM payloads enforce strict Pydantic models.
- **Strict Typing:** All functions must include complete Python type annotations (`typing`).
- **No Remediation Execution:** System never executes shell or database commands; strictly produces advisory guidance.
- **No Direct Provider SDKs:** All LLM invocations route through `src.gateway.client`.
- **Absolute Imports:** Import from `src.<module>` (e.g., `from src.api.schemas import AlertPayload`).

## 5. Pointers & Governance
- Architectural specs & ADRs: See [docs/](file:///E:/MLSD_MINI/docs/) (`docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/PROGRESS.md`).
- Operating rules & workflows: See [.agents/](file:///E:/MLSD_MINI/.agents/) (`.agents/rules/`, `.agents/workflows/slice.md`).
- Ask user confirmation before: adding dependencies, modifying architecture, or deleting files.
