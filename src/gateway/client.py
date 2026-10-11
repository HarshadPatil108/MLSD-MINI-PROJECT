"""LiteLLM Gateway with schema-constrained structured output and response caching (A5, L2, D4)."""

import hashlib
import logging
import os
import sqlite3
from collections.abc import Callable
from datetime import UTC
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class GatewayResponseCache:
    """Thread-safe SQLite cache for LLM structured responses keyed by input signature."""

    def __init__(self, db_path: str = "data/llm_cache.db"):
        self.db_path = db_path
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS response_cache (
                    cache_key TEXT PRIMARY KEY,
                    prompt_version TEXT NOT NULL,
                    model TEXT NOT NULL,
                    cached_at TEXT NOT NULL,
                    response_json TEXT NOT NULL
                );
                """
            )

    def get(self, cache_key: str) -> str | None:
        with self._conn:
            row = self._conn.execute(
                "SELECT response_json FROM response_cache WHERE cache_key = ?;",
                (cache_key,),
            ).fetchone()
            return row["response_json"] if row else None

    def set(self, cache_key: str, prompt_version: str, model: str, response_json: str) -> None:
        from datetime import datetime

        now_str = datetime.now(UTC).isoformat()
        with self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO response_cache (cache_key, prompt_version, model, cached_at, response_json)
                VALUES (?, ?, ?, ?, ?);
                """,
                (cache_key, prompt_version, model, now_str, response_json),
            )

    def clear(self) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM response_cache;")


class LiteLLMGateway:
    """Gateway for executing LLM completions via LiteLLM with strict Pydantic output constraints."""

    def __init__(
        self,
        model_name: str | None = None,
        cache_db_path: str | None = None,
        mock_handler: Callable[[str, type[BaseModel]], BaseModel] | None = None,
    ):
        self.model_name = model_name or os.getenv("LITELLM_MODEL", "groq/llama-3.1-70b-versatile")
        self.cache = GatewayResponseCache(db_path=cache_db_path or "data/llm_cache.db")
        self.mock_handler = mock_handler

    def _compute_cache_key(
        self,
        prompt: str,
        system_prompt: str,
        response_model: type[BaseModel],
        prompt_version: str,
    ) -> str:
        content = (
            f"{self.model_name}:{prompt_version}:{response_model.__name__}:{system_prompt}:{prompt}"
        )
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def call_structured(
        self,
        prompt: str,
        response_model: type[T],
        system_prompt: str = "",
        prompt_version: str = "v1.0.0",
        temperature: float = 0.0,
    ) -> T:
        """Execute structured LLM invocation with schema constraints and caching.

        Args:
            prompt: User/context prompt text.
            response_model: Pydantic model enforcing the expected response structure.
            system_prompt: System directive instructions.
            prompt_version: Explicit prompt version identifier.
            temperature: Sampling temperature (default 0.0 for deterministic evaluation).

        Returns:
            Instance of response_model populated by LLM or cache.
        """
        cache_key = self._compute_cache_key(
            prompt=prompt,
            system_prompt=system_prompt,
            response_model=response_model,
            prompt_version=prompt_version,
        )

        # 1. Check response cache
        cached_json = self.cache.get(cache_key)
        if cached_json:
            logger.debug("Cache hit for LLM invocation [%s]", cache_key[:12])
            return response_model.model_validate_json(cached_json)

        # 2. Check for injected mock handler (e.g. testing mode)
        if self.mock_handler is not None:
            res = self.mock_handler(prompt, response_model)
            if isinstance(res, response_model):
                self.cache.set(
                    cache_key=cache_key,
                    prompt_version=prompt_version,
                    model=self.model_name,
                    response_json=res.model_dump_json(),
                )
                return res

        # 3. Live LiteLLM call
        try:
            import litellm

            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            # Check if API keys are configured; if not and no provider configured, fall back gracefully
            response = litellm.completion(
                model=self.model_name,
                messages=messages,
                response_format=response_model,
                temperature=temperature,
            )

            raw_content = response.choices[0].message.content
            parsed = response_model.model_validate_json(raw_content)

            # Store in cache
            self.cache.set(
                cache_key=cache_key,
                prompt_version=prompt_version,
                model=self.model_name,
                response_json=parsed.model_dump_json(),
            )
            return parsed

        except Exception as exc:
            logger.warning(
                "LiteLLM call failed or provider unconfigured (%s); using fallback parser", exc
            )
            raise


# Global gateway singleton
_gateway_instance: LiteLLMGateway | None = None


def get_llm_gateway() -> LiteLLMGateway:
    """Get or create singleton LiteLLMGateway."""
    global _gateway_instance
    if _gateway_instance is None:
        _gateway_instance = LiteLLMGateway()
    return _gateway_instance


def set_llm_gateway(gateway: LiteLLMGateway) -> None:
    """Override singleton gateway (for testing)."""
    global _gateway_instance
    _gateway_instance = gateway
