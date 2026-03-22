from __future__ import annotations

from quart import Blueprint, current_app, jsonify, request

from server.ai.tasks.gfs_task import run_gfs_task


def create_gfs_ai_blueprint() -> Blueprint:
    bp = Blueprint('gfs_ai_bp', __name__, url_prefix='/gfs_ai')

    @bp.get('/health')
    async def health():
        queue = current_app.extensions.get('ai_queue')
        return jsonify({'ok': True, 'route': '/gfs_ai', 'task': 'gfs', 'state': 'ready', 'queue_depth': queue.qsize() if queue else 0})

    @bp.post('/evaluate')
    async def evaluate():
        payload = await request.get_json(silent=True) or {}
        result = await run_gfs_task(current_app.extensions['ai_core'], payload, route='/gfs_ai')
        await current_app.extensions['ai_memory'].touch(route='/gfs_ai', task='gfs', message=str(payload.get('note') or payload.get('query') or ''))
        return jsonify(result)

    return bp
