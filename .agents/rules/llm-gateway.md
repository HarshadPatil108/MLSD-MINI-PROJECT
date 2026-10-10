# Rule: LLM Gateway, Vector Storage & Secret Isolation

1. **Centralized LiteLLM Gateway:** All LLM invocations must route through `src.gateway.client`. Direct imports or calls to provider SDKs (`openai`, `google-generativeai`, `anthropic`) elsewhere in the codebase are strictly forbidden.
2. **Cloud Free-Tier by Environment:** The model provider (e.g., Groq, Gemini) must be configured exclusively via environment variables (`LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`).
3. **Zero Secrets in Repository (D4):** No credentials, private endpoints, or model identifiers may be hardcoded anywhere in the codebase. All configuration must be injected at runtime and documented in `.env.example`.
4. **Chroma Vector Store with CPU Embeddings (L1):** Document indexing uses Chroma with CPU-based `sentence-transformers/all-MiniLM-L6-v2`. Document and section IDs must be preserved so re-embedding updates records in-place without rebuilding the entire index.
5. **Schema-Constrained Decoding:** Every model call must enforce a Pydantic schema with structured JSON output and an automated repair fallback on validation failure.
6. **Bounded Context & Reliability (A5):** Context windows must stay strictly within **8,000 tokens**. Every call must declare explicit timeouts, bounded exponential backoff retries, and a circuit breaker that trips to a safe fallback on provider outage.
