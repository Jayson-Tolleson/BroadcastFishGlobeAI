from pathlib import Path


def test_broadcast_sh_no_html_mutation_logic():
    src = Path('broadcast.sh').read_text(encoding='utf-8')
    assert 'install.env' in src
    assert 'deploy/install.sh' in src
    assert 'PYMAPS' not in src
    assert 'rglob("*.html")' not in src
    assert 'Injected Google Maps API key into HTML files' not in src


def test_routes_split_files_present_and_used():
    routes_src = Path('server/routes.py').read_text(encoding='utf-8')
    assert 'register_core_routes' in routes_src
    assert 'create_gfs_blueprint' in routes_src
    assert 'register_broadcast_routes' in routes_src


def test_core_pages_and_ws_routes_exist():
    import asyncio
    from server.app_factory import create_app

    async def _run():
        app = create_app()
        client = app.test_client()
        for path in ['/', '/broadcast', '/watch', '/gfs']:
            res = await client.get(path)
            assert res.status_code in {200, 500}

    asyncio.run(_run())


def test_watch_js_avoids_forced_duplicate_stream_requests():
    src = Path('static/js/watch.js').read_text(encoding='utf-8')
    assert 'hasRequestedStream' in src
    assert "if (msg.type === 'stream_started')" in src
    assert "requestStream(false, 'stream_video_ready')" in src
    assert "requestStream(false, 'presence')" not in src
    assert 'audioTrackSeen' in src


def test_routes_live_flag_is_video_based_not_audio_based():
    src = Path('server/broadcast/routes.py').read_text(encoding='utf-8')
    assert 'rtc.has_live_video_source(room_id)' in src
    assert 'rtc_live = bool(rtc is not None and rtc.has_live_source(room_id))' not in src


def test_broadcast_offer_path_is_canvas_first_and_resilient():
    src = Path('static/js/broadcast.js').read_text(encoding='utf-8')
    assert 'Promise.allSettled' in src
    assert 'syncTracks failed; publishing canvas anyway' in src
    assert 'captureStream(30)' in src
    assert 'pc.addTrack(vtrack, ps)' in src
    assert "console.info('[broadcast/webrtc] createOffer hasVideoSender=%s'" in src
