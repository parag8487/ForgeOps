# SPDX-License-Identifier: FSL-1.1-ALv2
"""Redis Tasks Extension state machine (Design §12.4).

Implements the MCP Tasks Extension lifecycle with Redis-backed persistence.
Idempotent cancellation: terminal state → no error, returns existing state.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class TaskState(StrEnum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL: frozenset[TaskState] = frozenset(
    {
        TaskState.COMPLETED,
        TaskState.FAILED,
        TaskState.CANCELLED,
    }
)

ALLOWED: dict[TaskState, frozenset[TaskState]] = {
    TaskState.SUBMITTED: frozenset({TaskState.WORKING, TaskState.CANCELLED, TaskState.FAILED}),
    TaskState.WORKING: frozenset(
        {
            TaskState.INPUT_REQUIRED,
            TaskState.COMPLETED,
            TaskState.FAILED,
            TaskState.CANCELLED,
        }
    ),
    TaskState.INPUT_REQUIRED: frozenset({TaskState.WORKING, TaskState.CANCELLED, TaskState.FAILED}),
    # Terminal states allow no transitions
    TaskState.COMPLETED: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.CANCELLED: frozenset(),
}


def can_transition(from_state: TaskState, to_state: TaskState) -> bool:
    """Check whether a state transition is allowed."""
    return to_state in ALLOWED.get(from_state, frozenset())


@dataclass
class TaskRecord:
    """A single task's persisted state."""

    task_id: str
    state: TaskState
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_json(self) -> str:
        """Serialize to JSON for Redis storage."""
        d = asdict(self)
        d["state"] = self.state.value
        return json.dumps(d)

    @classmethod
    def from_json(cls, data: str) -> TaskRecord:
        """Deserialize from Redis JSON."""
        d = json.loads(data)
        d["state"] = TaskState(d["state"])
        return cls(**d)


class RedisForTasks(Protocol):
    """Minimal async Redis interface for the task store."""

    async def set(self, name: str, value: str, px: int | None = None) -> Any: ...
    async def get(self, name: str) -> str | None: ...


class RedisTaskStore:
    """Redis-backed task store with state machine enforcement.

    - Idempotent cancellation: cancelling a terminal task returns existing state.
    - Invalid transitions raise ValueError.
    """

    KEY_PREFIX = "mcp:task:"
    DEFAULT_TTL_MS = 86_400_000  # 24 hours

    def __init__(self, redis: RedisForTasks, *, ttl_ms: int | None = None) -> None:
        self._redis = redis
        self._ttl_ms = ttl_ms or self.DEFAULT_TTL_MS

    def _key(self, task_id: str) -> str:
        return f"{self.KEY_PREFIX}{task_id}"

    async def create(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> TaskRecord:
        """Create a new task in SUBMITTED state."""
        now = time.time()
        record = TaskRecord(
            task_id=str(uuid.uuid4()),
            state=TaskState.SUBMITTED,
            tool_name=tool_name,
            arguments=arguments or {},
            created_at=now,
            updated_at=now,
        )
        await self._redis.set(self._key(record.task_id), record.to_json(), px=self._ttl_ms)
        return record

    async def get(self, task_id: str) -> TaskRecord | None:
        """Retrieve a task by ID. Returns None if not found."""
        data = await self._redis.get(self._key(task_id))
        if data is None:
            return None
        return TaskRecord.from_json(data)

    async def update(
        self,
        task_id: str,
        new_state: TaskState,
        *,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> TaskRecord:
        """Transition a task to a new state.

        Raises ValueError if the transition is invalid or the task is not found.
        """
        record = await self.get(task_id)
        if record is None:
            raise ValueError(f"Task {task_id} not found")

        if not can_transition(record.state, new_state):
            raise ValueError(f"Invalid transition: {record.state.value} → {new_state.value}")

        record.state = new_state
        record.updated_at = time.time()
        if result is not None:
            record.result = result
        if error is not None:
            record.error = error

        await self._redis.set(self._key(task_id), record.to_json(), px=self._ttl_ms)
        return record

    async def cancel(self, task_id: str) -> TaskRecord:
        """Cancel a task. Idempotent: terminal state → no error, returns existing state.

        Raises ValueError if the task is not found.
        """
        record = await self.get(task_id)
        if record is None:
            raise ValueError(f"Task {task_id} not found")

        # Idempotent: already in a terminal state → return as-is
        if record.state in TERMINAL:
            return record

        # Transition to cancelled
        record.state = TaskState.CANCELLED
        record.updated_at = time.time()
        await self._redis.set(self._key(task_id), record.to_json(), px=self._ttl_ms)
        return record
