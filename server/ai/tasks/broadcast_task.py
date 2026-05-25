from __future__ import annotations

from typing import Any

from server.ai.core import AICore, AIContext
from server.ai.unicode_math import to_field

from . import score_value


async def run_broadcast_task(core: AICore, payload: dict[str, Any], *, route: str = '/broadcast_ai') -> dict[str, Any]:
    field = to_field({
        'a': score_value(payload, 'attention_score', 0.5),
        'b': score_value(payload, 'relevance_score', 0.5),
        'c': score_value(payload, 'urgency_score', 0.5),
        'd': score_value(payload, 'memory_score', 0.5),
        'e': score_value(payload, 'operator_score', 0.5),
    })
    context = AIContext(route=route, task='broadcast', domain='operator_assist', source_path=str(payload.get('source_path') or route))
    return core.evaluate(
        context,
        field,
        explanation='Broadcast score fused attention, relevance, urgency, operator confidence, and memory continuity.',
        details={'inputs': payload},
    )
