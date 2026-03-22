from __future__ import annotations

from quart import Blueprint, current_app, jsonify, request

from server.ai.queue import AIJob
from server.ai.router import route_for_specialist, select_specialist
from server.ai.tasks.broadcast_task import run_broadcast_task
from server.ai.tasks.chat_task import run_chat_task
from server.ai.tasks.gfs_task import run_gfs_task


def create_ai_blueprint() -> Blueprint:
    bp = Blueprint('ai_bp_v2', __name__, url_prefix='/ai')

    async def _execute(task: str, payload: dict):
        core = current_app.extensions['ai_core']
        if task == 'gfs':
            return await run_gfs_task(core, payload, route='/gfs_ai')
        if task == 'broadcast':
            return await run_broadcast_task(core, payload, route='/broadcast_ai')
        if task == 'lftr':
            return await run_chat_task(core, payload, route='/lftr_ai')
        return await run_chat_task(core, payload, route='/ai')

    @bp.get('/health')
    async def health():
        memory = await current_app.extensions['ai_memory'].snapshot()
        queue = current_app.extensions.get('ai_queue')
        return jsonify({'ok': True, 'route': '/ai', 'state': 'ready', 'queue_depth': queue.qsize() if queue else 0, 'memory': memory})

    @bp.post('/evaluate')
    async def evaluate():
        payload = await request.get_json(silent=True) or {}
        task = select_specialist(request.path, payload)
        result = await _execute(task, payload)
        await current_app.extensions['ai_memory'].touch(route='/ai', task=task, message=str(payload.get('query') or payload.get('note') or ''))
        return jsonify(result)

    @bp.post('/dispatch')
    async def dispatch():
        payload = await request.get_json(silent=True) or {}
        task = select_specialist(request.path, payload)
        route = route_for_specialist(task)
        job = AIJob(task=task, route=route, payload=payload)
        await current_app.extensions['ai_queue'].put(job)
        return jsonify({'ok': True, 'route': '/ai', 'task': task, 'state': 'queued', 'job_id': job.job_id, 'queue_depth': current_app.extensions['ai_queue'].qsize()})

    return bp
