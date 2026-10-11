"""Active tools available to the Investigator agent (A2)."""

import logging
import time
from typing import Any

from src.agent.state import AgentState, ToolExecutionTrace
from src.rag.bm25 import BM25Index
from src.rag.retriever import HybridRetriever
from src.rag.store import ChromaStore

logger = logging.getLogger(__name__)


class ToolExecutionError(Exception):
    """Raised when tool execution violates safety or bounded loop limits."""


class AgentToolExecutor:
    """Executes tools on behalf of the Investigator agent with strict bound checking."""

    def __init__(
        self,
        retriever: HybridRetriever | None = None,
        chroma_store: ChromaStore | None = None,
        bm25_index: BM25Index | None = None,
    ):
        self.chroma_store = chroma_store or ChromaStore()
        self.bm25_index = bm25_index or BM25Index()
        self.bm25_index.load()
        self.retriever = retriever or HybridRetriever(
            chroma_store=self.chroma_store,
            bm25_index=self.bm25_index,
            rrf_k=60,
        )

    def check_bounds(self, state: AgentState) -> None:
        """Check max tool calls and wall-clock timeout bounds."""
        elapsed = time.time() - state["start_time"]
        if elapsed > state["wall_clock_timeout_seconds"]:
            raise ToolExecutionError(
                f"Wall-clock timeout exceeded: {elapsed:.2f}s > {state['wall_clock_timeout_seconds']}s"
            )
        if state["tool_call_count"] >= state["max_tool_calls"]:
            raise ToolExecutionError(
                f"Maximum tool calls exceeded: {state['tool_call_count']} >= {state['max_tool_calls']}"
            )

    def corpus_search(
        self,
        state: AgentState,
        query: str,
        filters: dict[str, Any] | None = None,
        top_k: int = 4,
    ) -> list[dict[str, Any]]:
        """Search documentation and runbooks using hybrid dense + sparse retrieval."""
        self.check_bounds(state)
        state["tool_call_count"] += 1

        doc_type_filter = filters.get("doc_type") if filters else None
        results = self.retriever.search(query=query, top_k=top_k, doc_type_filter=doc_type_filter)

        serialized: list[dict[str, Any]] = []
        for r in results:
            hit = {
                "chunk_id": r.chunk_id,
                "section_id": r.metadata.get("section_id", r.chunk_id),
                "header_path": r.metadata.get("header_path", ""),
                "content": r.content,
                "score": r.score,
                "doc_type": r.metadata.get("doc_type", ""),
            }
            serialized.append(hit)
            # Add to state retrieved_passages if not already present
            if not any(p["chunk_id"] == r.chunk_id for p in state["retrieved_passages"]):
                state["retrieved_passages"].append(hit)

        state["tool_traces"].append(
            ToolExecutionTrace(
                tool_name="corpus_search",
                arguments={"query": query, "filters": filters or {}},
                result_summary=f"Found {len(serialized)} hit(s) for '{query}'",
            )
        )
        return serialized

    def get_section(self, state: AgentState, section_id: str) -> dict[str, Any]:
        """Fetch complete text and breadcrumbs for a specific document section ID."""
        self.check_bounds(state)
        state["tool_call_count"] += 1

        clean_id = section_id.strip()

        # Check BM25 chunks first
        chunk = self.bm25_index.chunks.get(clean_id)
        if not chunk:
            # Fuzzy check against section_id field in chunks
            for c in self.bm25_index.chunks.values():
                if c.section_id == clean_id or c.chunk_id == clean_id or clean_id in c.chunk_id:
                    chunk = c
                    break

        if chunk:
            res = {
                "section_id": chunk.section_id,
                "chunk_id": chunk.chunk_id,
                "header_path": chunk.header_path,
                "content": chunk.content,
                "doc_type": chunk.doc_type,
            }
            if not any(p["chunk_id"] == chunk.chunk_id for p in state["retrieved_passages"]):
                state["retrieved_passages"].append(res)

            state["tool_traces"].append(
                ToolExecutionTrace(
                    tool_name="get_section",
                    arguments={"section_id": clean_id},
                    result_summary=f"Resolved section: {chunk.header_path}",
                )
            )
            return res

        state["tool_traces"].append(
            ToolExecutionTrace(
                tool_name="get_section",
                arguments={"section_id": clean_id},
                result_summary=f"Section '{clean_id}' not found",
            )
        )
        return {"error": f"Section '{clean_id}' not found in corpus"}

    def get_alert_field(self, state: AgentState, name: str) -> Any:
        """Inspect a specific field from the input alert payload."""
        self.check_bounds(state)
        state["tool_call_count"] += 1

        field_name = name.strip()
        val = state["alert"].get(field_name, None)

        state["tool_traces"].append(
            ToolExecutionTrace(
                tool_name="get_alert_field",
                arguments={"name": field_name},
                result_summary=f"Retrieved field '{field_name}'",
            )
        )
        return {"field": field_name, "value": val}
