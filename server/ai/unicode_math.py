from __future__ import annotations

"""Symbolic math primitives for the shared AI core.

This module is intentionally the only place where Unicode Greek identifiers
are used. It provides a compact, bounded fusion model that can score mixed
signals for route specialists such as GFS, broadcast, and LFTR orchestration.
"""

from dataclasses import dataclass
from math import exp


@dataclass(frozen=True)
class Πεδίο:
    """Normalized signal bundle in the range [0, 1] where possible."""

    α: float = 0.0
    β: float = 0.0
    γ: float = 0.0
    δ: float = 0.0
    ε: float = 0.0


@dataclass(frozen=True)
class Παράμετροι:
    """Tunable fusion parameters for specialist route behavior."""

    α: float = 0.25
    β: float = 0.20
    γ: float = 0.20
    δ: float = 0.20
    ε: float = 0.15
    θ: float = 0.50
    κ: float = 6.0


def _κλιπ(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(x)))


def σ(x: float, κ: float = 6.0) -> float:
    """Sigmoid-like bounded mapping in [0, 1]."""

    z = max(-60.0, min(60.0, float(x) * float(κ)))
    return 1.0 / (1.0 + exp(-z))


def Φ(πεδίο: Πεδίο, παράμετροι: Παράμετροι) -> float:
    """Weighted fusion center before confidence shaping."""

    w_sum = παράμετροι.α + παράμετροι.β + παράμετροι.γ + παράμετροι.δ + παράμετροι.ε
    if w_sum <= 0:
        return 0.0
    raw = (
        πεδίο.α * παράμετροι.α
        + πεδίο.β * παράμετροι.β
        + πεδίο.γ * παράμετροι.γ
        + πεδίο.δ * παράμετροι.δ
        + πεδίο.ε * παράμετροι.ε
    ) / w_sum
    return _κλιπ(raw)


def Ω(πεδίο: Πεδίο, παράμετροι: Παράμετροι) -> float:
    """Bounded confidence score with threshold-centered shaping."""

    κέντρο = Φ(πεδίο, παράμετροι) - παράμετροι.θ
    return _κλιπ(σ(κέντρο, παράμετροι.κ))


def to_field(values: dict[str, float]) -> Πεδίο:
    """English-friendly adapter used by non-symbolic modules."""

    return Πεδίο(
        α=_κλιπ(values.get('a', 0.0)),
        β=_κλιπ(values.get('b', 0.0)),
        γ=_κλιπ(values.get('c', 0.0)),
        δ=_κλιπ(values.get('d', 0.0)),
        ε=_κλιπ(values.get('e', 0.0)),
    )
