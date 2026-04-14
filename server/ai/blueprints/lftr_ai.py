from __future__ import annotations

import json

from quart import Blueprint, current_app, jsonify, request, websocket

from server.ai.tasks.chat_task import run_chat_task


def create_lftr_ai_blueprint() -> Blueprint:
    bp = Blueprint('lftr_ai_bp', __name__, url_prefix='/lftr_ai')

    @bp.get('/health')
    async def health():
        queue = current_app.extensions.get('ai_queue')
        return jsonify({'ok': True, 'route': '/lftr_ai', 'task': 'lftr', 'state': 'ready', 'queue_depth': queue.qsize() if queue else 0})

    @bp.post('/evaluate')
    async def evaluate():
        payload = await request.get_json(silent=True) or {}
        result = await run_chat_task(current_app.extensions['ai_core'], payload, route='/lftr_ai')
        await current_app.extensions['ai_memory'].touch(route='/lftr_ai', task='lftr', message=str(payload.get('note') or payload.get('query') or ''))
        return jsonify(result)

    @bp.websocket('/ws')
    async def ws_lftr_ai():
        await websocket.send_json({'type': 'hello', 'route': '/lftr_ai/ws', 'ok': True})
        while True:
            try:
                message = await websocket.receive()
                if message is None:
                    break
                payload = {'query': message}
                if isinstance(message, str):
                    try:
                        parsed = json.loads(message)
                        if isinstance(parsed, dict):
                            payload = parsed
                    except Exception:
                        pass
                result = await run_chat_task(current_app.extensions['ai_core'], payload, route='/lftr_ai')
                await websocket.send_json(result)
            except Exception:
                break

    return bp
