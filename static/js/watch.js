(() => {
  const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
  const wsBase = `${wsProto}://${location.host}`;
  const room = (new URLSearchParams(location.search).get('room') || 'default').trim() || 'default';

  const dom = {
    video: document.getElementById('remoteVideo'),
    standby: document.getElementById('standby'),
    statusText: document.getElementById('statusText'),
    conn: document.getElementById('conn'),
    mode: document.getElementById('mode'),
    ai: document.getElementById('ai'),
    label: document.getElementById('label'),
    watchers: document.getElementById('watchers'),
    joinOverlay: document.getElementById('joinStreamOverlay'),
    joinBtn: document.getElementById('joinStreamBtn'),
    joinHint: document.getElementById('joinHint'),
    chatDock: document.getElementById('chatDock'),
    chatCollapseBtn: document.getElementById('chatCollapseBtn'),
    chat: document.getElementById('chat'),
    chatInput: document.getElementById('chatInput'),
    sendBtn: document.getElementById('sendBtn'),
    attachBtn: document.getElementById('attachBtn'),
    fileInput: document.getElementById('file'),
    webBtn: document.getElementById('webBtn'),
    searchCloseBtn: document.getElementById('searchCloseBtn'),
    searchPane: document.getElementById('searchPane'),
    searchResults: document.getElementById('searchResults'),
  };
  const v = dom.video;

  const unmuteBtn = document.createElement('button');
  unmuteBtn.textContent = 'Tap for sound';
  unmuteBtn.style.display = 'none';
  let liveOverlayApi = null;
  let audioTrackSeen = false;
  let videoTrackSeen = false;
  let videoActive = false;
  let offerInProgress = false;
  let lastRequestAt = 0;
  let lastForceRequestAt = 0;
  let missingVideoSince = 0;
  const REQUEST_MIN_INTERVAL_MS = 3000;
  const FORCE_RENEGOTIATE_MIN_INTERVAL_MS = 10000;
  const MISSING_VIDEO_TIMEOUT_MS = 7000;

  let ws = null;
  let pc = null;
  let reconnectDelayMs = 1000;
  let viewerId = `watch-${Math.random().toString(36).slice(2, 10)}`;
  let broadcasterPresent = false;
  let requestPending = false;
  let hasRequestedStream = false;
  let retryTimer = null;
  let requestTimeout = null;
  let streamPollTimer = null;
  let hearAiVoice = true;
  const DEBUG_CHAT = false;
  let lastChatSendAt = 0;
  let lastChatText = '';

  if (dom.joinOverlay) dom.joinOverlay.appendChild(unmuteBtn);

  function setStatus(text) {
    if (dom.statusText) dom.statusText.textContent = text;
  }

  function showJoinOverlay(show, reason = '') {
    if (!dom.joinOverlay) return;
    dom.joinOverlay.style.display = show ? 'flex' : 'none';
    if (show && dom.joinHint && reason) dom.joinHint.textContent = reason;
  }

  function setStandby(show, reason = 'Waiting for live stream…') {
    if (dom.standby) dom.standby.style.display = show ? 'block' : 'none';
    if (show) setStatus(reason);
  }

  async function playAiVoice(url) {
    if (!url || !hearAiVoice) return;
    try {
      const audio = new Audio(url);
      audio.volume = 0.9;
      await audio.play();
    } catch (_) {}
  }

  function appendChat(entry) {
    if (!dom.chat) return;
    const wrap = document.createElement('div');
    wrap.className = 'entry';
    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.textContent = `${entry.user || entry.sender || 'room'} • ${new Date().toLocaleTimeString()}`;
    const body = document.createElement('div');
    body.textContent = entry.text || '';
    wrap.append(meta, body);
    dom.chat.appendChild(wrap);
    dom.chat.scrollTop = dom.chat.scrollHeight;
  }

  function renderSearchResults(query, result) {
    if (!dom.searchPane || !dom.searchResults) return;
    const results = (((result || {}).data || {}).results || []);
    dom.searchPane.classList.add('open');
    dom.searchResults.textContent = '';
    const frag = document.createDocumentFragment();
    if (!results.length) {
      const empty = document.createElement('div');
      empty.className = 'searchMeta';
      empty.textContent = `No results for "${query}".`;
      frag.appendChild(empty);
    } else {
      for (const item of results.slice(0, 8)) {
        const row = document.createElement('div');
        row.className = 'searchItem';
        const title = document.createElement('a');
        title.href = item.url || '#';
        title.target = '_blank';
        title.rel = 'noopener';
        title.textContent = item.title || item.url || 'Result';
        const snip = document.createElement('div');
        snip.textContent = item.snippet || '';
        const meta = document.createElement('div');
        meta.className = 'searchMeta';
        meta.textContent = item.source || 'web';
        row.append(title, snip, meta);
        frag.appendChild(row);
      }
    }
    dom.searchResults.appendChild(frag);
  }

  function sendJson(type, extra = {}) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify({ type, room, clientId: viewerId, role: 'viewer', ...extra }));
    return true;
  }

  async function ensureLiveOverlay() {
    if (liveOverlayApi) return liveOverlayApi;
    try {
      liveOverlayApi = await import('/static/js/ui/liveOverlay.js');
      return liveOverlayApi;
    } catch (err) {
      console.warn('[watch/liveOverlay] import failed', err);
      return null;
    }
  }

  async function overlaySet(phase, payload = {}) {
    const api = await ensureLiveOverlay();
    if (!api || typeof api.applyLiveOverlay !== 'function') return;
    try { api.applyLiveOverlay(phase, payload); } catch (err) { console.warn('[watch/liveOverlay] apply failed', err); }
  }

  function hasLiveRemoteVideo() {
    const stream = dom.video && dom.video.srcObject;
    return stream instanceof MediaStream && stream.getVideoTracks().some((track) => track.readyState === 'live');
  }


  function setLiveMutedAutoplay() {
    if (!v) return;
    v.playsInline = true;
    v.autoplay = true;
    v.controls = true;
    v.muted = true;
  }

  async function tryPlay(reason) {
    if (!dom.video) return;
    dom.video.controls = true;
    dom.video.muted = true;
    try {
      console.info('[watch/video] autoplay attempt', { reason });
      dom.video.muted = true;
      await dom.video.play();
      showJoinOverlay(false);
      console.info('[watch/video] playing', { reason });
    } catch (err) {
      console.warn('[watch/video] autoplay blocked', { reason, message: err?.message || String(err) });
      showJoinOverlay(true, 'Tap to Play Stream');
    }
  }

  function requestStream(force = false, reason = 'default') {
    if (!broadcasterPresent) return;
    const now = Date.now();
    if (!force && (requestPending || offerInProgress)) return;
    if (!force && hasRequestedStream && (now - lastRequestAt) < REQUEST_MIN_INTERVAL_MS) return;
    if (force && (now - lastForceRequestAt) < FORCE_RENEGOTIATE_MIN_INTERVAL_MS) return;

    if (force) {
      hasRequestedStream = false;
      requestPending = false;
      if (requestTimeout) { clearTimeout(requestTimeout); requestTimeout = null; }
      lastForceRequestAt = now;
      sendJson('request_stream', { force: true, reason });
      console.info('[watch/video] forcing renegotiation reason=%s', reason);
    } else {
      requestPending = sendJson('request_stream');
    }
    hasRequestedStream = requestPending || force || hasRequestedStream;
    lastRequestAt = now;
    if (requestPending || force) {
      if (requestTimeout) clearTimeout(requestTimeout);
      requestTimeout = setTimeout(() => {
        requestPending = false;
        hasRequestedStream = false;
      }, 4000);
    }
    console.info('[watch] request_stream sent', { room, viewerId, requestPending, force, reason });
  }

  async function iceServers() {
    try {
      const r = await fetch('/webrtc/ice-config');
      const j = await r.json();
      return j.iceServers || [{ urls: 'stun:stun.l.google.com:19302' }];
    } catch {
      return [{ urls: 'stun:stun.l.google.com:19302' }];
    }
  }

  async function ensurePeerConnection(reset = false) {
    if (pc && !reset) return pc;
    if (pc && reset) {
      try { pc.close(); } catch (_) {}
      pc = null;
    }
    pc = new RTCPeerConnection({ iceServers: await iceServers() });
    pc.ontrack = async (event) => {
      console.info('[watch/rtc] track received kind=%s id=%s', (event.track?.kind || 'unknown'), (event.track?.id || 'na'));
      const existing = dom.video.srcObject instanceof MediaStream ? dom.video.srcObject : new MediaStream();
      if (event.track && !existing.getTracks().find((t) => t.id === event.track.id)) existing.addTrack(event.track);
      if (dom.video.srcObject !== existing) dom.video.srcObject = existing;
      setStandby(false);
      await tryPlay('remote_track_attach');
      if (event.track?.kind === 'video') {
        videoTrackSeen = true;
        missingVideoSince = 0;
        dom.mode && (dom.mode.textContent = 'LIVE');
        console.info('[watch/rtc] video track attached');
        overlaySet('video_active', { room });
      } else if (event.track?.kind === 'audio') {
        audioTrackSeen = true;
      }
      if (!hasLiveRemoteVideo()) {
        if (audioTrackSeen && !videoTrackSeen) setStandby(true, 'audio-only: waiting for video track');
        else setStandby(true, 'Broadcaster connected, waiting for video…');
        overlaySet('waiting_for_video', { room });
      }
    };
    pc.onicecandidate = (e) => {
      if (!e.candidate) return;
      sendJson('webrtc_ice', { candidate: e.candidate });
    };
    pc.onconnectionstatechange = () => {
      const state = pc?.connectionState || 'unknown';
      console.info('[watch] pc connection state', { state });
      if (state === 'failed' || state === 'disconnected' || state === 'closed') {
        requestPending = false;
        if (requestTimeout) { clearTimeout(requestTimeout); requestTimeout = null; }
        hasRequestedStream = false;
        setStandby(true, 'Reconnecting stream…');
        if (broadcasterPresent) requestStream(false, 'pc_state_recover');
      }
    };
    return pc;
  }

  async function onOffer(payload, sourceType) {
    if (!payload?.sdp) return;
    console.info('[watch] offer received', { room, viewerId, sourceType });
    requestPending = false;
    hasRequestedStream = false;
    offerInProgress = true;
    const localPc = await ensurePeerConnection(true);
    await localPc.setRemoteDescription(payload);
    const answer = await localPc.createAnswer();
    await localPc.setLocalDescription(answer);
    sendJson('webrtc_answer', { sdp: answer.sdp, type: answer.type });
    offerInProgress = false;
    console.info('[watch] answer sent', { viewerId });
  }

  async function onServerMessage(msg) {
    if (msg.type === 'connected' && msg.clientId) {
      viewerId = String(msg.clientId);
      console.info('[watch] viewer websocket connected', { room, viewerId });
      return;
    }
    if (msg.type === 'state_sync' || msg.type === 'state_update') {
      const st = msg.state || {};
      broadcasterPresent = !!st.runtime?.broadcaster_present;
      if (dom.watchers) dom.watchers.textContent = `watchers ${st.runtime?.viewer_count ?? 0}`;
      if (dom.ai) dom.ai.textContent = `AI ${st.settings?.ai_status || (st.settings?.ai_enabled ? 'active' : 'idle')}`;
      hearAiVoice = Boolean(st.settings?.hear_ai_voice ?? hearAiVoice);
      const present = broadcasterPresent;
      const videoReady = !!st.runtime?.stream_live || !!st.runtime?.video_ready;
      if (present && videoReady && !requestPending && !offerInProgress && !hasLiveRemoteVideo()) {
        requestStream(false, 'state_sync');
      }
      return;
    }
    if (msg.type === 'presence') {
      broadcasterPresent = !!msg.broadcaster_present;
      const videoReady = !!msg.stream_live || !!msg.video_ready;
      if (dom.watchers) dom.watchers.textContent = `watchers ${msg.viewer_count ?? 0}`;
      if (broadcasterPresent && videoReady && !hasLiveRemoteVideo()) {
        dom.mode && (dom.mode.textContent = 'LIVE');
        requestStream(false, 'presence_video_ready');
      } else if (broadcasterPresent) {
        dom.mode && (dom.mode.textContent = 'WAITING VIDEO');
        setStandby(true, 'Broadcaster connected, waiting for video…');
        overlaySet('waiting_for_video', { room });
      } else {
        dom.mode && (dom.mode.textContent = 'OFFLINE');
        setStandby(true, 'Waiting for broadcaster…');
        requestPending = false;
      }
      return;
    }
    if (msg.type === 'stream_started') {
      const kind = msg.kind || msg.payload?.kind;
      if (kind !== 'video') {
        console.info('[watch] ignoring non-video stream_started', msg);
        return;
      }
      broadcasterPresent = true;
      requestStream(false, 'stream_started_video');
      return;
    }
    if (msg.type === 'stream_video_ready') {
      broadcasterPresent = true;
      const kind = msg.kind || msg.payload?.kind;
      if (kind && kind !== 'video') return;
      if (!hasLiveRemoteVideo()) requestStream(false, 'stream_video_ready');
      return;
    }
    if (msg.type === 'broadcaster-start') {
      const kind = msg.kind || msg.payload?.kind;
      if (kind !== 'video') {
        console.info('[watch] ignoring non-video broadcaster-start', msg);
        return;
      }
      broadcasterPresent = true;
      requestStream(false, 'broadcaster_start_video');
      return;
    }
    if (msg.type === 'broadcaster-stop') {
      broadcasterPresent = false;
      requestPending = false;
      if (requestTimeout) { clearTimeout(requestTimeout); requestTimeout = null; }
      hasRequestedStream = false;
      setStandby(true, 'Broadcast ended');
      showJoinOverlay(false);
      return;
    }
    if (msg.type === 'ai_status' && dom.ai) {
      dom.ai.textContent = `AI ${msg.status || 'idle'}`;
      return;
    }
    if (msg.type === 'stage_state') {
      const p = msg.payload || {};
      if (dom.label) dom.label.textContent = p.label || 'PUBLIC ACCESS';
      if (p.mode === 'upload' && p.latestUploadUrl) {
        if (pc) { try { pc.close(); } catch (_) {} pc = null; }
        dom.video.srcObject = null;
        dom.video.src = p.latestUploadUrl;
        dom.video.muted = true;
        await tryPlay('fallback_upload');
        dom.mode && (dom.mode.textContent = 'LATEST UPLOAD');
        setStandby(false);
      }
      return;
    }
    if (msg.type === 'chat' || msg.type === 'ai' || msg.type === 'ai_partial' || msg.type === 'attachment') {
      appendChat(msg);
      if (msg.type === 'ai' && msg.voice) playAiVoice(msg.voice);
      return;
    }
    if (msg.type === 'web_search_result') {
      renderSearchResults(msg.query || '', msg.result || {});
      return;
    }
    if (msg.type === 'waiting' || msg.type === 'error') {
      if (msg.message === 'stream_offline' || msg.message === 'no_broadcaster') {
        requestPending = false;
        if (requestTimeout) { clearTimeout(requestTimeout); requestTimeout = null; }
        hasRequestedStream = false;
        setStandby(true, msg.message === 'stream_offline' ? 'Broadcaster connected, waiting for media…' : 'Waiting for broadcaster…');
        if (msg.message === 'stream_offline' && broadcasterPresent) requestStream(false, 'stream_offline');
      }
      return;
    }
    if (msg.type === 'watch_offer' || msg.type === 'webrtc_offer') {
      await onOffer(msg.payload, msg.type);
      return;
    }
    if (msg.type === 'webrtc_ice') {
      const candidate = msg.candidate || msg.payload?.candidate;
      if (!candidate) return;
      await ensurePeerConnection();
      try {
        await pc.addIceCandidate(candidate);
        console.info('[watch] ice received', { viewerId, type: msg.type });
      } catch (err) {
        console.warn('[watch] ice add failed', { message: err?.message || String(err) });
      }
    }
  }

  function connect() {
    const url = `${wsBase}/ws/watch`;
    ws = new WebSocket(url);
    dom.conn && (dom.conn.textContent = 'connecting');

    ws.onopen = () => {
      reconnectDelayMs = 1000;
      dom.conn && (dom.conn.textContent = 'connected');
      requestPending = false;
      if (requestTimeout) { clearTimeout(requestTimeout); requestTimeout = null; }
      hasRequestedStream = false;
      setStandby(true, 'Waiting for live stream…');
      setLiveMutedAutoplay();
      sendJson('join');
      requestStream(false, 'ws_open');
      if (streamPollTimer) clearInterval(streamPollTimer);
      streamPollTimer = setInterval(() => {
        if (!broadcasterPresent) return;
        const hasVideo = hasLiveRemoteVideo();
        if (hasVideo) {
          videoActive = true;
          missingVideoSince = 0;
          return;
        }
        if (!missingVideoSince) missingVideoSince = Date.now();
        if (requestPending || offerInProgress) {
          setStandby(true, 'connecting video…');
          return;
        }
        if (!videoTrackSeen && !audioTrackSeen) {
          setStandby(true, 'waiting for video track…');
          return;
        }
        if (audioTrackSeen && !videoTrackSeen) {
          setStandby(true, 'audio connected, waiting for video track.');
        }
        if ((Date.now() - missingVideoSince) >= MISSING_VIDEO_TIMEOUT_MS) {
          requestStream(true, 'missing_video');
        } else if (!requestPending && !offerInProgress) {
          requestStream(false, 'poll_wait_video');
        }
      }, 2500);
    };

    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      onServerMessage(msg).catch((err) => console.warn('[watch] message handling failed', err));
    };

    ws.onerror = (err) => console.warn('[watch] websocket error', { room, err });

    ws.onclose = (ev) => {
      dom.conn && (dom.conn.textContent = 'reconnecting');
      requestPending = false;
      hasRequestedStream = false;
      if (streamPollTimer) { clearInterval(streamPollTimer); streamPollTimer = null; }
      setStandby(true, 'Reconnecting viewer socket…');
      console.warn('[watch] websocket disconnected', { code: ev.code, reason: ev.reason, reconnectDelayMs });
      setTimeout(connect, reconnectDelayMs);
      reconnectDelayMs = Math.min(20000, Math.round(reconnectDelayMs * 1.8));
    };
  }

  dom.joinBtn?.addEventListener('click', async () => {
    dom.video.muted = true;
    dom.video.controls = true;
    console.info('[watch/video] user play started');
    await tryPlay('manual_overlay_click');
  });

  dom.chatCollapseBtn?.addEventListener('click', () => {
    if (!dom.chatDock) return;
    dom.chatDock.classList.toggle('collapsed');
    dom.chatCollapseBtn.textContent = dom.chatDock.classList.contains('collapsed') ? 'Expand' : 'Collapse';
  });

  function sendChatMessage() {
    const text = (dom.chatInput?.value || '').trim();
    if (!text) return;
    const now = Date.now();
    if (text === lastChatText && (now - lastChatSendAt) < 400) return;
    lastChatText = text;
    lastChatSendAt = now;
    if (DEBUG_CHAT) console.debug('[watch.chat] send', { chars: text.length });
    sendJson('chat', { text });
    dom.chatInput.value = '';
  }

  dom.sendBtn?.addEventListener('click', sendChatMessage);

  dom.chatInput?.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && !ev.shiftKey) {
      ev.preventDefault();
      sendChatMessage();
    }
  });

  dom.attachBtn?.addEventListener('click', () => dom.fileInput?.click());
  dom.fileInput?.addEventListener('change', async () => {
    const f = dom.fileInput.files?.[0];
    if (!f) return;
    const fd = new FormData();
    fd.append('file', f, f.name);
    const uploadType = /^image\//i.test(f.type || '') ? 'image' : 'location_video';
    fd.append('upload_type', uploadType);
    try {
      const r = await fetch('/api/upload', { method: 'POST', body: fd });
      const payload = await r.json();
      sendJson('attachment', { attachment: payload });
      sendJson('attachment_uploaded', { attachment: payload });
      appendChat({ user: 'you', text: `Uploaded: ${payload.url || payload.path || f.name}` });
    } catch (err) {
      appendChat({ user: 'system', text: `Upload failed: ${err?.message || String(err)}` });
    } finally {
      dom.fileInput.value = '';
    }
  });

  dom.webBtn?.addEventListener('click', () => {
    const query = (dom.chatInput?.value || '').trim();
    if (!query) return;
    if (DEBUG_CHAT) console.debug('[watch.chat] web_search send', { query_len: query.length });
    sendJson('web_search', { query });
  });

  dom.searchCloseBtn?.addEventListener('click', () => dom.searchPane?.classList.remove('open'));

  dom.video?.addEventListener('loadedmetadata', () => {
    console.info('[watch/rtc] video dimensions width=%s height=%s', dom.video.videoWidth, dom.video.videoHeight);
  });
  dom.video?.addEventListener('resize', () => {
    console.info('[watch/rtc] video dimensions width=%s height=%s', dom.video.videoWidth, dom.video.videoHeight);
  });
  dom.video?.addEventListener('playing', () => {
    const active = dom.video.videoWidth > 0 && dom.video.videoHeight > 0;
    console.info('[watch/video] live video received %s', active);
    if (active) {
      videoActive = true;
      missingVideoSince = 0;
      setStandby(false);
      dom.mode && (dom.mode.textContent = 'LIVE');
      overlaySet('video_active', { room });
    }
  });

  connect();
})();
