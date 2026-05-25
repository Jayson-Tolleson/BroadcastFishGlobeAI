from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AIMemoryState:
    last_route: str = ''
    last_task: str = ''
    counters: dict[str, int] = field(default_factory=dict)
    recent_messages: deque[str] = field(default_factory=lambda: deque(maxlen=20))


class AIMemory:
    """In-process shared AI memory scaffold."""

    def __init__(self) -> None:
        self._state = AIMemoryState()
        self._lock = asyncio.Lock()

    async def touch(self, *, route: str, task: str, message: str = '') -> AIMemoryState:
        async with self._lock:
            self._state.last_route = route
            self._state.last_task = task
            self._state.counters[task] = self._state.counters.get(task, 0) + 1
            if message:
                self._state.recent_messages.append(str(message)[:300])
            return self._state

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            return {
                'last_route': self._state.last_route,
                'last_task': self._state.last_task,
                'counters': dict(self._state.counters),
                'recent_messages': list(self._state.recent_messages),
            }
