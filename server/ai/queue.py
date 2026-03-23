from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(slots=True)
class AIJob:
    task: str
    route: str
    payload: dict[str, Any] = field(default_factory=dict)
    job_id: str = field(default_factory=lambda: uuid4().hex)
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))


class AIQueue:
    def __init__(self, maxsize: int = 256) -> None:
        self._q: asyncio.Queue[AIJob] = asyncio.Queue(maxsize=maxsize)

    async def put(self, job: AIJob) -> None:
        await self._q.put(job)

    async def get(self) -> AIJob:
        return await self._q.get()

    def task_done(self) -> None:
        self._q.task_done()

    def qsize(self) -> int:
        return self._q.qsize()


shared_ai_queue = AIQueue(maxsize=256)
