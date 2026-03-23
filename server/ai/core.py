from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .unicode_math import Παράμετροι, Πεδίο, Ω


@dataclass(frozen=True)
class AIContext:
    route: str
    task: str
    domain: str = 'general'
    source_path: str = ''
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class AICore:
    """Shared AI scoring core used by specialist tasks."""

    def __init__(self) -> None:
        self._presets: dict[str, Παράμετροι] = {
            'gfs': Παράμετροι(α=0.20, β=0.25, γ=0.20, δ=0.25, ε=0.10, θ=0.55, κ=7.0),
            'broadcast': Παράμετροι(α=0.30, β=0.25, γ=0.20, δ=0.15, ε=0.10, θ=0.52, κ=6.5),
            'chat': Παράμετροι(α=0.26, β=0.22, γ=0.20, δ=0.18, ε=0.14, θ=0.50, κ=6.0),
            'lftr': Παράμετροι(α=0.24, β=0.22, γ=0.20, δ=0.20, ε=0.14, θ=0.50, κ=6.0),
            'default': Παράμετροι(),
        }

    @staticmethod
    def _clamp_score(value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    def params_for(self, task: str) -> Παράμετροι:
        key = (task or 'default').strip().lower()
        return self._presets.get(key, self._presets['default'])

    def evaluate(
        self,
        context: AIContext,
        field: Πεδίο,
        *,
        explanation: str = '',
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = self.params_for(context.task)
        score = self._clamp_score(Ω(field, params))
        state = 'active' if score >= 0.5 else 'monitoring'
        return {
            'ok': True,
            'route': context.route,
            'task': context.task,
            'score': round(score, 4),
            'state': state,
            'explanation': explanation or f"Starter {context.task} evaluation computed from fused route signals.",
            'details': {
                'domain': context.domain,
                'source_path': context.source_path,
                'request_id': context.request_id,
                'weights': {
                    'a': params.α,
                    'b': params.β,
                    'c': params.γ,
                    'd': params.δ,
                    'e': params.ε,
                    'theta': params.θ,
                },
                **(details or {}),
            },
        }
