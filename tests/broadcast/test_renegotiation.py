from __future__ import annotations

import asyncio

from server.state import AppState


def test_broadcaster_renegotiation_reuses_peer_for_same_sid(rtc_patched):
    async def _run():
        from server.rtc import RTCManager

        state = AppState(default_room="room")
        rtc = RTCManager(state)

        await rtc.start_broadcaster_from_offer("room", "b1", "offer-cam", "offer")
        first_pc = rtc.broadcasters["room"].pc

        # Simulate camera -> screen renegotiation by another offer from same broadcaster.
        await rtc.start_broadcaster_from_offer("room", "b1", "offer-screen", "offer")
        second_pc = rtc.broadcasters["room"].pc

        assert second_pc is not first_pc

        # Simulate screen -> camera renegotiation.
        await rtc.start_broadcaster_from_offer("room", "b1", "offer-cam-back", "offer")
        third_pc = rtc.broadcasters["room"].pc

        assert third_pc is not second_pc


    asyncio.run(_run())
def test_watcher_peer_survives_broadcaster_renegotiation(rtc_patched):
    async def _run():
        from server.rtc import RTCManager

        state = AppState(default_room="room")
        rtc = RTCManager(state)

        await rtc.start_broadcaster_from_offer("room", "b1", "offer-initial", "offer")
        rtc.broadcasters["room"].tracks["video"] = object()

        await rtc.start_viewer_offer("room", "w1")
        await rtc.set_viewer_answer("room", "w1", "answer-initial", "answer")
        watcher_pc = rtc.viewers["room"]["w1"]

        # Broadcaster renegotiates source changes; watcher should stay mapped/alive.
        await rtc.start_broadcaster_from_offer("room", "b1", "offer-switch-1", "offer")
        await rtc.start_broadcaster_from_offer("room", "b1", "offer-switch-2", "offer")

        assert "w1" in rtc.viewers.get("room", {})
    asyncio.run(_run())


def test_rtc_video_event_contract_in_source():
    from pathlib import Path
    src = Path("server/rtc.py").read_text(encoding="utf-8")
    assert 'generation: str = ""' in src
    assert 'video_ready_emitted: bool = False' in src
    assert 'async def stop_broadcaster(self, room_id: str, sid: str, generation: str | None = None)' in src
    assert 'ignore stale broadcaster pc state' in src
    assert 'ignore stale stop_broadcaster' in src
    assert 'existing = self.broadcasters.pop(room_id, None)' in src
    assert 'self.broadcast_video_event' in src
    assert 'def _room_video_event' in src
    assert 'if getattr(track, "kind", None) == "video":' in src
    assert 'elif getattr(track, "kind", None) == "audio":' in src
    assert '"stream_video_ready"' in src
    assert '"audio_ready"' in src
    assert 'source="transceiver-scan"' in src
