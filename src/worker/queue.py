"""Task queue abstraction supporting Redis and in-memory backends (A4, D3)."""

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

import redis

from config.settings import get_settings

logger = logging.getLogger(__name__)


class TaskQueue(ABC):
    """Abstract interface for the IncidentOps task queue."""

    @abstractmethod
    def enqueue(self, run_id: str, payload: dict[str, Any]) -> bool:
        """Enqueue an alert triage run job."""

    @abstractmethod
    def dequeue(self, timeout: int = 0) -> tuple[str, dict[str, Any]] | None:
        """Dequeue the next available run job."""

    @abstractmethod
    def length(self) -> int:
        """Get the current number of enqueued items."""

    @abstractmethod
    def clear(self) -> None:
        """Clear all pending items in the queue."""


class InMemoryTaskQueue(TaskQueue):
    """In-memory task queue for isolated testing and local runs without Redis."""

    def __init__(self) -> None:
        self._queue: list[tuple[str, dict[str, Any]]] = []

    def enqueue(self, run_id: str, payload: dict[str, Any]) -> bool:
        self._queue.append((run_id, payload))
        return True

    def dequeue(self, timeout: int = 0) -> tuple[str, dict[str, Any]] | None:
        if not self._queue:
            return None
        return self._queue.pop(0)

    def length(self) -> int:
        return len(self._queue)

    def clear(self) -> None:
        self._queue.clear()


class RedisTaskQueue(TaskQueue):
    """Production Redis-backed FIFO task queue."""

    def __init__(self, redis_url: str | None = None, queue_name: str | None = None) -> None:
        settings = get_settings()
        self.redis_url = redis_url or settings.REDIS_URL
        self.queue_name = queue_name or settings.REDIS_QUEUE_NAME
        self.client = redis.Redis.from_url(self.redis_url, decode_responses=True)

    def enqueue(self, run_id: str, payload: dict[str, Any]) -> bool:
        data = json.dumps({"run_id": run_id, "payload": payload})
        self.client.rpush(self.queue_name, data)
        return True

    def dequeue(self, timeout: int = 0) -> tuple[str, dict[str, Any]] | None:
        res = self.client.blpop([self.queue_name], timeout=timeout)
        if not res:
            return None
        _, raw_json = res
        parsed = json.loads(raw_json)
        return parsed["run_id"], parsed["payload"]

    def length(self) -> int:
        return int(self.client.llen(self.queue_name))

    def clear(self) -> None:
        self.client.delete(self.queue_name)


_global_queue: TaskQueue | None = None


def get_task_queue() -> TaskQueue:
    """Return the configured task queue instance."""
    global _global_queue
    if _global_queue is None:
        settings = get_settings()
        try:
            # Check if redis is reachable
            rq = RedisTaskQueue(settings.REDIS_URL, settings.REDIS_QUEUE_NAME)
            rq.client.ping()
            _global_queue = rq
        except (redis.RedisError, ConnectionError, OSError) as exc:
            logger.warning("Redis connection failed (%s); falling back to InMemoryTaskQueue", exc)
            _global_queue = InMemoryTaskQueue()
    return _global_queue


def set_task_queue(queue: TaskQueue) -> None:
    """Explicitly set the task queue instance (for testing)."""
    global _global_queue
    _global_queue = queue
