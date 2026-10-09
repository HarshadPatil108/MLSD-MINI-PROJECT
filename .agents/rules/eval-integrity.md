# Rule: Evaluation Integrity & Scientific Rigor

1. **Verifiable Metrics Only:** No metric, table score, or latency figure may be placed in `README.md` or project reports unless a committed script in `src/eval/` generated it and logged artifacts.
2. **Explicit Labeling:** All synthetic datasets (alerts, telemetry, post-mortems) must be clearly and explicitly labeled as **synthetic data**.
3. **Deterministic Retrieval Benchmarks:** Retrieval metrics (Recall@k, MRR, nDCG) must be evaluated against versioned, hand-curated `(query, ground_truth_chunk_id)` pairs stored in `data/`.
4. **Reproducible LLM Evaluation:** Any LLM-as-a-judge evaluations must pin the judge model version, enforce `temperature=0.0`, cache responses to minimize variability, and report variance across runs.
5. **Ablation Transparency:** The retrieval ablation table must report real measured outputs across all four configurations (BM25 only, Dense only, Hybrid RRF, Hybrid + Cross-Encoder).
