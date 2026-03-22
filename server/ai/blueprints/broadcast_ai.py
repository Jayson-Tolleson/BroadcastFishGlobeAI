from __future__ import annotations

from quart import Blueprint, current_app, jsonify, request

from server.ai.tasks.broadcast_task import run_broadcast_task


def create_broadcast_ai_blueprint() -> Blueprint:
    bp = Blueprint('broadcast_ai_bp', __name__, url_prefix='/broadcast_ai')

    @bp.get('/health')
    async def health():
        queue = current_app.extensions.get('ai_queue')
        return jsonify({'ok': True, 'route': '/broadcast_ai', 'task': 'broadcast', 'state': 'ready', 'queue_depth': queue.qsize() if queue else 0})

    @bp.post('/evaluate')
    async def evaluate():
        payload = await request.get_json(silent=True) or {}
        result = await run_broadcast_task(current_app.extensions['ai_core'], payload, route='/broadcast_ai')
        await current_app.extensions['ai_memory'].touch(route='/broadcast_ai', task='broadcast', message=str(payload.get('note') or payload.get('query') or ''))
        return jsonify(result)

    return bp
