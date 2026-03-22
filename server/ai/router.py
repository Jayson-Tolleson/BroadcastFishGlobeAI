from __future__ import annotations

from typing import Any


def select_specialist(path: str, payload: dict[str, Any] | None = None) -> str:
    """Deterministic specialist selection for starter orchestration."""

    body = payload or {}
    domain = str(body.get('domain') or '').strip().lower()
    hint = str(body.get('task') or body.get('specialist') or '').strip().lower()
    p = (path or '').lower()

    if domain in {'gfs', 'weather', 'ocean'} or hint in {'gfs', 'weather', 'ocean'} or '/gfs' in p:
        return 'gfs'
    if domain in {'broadcast', 'ops', 'operator'} or hint in {'broadcast', 'operator'} or '/broadcast' in p:
        return 'broadcast'
    if domain in {'lftr', 'master'} or '/lftr' in p:
        return 'lftr'
    if hint in {'chat', 'general'}:
        return 'chat'
    return 'chat'


def route_for_specialist(task: str) -> str:
    return {
        'gfs': '/gfs_ai',
        'broadcast': '/broadcast_ai',
        'lftr': '/lftr_ai',
        'chat': '/ai',
    }.get(task, '/ai')
