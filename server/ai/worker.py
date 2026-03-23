from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

from .core import AICore
from .queue import AIJob, AIQueue
from .tasks.broadcast_task import run_broadcast_task
from .tasks.chat_task import run_chat_task
from .tasks.gfs_task import run_gfs_task

log = logging.getLogger('server.ai.worker')


class AIWorker:
    """Starter async worker loop for queued AI jobs."""

    def __init__(self, core: AICore, queue: AIQueue) -> None:
        self.core = core
        self.queue = queue
        self._running = False

    async def _dispatch(self, job: AIJob) -> dict:
        if job.task == 'gfs':
            return await run_gfs_task(self.core, job.payload, route=job.route or '/gfs_ai')
        if job.task == 'broadcast':
            return await run_broadcast_task(self.core, job.payload, route=job.route or '/broadcast_ai')
        return await run_chat_task(self.core, job.payload, route=job.route or '/ai')

    async def run_forever(self) -> None:
        self._running = True
        log.info('ai worker started')
        while self._running:
            job = await self.queue.get()
            try:
                result = await self._dispatch(job)
                log.debug('ai worker processed job_id=%s task=%s score=%s', job.job_id, job.task, result.get('score'))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning('ai worker job failed job_id=%s task=%s err=%s', job.job_id, job.task, exc)
            finally:
                self.queue.task_done()

    def stop(self) -> None:
        self._running = False
