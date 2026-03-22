from __future__ import annotations

from typing import Any

from server.ai.core import AICore, AIContext
from server.ai.unicode_math import to_field

from . import score_value


async def run_gfs_task(core: AICore, payload: dict[str, Any], *, route: str = '/gfs_ai') -> dict[str, Any]:
    field = to_field({
        'a': score_value(payload, 'temp_score', 0.5),
        'b': score_value(payload, 'current_score', 0.5),
        'c': score_value(payload, 'weather_score', 0.5),
        'd': score_value(payload, 'productivity_score', 0.5),
        'e': score_value(payload, 'structure_score', 0.5),
    })
    context = AIContext(
        route=route,
        task='gfs',
        domain='ocean_weather',
        source_path=str(payload.get('source_path') or route),
        request_id=(payload.get('request_id') if isinstance(payload.get('request_id'), str) else None),
    )
    result = core.evaluate(
        context,
        field,
        explanation='Fused field score favored ocean-current, productivity, and weather balance for GFS guidance.',
        details={'inputs': payload},
    )
    return result
