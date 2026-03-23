from __future__ import annotations

from typing import Any

from server.ai.core import AICore, AIContext
from server.ai.unicode_math import to_field

from . import score_value


async def run_chat_task(core: AICore, payload: dict[str, Any], *, route: str = '/ai') -> dict[str, Any]:
    field = to_field({
        'a': score_value(payload, 'intent_score', 0.5),
        'b': score_value(payload, 'context_score', 0.5),
        'c': score_value(payload, 'confidence_score', 0.5),
        'd': score_value(payload, 'memory_score', 0.5),
        'e': score_value(payload, 'novelty_score', 0.5),
    })
    context = AIContext(route=route, task='chat' if route != '/lftr_ai' else 'lftr', domain='assistant', source_path=str(payload.get('source_path') or route))
    return core.evaluate(
        context,
        field,
        explanation='General assistant score fused intent, context, confidence, memory, and novelty.',
        details={'inputs': payload},
    )
