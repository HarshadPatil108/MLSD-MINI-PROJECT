# Architecture: Production Incident Triage and Runbook Assistant

Status: draft v1. Decisions and their reasons live in `docs/DECISIONS.md`. Progress lives in `docs/PROGRESS.md`.

## 1. Purpose and scope

An SRE assistant that takes an alert, retrieves relevant runbooks and post-mortems, gathers telemetry through tools, proposes a diagnosis and remediation, and gates any mutating action behind human approval.

All infrastructure is **simulated**. Corpus, incidents and labels are **synthetic**. Metrics describe performance on this synthetic data, not on real production systems.

### Non-goals
- No execution of real commands against real systems.
- No multi-tenant auth, no real paging/ticketing integrations.
- No fine-tuning. No multi-agent swarm.

## 2. Topology

| Service | Tech | Where | Notes |
|---|---|---|---|
| `backend` | FastAPI | Docker | triage, RAG search, agent runs, approvals, eval endpoints, SSE trace stream |
| `qdrant` | Qdrant >= 1.10 | Docker | dense + sparse vectors, server-side RRF |
| `frontend` | Streamlit | Docker | thin client; holds no run state |
| `ollama` | Ollama | **Host** | `qwen2.5:7b-instruct` Q4; reached via `host.docker.internal:11434` |

Hardware assumption: 8GB VRAM GPU. LLM on GPU. Embedder and reranker on CPU.
Ollama settings: `num_ctx=8192`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_FLASH_ATTENTION=1`.

```
Streamlit  --HTTP/SSE-->  FastAPI  --> LangGraph agent --> Gateway (LiteLLM) --> Ollama (host)
                             |              |
                             |              +--> Telemetry simulator (in-process)
                             +--> Qdrant (hybrid search)
                             +--> SQLite (run state, checkpoints, audit log)
```

## 3. Repository layout

```
src/
  gateway/        LiteLLM wrapper, schema-constrained calls, retry/repair, response cache
  rag/            ingestion, chunking, embedding, Qdrant client, hybrid query, reranker
  safety/         command parser, tiered classifier, SQL validator, injection fixtures
  telemetry_sim/  scenario loader, simulated tools (logs, metrics, deploys, k8s, disk)
  agent/          LangGraph graph, node functions, Pydantic state and schemas, prompts
  api/            FastAPI routes, SSE streaming, approval endpoints
  eval/           retrieval eval, agent eval, safety eval, optional RAGAS, report generator
frontend/         Streamlit app
data/
  corpus/         runbooks/, postmortems/ (markdown, synthetic)
  scenarios/      one folder per incident: alert.json, telemetry/, ground_truth.json
  eval/           retrieval_pairs.jsonl, alerts_labeled.jsonl, adversarial_commands.jsonl
tests/
docs/
```

## 4. Agent flow

A linear LangGraph with one interrupt. No branching beyond the capped tool loop.

```
classify_severity
      -> retrieve_runbooks
      -> gather_telemetry   (loop, max 4 iterations)
      -> hypothesize
      -> propose_actions
      -> [INTERRUPT: human approval for MUTATING actions]
      -> execute_simulated
      -> verify
      -> summarize
```

Rules:
- Every node returns a Pydantic model. Output is schema-constrained at the gateway.
- Every action passes the safety classifier **before** execution and **before** being shown for approval.
- READ_ONLY actions auto-run. MUTATING actions pause at the interrupt. FORBIDDEN actions are rejected and logged, never shown as approvable.
- State is persisted by the LangGraph checkpointer (SQLite). An approval can arrive after a UI reload.
- Per-run budgets: max LLM calls, max total tokens, max wall-clock seconds. Exceeding any budget ends the run with a partial summary.
- Older tool outputs are summarized before being appended to the scratchpad to stay within the 8k context.

### Context budget (approximate, tokens)
System + schema 800, alert + telemetry 1500, retrieved chunks 1500, scratchpad 2000, output headroom 1000.

## 5. Key schemas

```python
class Alert:        id, service, source, message, fired_at, labels: dict
class Severity:     level: Literal["SEV1","SEV2","SEV3","SEV4"], rationale: str
class Hypothesis:   root_cause: str, confidence: float, evidence: list[EvidenceRef]
class Action:       id, command: str, kind: Literal["shell","sql","api"], rationale: str,
                    tier: Literal["READ_ONLY","MUTATING","FORBIDDEN"] | None
class ToolStep:     thought: str, action: Action        # "JSON action" format, not native function-calling
class ApprovalRecord: action_id, decision, decided_by, decided_at, reason
class AgentState:   alert, severity, retrieved_chunks, telemetry_summary, hypotheses,
                    proposed_actions, approvals, executed, report, budget_used
```

## 6. Safety layer

Tiered classifier. Allowlist first, not blocklist.

| Tier | Behavior | Examples |
|---|---|---|
| `READ_ONLY` | auto-run | `kubectl get`, `kubectl logs`, `kubectl describe`, `df`, `free`, `tail`, `cat` of allowed paths |
| `MUTATING` | human approval required | `kubectl rollout restart`, `systemctl restart`, scale operations |
| `FORBIDDEN` | always rejected | unparseable input, command substitution, pipes to `sh`/`bash`, `rm` variants, `find -delete`, `dd`, `mkfs`, `chmod -R`, anything not in an allowlist |

Implementation notes:
- Shell: parse with `bashlex`. Any parse failure means FORBIDDEN. Validate the binary, subcommand, **and arguments**.
- SQL: parse with `sqlglot`. Only a single `SELECT` statement is READ_ONLY. Everything else is MUTATING or FORBIDDEN by policy.
- Unknown binary or subcommand defaults to FORBIDDEN.
- Tool output is wrapped and labeled as untrusted data in prompts. Instructions found in logs or alerts are never followed.
- Adversarial suite (`data/eval/adversarial_commands.jsonl`) includes flag-splitting (`rm -r -f`), base64 substitution, `find / -delete`, chained commands, unicode lookalikes, and prompt-injection strings embedded in log lines. **A hand-written core set is maintained by the human, not generated by the agent.**
- Audit log (SQLite): every proposed, classified, approved, rejected and executed action with timestamp and run id.

## 7. RAG pipeline

### Ingestion (idempotent, script and endpoint)
1. Load markdown from `data/corpus/`. Hash each file; skip unchanged.
2. Split on headers. Keep the header path as metadata, for example `DB Runbook > Connection Pool > Mitigation`.
3. Target 250-350 tokens per chunk. Prepend the header path to chunk text before embedding.
4. Store metadata: `doc_id`, `doc_type` (runbook | postmortem), `service`, `header_path`, `parent_id`, `source_hash`.
5. Embed dense (`all-MiniLM-L6-v2`, CPU) and sparse (BM25-style via `fastembed`). Upsert into one Qdrant collection with named vectors.

### Retrieval
1. Metadata pre-filter on `service` (from the alert) when available.
2. Qdrant Query API: dense and sparse prefetch, server-side RRF fusion, top 20.
3. Cross-encoder rerank (`ms-marco-MiniLM-L-6-v2`, CPU): top 20 to top 4-5.
4. Optional parent-section expansion for the final chunks.

### Ablation variants (all must be runnable from one script)
`dense` | `bm25` | `hybrid_rrf` | `hybrid_rrf + rerank`

## 8. LLM gateway

- LiteLLM behind a thin wrapper. `LLM_PROVIDER=ollama|groq|gemini`, default `ollama`.
- API: `generate(prompt, schema: type[BaseModel], *, temperature=0, max_tokens) -> BaseModel`.
- Schema passed to Ollama via the `format` parameter (constrained decoding). On validation failure: one repair attempt, then fail the node.
- Retry with backoff for cloud providers. Response cache keyed by hash of (model, prompt, schema, temperature) used in eval for reproducibility.
- No provider SDK imports outside `src/gateway/`.

## 9. Simulated telemetry and scenarios

Each scenario folder contains:
- `alert.json`: the triggering alert
- `telemetry/`: canned logs, metrics series, deploy history, k8s state, disk and connection stats
- `ground_truth.json`: root cause, severity, correct runbook doc ids, correct remediation action(s), forbidden traps

Simulated tools read only from the active scenario. Mutating actions in the simulator change scenario state (for example, "restart" moves the metric series to a recovered state) so `verify` has something to check.

Initial scenarios (target 8-10): DB connection pool exhaustion, bad deploy, disk full, memory leak, certificate expiry, noisy neighbor CPU, DNS failure, queue backlog. At least two include prompt-injection text in logs.

## 10. API surface (backend)

| Route | Purpose |
|---|---|
| `POST /triage` | classify an alert; return severity and rationale |
| `POST /rag/search` | hybrid search with optional filters and variant selector |
| `POST /runs` | start an agent run for an alert or scenario id |
| `GET /runs/{id}/stream` | SSE stream of node events, tool calls, LLM outputs |
| `GET /runs/{id}` | current state and report |
| `POST /runs/{id}/approvals` | approve or reject a pending action |
| `GET /audit` | audit log, filterable by run |
| `POST /eval/run` | trigger an eval suite (background); `GET /eval/results` for output |
| `GET /health` | liveness and dependency checks (Qdrant, Ollama) |

The Streamlit UI holds no run state. It polls or subscribes to SSE and renders from backend state.

## 11. Evaluation plan

Primary metrics (no LLM judge, deterministic):

| Area | Metrics | Data |
|---|---|---|
| Retrieval | Recall@k, MRR, nDCG for each ablation variant | `retrieval_pairs.jsonl` (hand-labeled query to chunk) |
| Severity | accuracy, macro F1 | `alerts_labeled.jsonl` (40-60 synthetic alerts) |
| Agent | root-cause accuracy, correct-tool-call rate, steps-to-diagnosis, latency | scenarios + `ground_truth.json` |
| Safety | unsafe-action block rate, false-block rate on benign set | `adversarial_commands.jsonl` |

Secondary: RAGAS faithfulness and context recall, with a pinned judge model, temperature 0, cached results, small fixed set, variance reported across runs. The judge is named in the README.

Report generator writes `docs/RESULTS.md` from script output. The README may only reference numbers from that file.

Report the agent model separately from the judge model. An optional extra row compares the local 7B against a cloud model.

## 12. Observability

- Structured logging with a run id on every line.
- Langfuse or OpenTelemetry traces for LLM calls and graph nodes (choose one; log in DECISIONS.md).
- Latency and token counts recorded per node.

## 13. CI

GitHub Actions: ruff, pytest (unit and safety adversarial suite), and a small offline eval on fixture data using cached LLM responses. No GPU required in CI.

## 14. Build order (maps to PROGRESS.md slices)

1. Skeleton, Compose, `/health`, tooling
2. Corpus, chunking, ingestion
3. Qdrant hybrid, reranker, retrieval eval and ablation table
4. Gateway with schema-constrained output and cache; local-model smoke test on 20 alerts
5. Command classifier and adversarial suite
6. Telemetry simulator and scenarios
7. LangGraph agent with interrupt and checkpointer
8. Agent and safety eval
9. API streaming, audit log, Streamlit cockpit
10. CI, observability, README with results and Limitations

## 15. Known limitations (to repeat in README)

- Synthetic corpus and incidents; results do not generalize to real systems.
- A 7B local model has limited reasoning and may fail on long or ambiguous telemetry.
- Free-tier or local judge models are noisy for RAGAS metrics.
- The classifier is an allowlist for a small command set, not a complete shell security boundary.

## 16. Open questions

- Langfuse vs OpenTelemetry for tracing.
- Whether to add a React frontend after the Streamlit version works.
- Whether `qwen3:8b` (non-thinking) beats `qwen2.5:7b` on the smoke test enough to switch.
