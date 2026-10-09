# Rule: LLM Gateway & Model Interaction

1. **Centralized Gateway:** All LLM invocations must route through the centralized LiteLLM gateway (`src.core.llm.LLMGateway`). Direct imports and calls to provider SDKs (`openai`, `google-generativeai`, `anthropic`) elsewhere in the codebase are strictly forbidden.
2. **Schema-Constrained Outputs:** Every LLM response must be validated against a Pydantic schema with structured JSON output and an automated retry/repair fallback on parsing errors.
3. **Default Model:** The default configured model is local Ollama `qwen2.5:7b` (overridable via `LLM_MODEL` in `.env` to Groq or Gemini free tiers).
4. **Context Budget:** The total prompt and generation context window must stay strictly within **8,000 tokens** to prevent VRAM overflow and token exhaustion.
5. **CPU Inference for Embeddings:** The text embedder (`all-MiniLM-L6-v2` / FastEmbed) and Cross-Encoder reranker (`cross-encoder/ms-marco-MiniLM-L-6-v2`) must execute on CPU to conserve GPU VRAM for the primary LLM.
