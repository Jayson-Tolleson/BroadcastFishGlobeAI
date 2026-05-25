(() => {
  const cfg = window.BROADCAST_CONFIG || {};
  const wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
  const wsBase = `${wsProto}://${location.host}`;

  const dom = {
    preview: document.getElementById('preview'),
    chat: document.getElementById('chat'),
    chatInput: document.getElementById('chatInput'),
    sendBtn: document.getElementById('sendBtn'),
    roomStatus: document.getElementById('roomStatus'),
    stRoom: document.getElementById('stRoom'),
    stServer: document.getElementById('stServer'),
    stRoomConn: document.getElementById('stRoomConn'),
    stLive: document.getElementById('stLive'),
    stAi: document.getElementById('stAi'),
    stWatchers: document.getElementById('stWatchers'),
    stPc: document.getElementById('stPc'),
    stIce: document.getElementById('stIce'),
    ledServer: document.getElementById('ledServer'),
    ledRoom: document.getElementById('ledRoom'),
    ledLive: document.getElementById('ledLive'),
    ledAi: document.getElementById('ledAi'),
    camBtn: document.getElementById('camBtn'),
    screenBtn: document.getElementById('screenBtn'),
    micBtn: document.getElementById('micBtn'),
    sttBtn: document.getElementById('sttBtn'),
    ncBtn: document.getElementById('ncBtn'),
    aiEnableBtn: document.getElementById('aiEnableBtn'),
    aiStatusBtn: document.getElementById('aiStatusBtn'),
    ttsMonBtn: document.getElementById('ttsMonBtn'),
    recordBtn: document.getElementById('recordBtn'),
    rtmpBtn: document.getElementById('rtmpBtn'),
    rtmpKeyInput: document.getElementById('rtmpKeyInput'),
    recordingStatus: document.getElementById('recordingStatus'),
    attachBtn: document.getElementById('attachBtn'),
    webBtn: document.getElementById('webBtn'),
    searchCloseBtn: document.getElementById('searchCloseBtn'),
    searchPane: document.getElementById('searchPane'),
    searchResults: document.getElementById('searchResults'),
    fileInput: document.getElementById('file'),
    chatCollapseBtn: document.getElementById('chatCollapseBtn'),
    chatPanel: document.querySelector('.chat'),
  };

  let chatRetryMs = 1200;
  let signalRetryMs = 1200;
  const DEBUG_CHAT = false;
  let lastChatSendAt = 0;
  let lastChatText = '';
  let selectedVideoDeviceId = '';
  let cachedVideoInputs = [];
  let cameraCycleIndex = -1;
  let preferredFacingMode = 'user';
  let cameraModes = [];
  let cameraModeIndex = -1;
  let recordingStream = null;
  let recordingChunks = [];
  let recordingMedia = null;
  let activeAiAudio = null;
  let wakeLockSentinel = null;
  let programCanvas = null;
  let programCtx = null;
  let programStream = null;
  let programVideoTrack = null;
  let programLoopHandle = 0;
  let programLoopRunning = false;
  const pip = { enabled: false, x: 20, y: 20, w: 220, h: 124, dragging: false, dragOffsetX: 0, dragOffsetY: 0 };
  let lastSttSentAt = 0;
  let sttFrameModulo = 0;
  const camSourceEl = document.createElement('video');
  camSourceEl.muted = true;
  camSourceEl.playsInline = true;
  const screenSourceEl = document.createElement('video');
  screenSourceEl.muted = true;
  screenSourceEl.playsInline = true;

  const state = {
    room: cfg.room || new URLSearchParams(location.search).get('room') || 'default',
    clientId: `b-${Math.random().toString(36).slice(2, 10)}`,
    pc: null,
    peerConnections: {},
    chatWs: null,
    signalWs: null,
    camStream: null,
    screenStream: null,
    speechCtx: null,
    speechSource: null,
    speechProcessor: null,
    speechProgramStream: null,
    media: {
      ai_enabled: true,
      ai_status: 'idle',
      stt_enabled: true,
      tts_enabled: true,
      hear_ai_voice: true,
      mic_enabled: true,
      camera_enabled: true,
      screen_enabled: false,
      noise_cancel_enabled: true,
      record_enabled: false,
      rtmp_enabled: false,
      rtmp_url: '',
    },
  };
  dom.stRoom && (dom.stRoom.textContent = state.room);

  function setLed(el, on) {
    if (!el) return;
    el.classList.remove('r', 'g');
    el.classList.add(on ? 'g' : 'r');
  }

  function sendJson(ws, type, extra = {}) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type, room: state.room, clientId: state.clientId, role: 'broadcaster', ...extra }));
  }

  function applyPresence(presence) {
    const viewers = Number(presence.viewer_count ?? 0);
    dom.stWatchers && (dom.stWatchers.textContent = `${viewers}`);
    dom.roomStatus && (dom.roomStatus.textContent = `viewers: ${viewers}`);
    dom.stLive && (dom.stLive.textContent = presence.broadcaster_present ? 'live' : 'offline');
    setLed(dom.ledLive, !!presence.broadcaster_present);
  }

  function updateAiStatus(status) {
    state.media.ai_status = status || 'idle';
    dom.stAi && (dom.stAi.textContent = state.media.ai_status);
    if (dom.aiStatusBtn) dom.aiStatusBtn.textContent = `AI ${state.media.ai_status}`;
    setLed(dom.ledAi, state.media.ai_status === 'active' || state.media.ai_enabled);
  }



  async function acquireWakeLock(reason = 'init') {
    if (!('wakeLock' in navigator)) return;
    if (document.visibilityState !== 'visible') return;
    try {
      wakeLockSentinel = await navigator.wakeLock.request('screen');
      wakeLockSentinel.addEventListener('release', () => {
        if (document.visibilityState === 'visible') {
          acquireWakeLock('released').catch(() => {});
        }
      }, { once: true });
      console.info('[broadcast] wake lock active', { reason });
    } catch (err) {
      console.info('[broadcast] wake lock unavailable', { reason, message: err?.message || String(err) });
    }
  }

  function installWakeLock() {
    const retry = () => acquireWakeLock('visibility').catch(() => {});
    document.addEventListener('visibilitychange', retry);
    const activate = () => acquireWakeLock('gesture').catch(() => {});
    window.addEventListener('pointerdown', activate, { passive: true });
    window.addEventListener('touchstart', activate, { passive: true });
    window.addEventListener('keydown', activate, { passive: true });
    acquireWakeLock('boot').catch(() => {});
  }

  function applyRoomState(next = {}) {
    const settings = next.settings || {};
    state.media = { ...state.media, ...settings };
    if (next.runtime) applyPresence(next.runtime);
    updateAiStatus(state.media.ai_status);

    const setTxt = (id, txt) => { const n = document.getElementById(id); if (n) n.textContent = txt; };
    setLed(document.getElementById('camLed'), !!state.media.camera_enabled);
    if (!state.media.camera_enabled) {
      setTxt('camTxt', 'CAM: off');
    }
    setLed(document.getElementById('screenLed'), !!state.media.screen_enabled);
    setTxt('screenTxt', `SCREEN: ${state.media.screen_enabled ? 'on' : 'off'}`);
    setLed(document.getElementById('micLed'), !!state.media.mic_enabled);
    setTxt('micTxt', `MIC: ${state.media.mic_enabled ? 'on' : 'off'}`);
    setLed(document.getElementById('sttLed'), !!state.media.stt_enabled);
    setTxt('sttTxt', `STT: ${state.media.stt_enabled ? 'on' : 'off'}`);
    setLed(document.getElementById('ncLed'), !!state.media.noise_cancel_enabled);
    setTxt('ncTxt', `NoiseCancel: ${state.media.noise_cancel_enabled ? 'on' : 'off'}`);
    setLed(document.getElementById('ttsMonLed'), !!state.media.hear_ai_voice);
    setTxt('ttsMonTxt', `Hear AI voice: ${state.media.hear_ai_voice ? 'on' : 'off'}`);
    setLed(document.getElementById('aiEnableLed'), !!state.media.ai_enabled);
    setTxt('aiEnableTxt', `AI: ${state.media.ai_enabled ? 'on' : 'off'}`);
    setLed(document.getElementById('recordLed'), !!state.media.record_enabled);
    setTxt('recordTxt', `Record: ${state.media.record_enabled ? 'on' : 'off'}`);
    setLed(document.getElementById('rtmpLed'), !!state.media.rtmp_enabled);
    setTxt('rtmpTxt', `RTMP: ${state.media.rtmp_enabled ? 'on' : 'off'}`);
  }

  function compactCameraName(label) {
    const text = String(label || '').trim();
    if (!text) return 'camera';
    if (/front|user/i.test(text)) return 'front cam';
    if (/back|rear|environment/i.test(text)) return 'back cam';
    return text.length > 18 ? `${text.slice(0, 18)}…` : text;
  }

  function updateCameraLabel(label) {
    const camTxt = document.getElementById('camTxt');
    if (!camTxt) return;
    camTxt.textContent = state.media.camera_enabled ? `CAM: ${compactCameraName(label)}` : 'CAM: off';
  }

  function isTouchLikeDevice() {
    return ('ontouchstart' in window) || navigator.maxTouchPoints > 0;
  }

  function getPreferredRecorderOptions() {
    const candidates = [
      'video/webm;codecs=vp9,opus',
      'video/webm;codecs=vp8,opus',
      'video/webm',
    ];
    for (const mimeType of candidates) {
      if (window.MediaRecorder?.isTypeSupported?.(mimeType)) return { mimeType };
    }
    return {};
  }

  function timestampedRecordingName() {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return `broadcast-${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}.webm`;
  }

  function appendChat(msg) {
    if (!dom.chat) return;
    const startedAt = performance.now();
    const d = document.createElement('article');
    d.className = 'entry';
    const who = msg.user || msg.sender || 'system';
    const text = msg.text || msg.payload?.text || '';
    const whoEl = document.createElement('b');
    whoEl.textContent = `[${who}]`;
    const textEl = document.createElement('div');
    textEl.textContent = String(text);
    d.append(whoEl, textEl);
    if (msg.attachment?.url) {
      const a = document.createElement('a');
      a.href = msg.attachment.url;
      a.target = '_blank';
      a.rel = 'noopener';
      a.textContent = msg.attachment.name || 'attachment';
      d.appendChild(a);
    }
    dom.chat.appendChild(d);
    dom.chat.scrollTop = dom.chat.scrollHeight;
    if (DEBUG_CHAT) {
      console.debug('[broadcast.chat] render_ms', Math.round((performance.now() - startedAt) * 1000) / 1000);
    }
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

  function updateConnectivity(online) {
    dom.stServer && (dom.stServer.textContent = online ? 'connected' : 'disconnected');
    dom.stRoomConn && (dom.stRoomConn.textContent = online ? 'connected' : 'disconnected');
    setLed(dom.ledServer, online);
    setLed(dom.ledRoom, online);
  }

  async function requestCameraStream(videoConstraints) {
    return navigator.mediaDevices.getUserMedia({
      video: videoConstraints,
      audio: {
        echoCancellation: true,
        noiseSuppression: !!state.media.noise_cancel_enabled,
        autoGainControl: true,
        channelCount: 1,
        sampleRate: 48000,
      },
    });
  }

  function audioConstraints() {
    return {
      echoCancellation: true,
      noiseSuppression: !!state.media.noise_cancel_enabled,
      autoGainControl: true,
      channelCount: 1,
      sampleRate: 48000,
    };
  }

  async function buildCameraModes() {
    const inputs = await refreshVideoInputs();
    const facingModes = [
      { kind: 'facing', label: 'Front', facingMode: 'user' },
      { kind: 'facing', label: 'Back', facingMode: 'environment' },
    ];
    const deviceModes = inputs.map((d, idx) => ({ kind: 'device', label: d.label || `Camera ${idx + 1}`, deviceId: d.deviceId }));
    cameraModes = isTouchLikeDevice() ? [...facingModes, ...deviceModes] : [...deviceModes, ...facingModes];
    if (!cameraModes.length) cameraModes = [...facingModes];
    console.info('[broadcast/camera] modes built', cameraModes);
    return cameraModes;
  }

  async function openCameraMode(mode) {
    if (mode.kind === 'facing') {
      try {
        if (mode.facingMode === 'user') console.info('[broadcast/camera] switching facing=user exact');
        if (mode.facingMode === 'environment') console.info('[broadcast/camera] switching facing=environment exact');
        const exactStream = await requestCameraStream({ facingMode: { exact: mode.facingMode } });
        console.info('[broadcast/camera] active facing result', { facingMode: mode.facingMode, strategy: 'exact' });
        return exactStream;
      } catch (_) {
        if (mode.facingMode === 'user') console.info('[broadcast/camera] switching facing=user ideal');
        if (mode.facingMode === 'environment') console.info('[broadcast/camera] switching facing=environment ideal');
        const idealStream = await requestCameraStream({ facingMode: { ideal: mode.facingMode } });
        console.info('[broadcast/camera] active facing result', { facingMode: mode.facingMode, strategy: 'ideal' });
        return idealStream;
      }
    }
    console.info(`[broadcast/camera] switching to deviceId=${mode.deviceId}`);
    try {
      return await requestCameraStream({ deviceId: { exact: mode.deviceId } });
    } catch (_) {
      return requestCameraStream({ deviceId: { ideal: mode.deviceId } });
    }
  }

  async function startCameraStream() {
    if (state.camStream) {
      const activeTrack = state.camStream.getVideoTracks()[0];
      const activeDeviceId = activeTrack?.getSettings?.().deviceId || '';
      if (!selectedVideoDeviceId || selectedVideoDeviceId === activeDeviceId) {
        return state.camStream;
      }
      state.camStream.getTracks().forEach((t) => t.stop());
      state.camStream = null;
    }
    const attempts = [];
    if (selectedVideoDeviceId) attempts.push({ deviceId: { exact: selectedVideoDeviceId } });
    attempts.push({ facingMode: { ideal: preferredFacingMode } });
    attempts.push({ facingMode: { ideal: 'user' } });
    attempts.push(true);
    let stream = null;
    let lastErr = null;
    for (const c of attempts) {
      try {
        stream = await requestCameraStream(c);
        break;
      } catch (err) {
        lastErr = err;
        console.info('[broadcast/camera] getUserMedia attempt failed', { constraint: c, message: err?.message || String(err) });
      }
    }
    if (!stream) throw lastErr || new Error('camera unavailable');
    state.camStream = stream;
    ensureProgramStream();
    const track = state.camStream.getVideoTracks()[0];
    camSourceEl.srcObject = state.camStream;
    camSourceEl.play().catch(() => {});
    selectedVideoDeviceId = track?.getSettings?.().deviceId || selectedVideoDeviceId;
    const facing = track?.getSettings?.().facingMode;
    if (facing === 'environment' || facing === 'user') preferredFacingMode = facing;
    console.info('[broadcast/camera] active track', { label: track?.label || '', deviceId: selectedVideoDeviceId, facingMode: preferredFacingMode });
    updateCameraLabel(track?.label || 'camera');
    return state.camStream;
  }

  async function refreshVideoInputs() {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      cachedVideoInputs = devices.filter((d) => d.kind === 'videoinput');
    } catch {
      cachedVideoInputs = [];
    }
    console.info('[broadcast/camera] enumerate devices', { count: cachedVideoInputs.length, labelsReady: cachedVideoInputs.some((d) => !!d.label) });
    return cachedVideoInputs;
  }

  async function cycleCameraDevice() {
    if (!cachedVideoInputs.length || cachedVideoInputs.every((d) => !d.label)) {
      try {
        if (!state.camStream) await startCameraStream();
      } catch (_) {}
    }
    const inputs = await refreshVideoInputs();
    if (!inputs.length) {
      state.media.camera_enabled = !state.media.camera_enabled;
      await syncTracks();
      announceState();
      return;
    }
    if (isTouchLikeDevice()) {
      const nextFacing = preferredFacingMode === 'user' ? 'environment' : 'user';
      preferredFacingMode = nextFacing;
      selectedVideoDeviceId = '';
      state.media.camera_enabled = true;
      const old = state.camStream;
      state.camStream = null;
      try {
        await syncTracks();
        old?.getTracks?.().forEach((t) => t.stop());
        announceState();
        console.info('[broadcast/camera] switched facing mode', { facingMode: preferredFacingMode });
        return;
      } catch (err) {
        console.warn('[broadcast/camera] facing switch failed, falling back to device cycle', { message: err?.message || String(err) });
        if (old) state.camStream = old;
      }
    }
    const idx = inputs.findIndex((d) => d.deviceId === selectedVideoDeviceId);
    cameraCycleIndex = idx >= 0 ? idx : cameraCycleIndex;
    cameraCycleIndex = (cameraCycleIndex + 1) % inputs.length;
    selectedVideoDeviceId = inputs[cameraCycleIndex].deviceId;
    state.media.camera_enabled = true;
    const old = state.camStream;
    state.camStream = null;
    await syncTracks();
    old?.getTracks?.().forEach((t) => t.stop());
    updateCameraLabel(inputs[cameraCycleIndex].label || `camera ${cameraCycleIndex + 1}`);
    console.info('[broadcast/camera] cycled device', { deviceId: selectedVideoDeviceId, label: inputs[cameraCycleIndex].label || '' });
    announceState();
  }

  async function startScreenStream() {
    if (state.screenStream) return state.screenStream;
    state.screenStream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
    console.info('[broadcast/screen] screen stream started');
    state.screenStream.getVideoTracks().forEach((t) => t.addEventListener('ended', () => {
      if (!state.media.screen_enabled) return;
      state.media.screen_enabled = false;
      console.info('[broadcast/screen] native screen-share ended; returning to camera');
      pip.enabled = false;
      console.info('[broadcast/pip] disabled');
      switchToCamera().catch(() => announceState());
    }));
    ensureProgramStream();
    screenSourceEl.srcObject = state.screenStream;
    screenSourceEl.play().catch(() => {});
    return state.screenStream;
  }

  function ensureProgramCanvas() {
    if (programCanvas) return;
    programCanvas = document.createElement('canvas');
    programCanvas.width = 1280;
    programCanvas.height = 720;
    programCtx = programCanvas.getContext('2d');
  }
  function ensureProgramStream() {
    ensureProgramCanvas();
    startProgramLoop();

    if (!programStream) {
      programStream = programCanvas.captureStream(30);
      programVideoTrack = programStream.getVideoTracks()[0] || null;
      console.info('[broadcast/program] stream ready');
    }

    if (dom.preview && dom.preview.srcObject !== programStream) {
      dom.preview.srcObject = programStream;
      dom.preview.muted = true;
      dom.preview.playsInline = true;
      dom.preview.play?.().catch(() => {});
      console.info('[broadcast/program] preview using program stream');
    }

    return programStream;
  }

  function drawProgramFrame() {
    if (!programCtx || !programCanvas) return;
    const stage = dom.preview?.parentElement;
    const w = stage?.clientWidth || 1280;
    const h = stage?.clientHeight || 720;
    if (programCanvas.width !== w || programCanvas.height !== h) {
      programCanvas.width = w;
      programCanvas.height = h;
    }
    programCtx.fillStyle = '#000';
    programCtx.fillRect(0, 0, programCanvas.width, programCanvas.height);
    const mainEl = state.media.screen_enabled ? screenSourceEl : camSourceEl;
    if (mainEl?.readyState >= 2) {
      try { programCtx.drawImage(mainEl, 0, 0, programCanvas.width, programCanvas.height); } catch (_) {}
    }
    if (state.media.screen_enabled && pip.enabled && camSourceEl.readyState >= 2) {
      try {
        programCtx.fillStyle = 'rgba(0,0,0,0.45)';
        programCtx.fillRect(pip.x - 2, pip.y - 2, pip.w + 4, pip.h + 4);
        programCtx.drawImage(camSourceEl, pip.x, pip.y, pip.w, pip.h);
      } catch (_) {}
    }
  }

  function startProgramLoop() {
    if (programLoopRunning) return;
    ensureProgramCanvas();
    programLoopRunning = true;
    const tick = () => {
      if (!programLoopRunning) return;
      drawProgramFrame();
      programLoopHandle = requestAnimationFrame(tick);
    };
    programLoopHandle = requestAnimationFrame(tick);
  }

  async function ensurePeerConnection(viewerId = null) {
    if (!viewerId && state.pc) return state.pc;
    if (viewerId && state.peerConnections[viewerId]) return state.peerConnections[viewerId];
    const iceCfg = await fetch(cfg.iceConfigUrl || '/webrtc/ice-config').then((r) => r.json()).catch(() => ({ iceServers: [{ urls: 'stun:stun.l.google.com:19302' }] }));
    const pc = new RTCPeerConnection({ iceServers: iceCfg.iceServers || [{ urls: 'stun:stun.l.google.com:19302' }] });
    if (viewerId) state.peerConnections[viewerId] = pc;
    else state.pc = pc;
    pc.onicecandidate = (e) => {
      if (!e.candidate) return;
      if (viewerId) sendJson(state.signalWs, 'ice-candidate', { viewerId, candidate: e.candidate });
      else sendJson(state.signalWs, 'webrtc_ice', { candidate: e.candidate });
    };
    pc.onconnectionstatechange = () => dom.stPc && (dom.stPc.textContent = pc.connectionState);
    pc.oniceconnectionstatechange = () => dom.stIce && (dom.stIce.textContent = pc.iceConnectionState);
    if (viewerId) {
      const ps = ensureProgramStream();
      const vtrack = programVideoTrack || ps.getVideoTracks()[0] || null;
      if (vtrack) pc.addTrack(vtrack, ps);
      if (state.media.mic_enabled) {
        const atrack = state.camStream?.getAudioTracks?.()[0] || null;
        if (atrack) pc.addTrack(atrack, state.camStream);
      }
      console.info('[broadcast/program] sender using program video track');
    }
    return pc;
  }

  async function createOfferForViewer(viewerId) {
    const pc = await ensurePeerConnection(viewerId);
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    sendJson(state.signalWs, 'offer', { viewerId, sdp: offer.sdp, type: offer.type });
  }

  function removeViewerPeer(viewerId) {
    const pc = state.peerConnections[viewerId];
    if (!pc) return;
    try { pc.close(); } catch (_) {}
    delete state.peerConnections[viewerId];
  }

  async function replaceOutgoingVideoTrack(newTrack) {
    for (const pc of Object.values(state.peerConnections)) {
      const sender = pc.getSenders().find((s) => s.track && s.track.kind === 'video');
      if (sender) await sender.replaceTrack(newTrack || null);
    }
  }

  async function replaceOutgoingAudioTrack(newTrack) {
    for (const pc of Object.values(state.peerConnections)) {
      const sender = pc.getSenders().find((s) => s.track && s.track.kind === 'audio');
      if (sender) await sender.replaceTrack(newTrack || null);
    }
  }

  async function syncTracks() {
    startProgramLoop();
    if (state.media.screen_enabled) {
      const screen = await startScreenStream();
      const ps = ensureProgramStream();
      await replaceOutgoingVideoTrack(programVideoTrack || ps.getVideoTracks()[0] || screen.getVideoTracks()[0] || null);
      console.info('[broadcast/program] sender using program video track');
    } else {
      const cam = await startCameraStream();
      const ps = ensureProgramStream();
      await replaceOutgoingVideoTrack(state.media.camera_enabled ? (programVideoTrack || ps.getVideoTracks()[0] || cam.getVideoTracks()[0] || null) : null);
      console.info('[broadcast/program] sender using program video track');
    }
    if (state.media.mic_enabled) {
      const cam = await startCameraStream();
      await replaceOutgoingAudioTrack(cam.getAudioTracks()[0] || null);
    } else {
      await replaceOutgoingAudioTrack(null);
    }
  }

  async function switchToScreen() {
    state.media.screen_enabled = true;
    pip.enabled = true;
    console.info('[broadcast/pip] enabled');
    await syncTracks();
    console.info('[broadcast/screen] switched to screen mode with camera PiP');
    announceState();
  }

  async function switchToCamera() {
    state.media.screen_enabled = false;
    pip.enabled = false;
    console.info('[broadcast/pip] disabled');
    if (state.screenStream) {
      state.screenStream.getTracks().forEach((t) => t.stop());
      state.screenStream = null;
    }
    await syncTracks();
    ensureProgramStream();
    console.info('[broadcast/screen] switched back to camera mode');
    announceState();
  }

  const STT_TARGET_SAMPLE_RATE = 16000;
  const STT_TARGET_CHANNELS = 1;

  function stopSpeechCapture() {
    if (state.speechProcessor) {
      try { state.speechProcessor.disconnect(); } catch (_) {}
      state.speechProcessor.onaudioprocess = null;
      state.speechProcessor = null;
    }
    if (state.speechSource) {
      try { state.speechSource.disconnect(); } catch (_) {}
      state.speechSource = null;
    }
    if (state.speechCtx) {
      try { state.speechCtx.close(); } catch (_) {}
      state.speechCtx = null;
    }
  }

  async function playAiVoice(url) {
    if (!url || !state.media.hear_ai_voice) return;
    try {
      if (activeAiAudio) {
        activeAiAudio.pause();
        activeAiAudio.src = '';
        activeAiAudio = null;
        console.info('[broadcast/ai] stopped previous AI audio');
      }
      if ('speechSynthesis' in window) window.speechSynthesis.cancel();
      const audio = new Audio(url);
      audio.volume = 0.9;
      activeAiAudio = audio;
      audio.onended = () => { if (activeAiAudio === audio) activeAiAudio = null; };
      await audio.play();
      console.info('[broadcast/ai] AI voice started');
    } catch (_) {}
  }

  function currentProgramStream() {
    const ps = ensureProgramStream();
    const tracks = [];
    const videoTrack = programVideoTrack || ps.getVideoTracks()[0];
    if (videoTrack) tracks.push(videoTrack);
    const audioTrack = state.camStream?.getAudioTracks?.()[0];
    if (audioTrack) tracks.push(audioTrack);
    return tracks.length ? new MediaStream(tracks) : null;
  }

  async function uploadRecording(blob) {
    const fd = new FormData();
    fd.append('file', new File([blob], `broadcast-${Date.now()}.webm`, { type: blob.type || 'video/webm' }));
    const resp = await fetch(`/api/broadcast/recording?room=${encodeURIComponent(state.room)}`, { method: 'POST', body: fd });
    const payload = await resp.json().catch(() => ({}));
    if (!resp.ok || !payload?.ok) throw new Error(payload?.error || `record upload failed (${resp.status})`);
    return payload;
  }

  async function toggleRecording() {
    if (recordingMedia && recordingMedia.state === 'recording') {
      recordingMedia.stop();
      state.media.record_enabled = false;
      announceState();
      return;
    }
    const stream = currentProgramStream();
    if (!stream) {
      if (dom.recordingStatus) dom.recordingStatus.textContent = 'Record unavailable: no active camera/screen';
      return;
    }
    recordingChunks = [];
    recordingStream = stream;
    recordingMedia = new MediaRecorder(stream, getPreferredRecorderOptions());
    recordingMedia.ondataavailable = (ev) => { if (ev.data?.size) recordingChunks.push(ev.data); };
    recordingMedia.onstop = async () => {
      const blob = new Blob(recordingChunks, { type: 'video/webm' });
      recordingChunks = [];
      recordingStream?.getAudioTracks?.().forEach((t) => t.stop());
      recordingStream = null;
      const filename = timestampedRecordingName();
      const href = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = href;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(href);
      console.info('[broadcast/record] auto-downloaded recording', { filename, size: blob.size });
      if (dom.recordingStatus) dom.recordingStatus.textContent = `Saved ${filename}`;
      return;
    };
    recordingMedia.start(1000);
    console.info('[broadcast/record] recording started');
    state.media.record_enabled = true;
    if (dom.recordingStatus) dom.recordingStatus.textContent = 'Recording live…';
    announceState();
  }

  async function toggleRtmp() {
    const next = !state.media.rtmp_enabled;
    const streamKey = (dom.rtmpKeyInput?.value || '').trim();
    const res = await fetch('/api/broadcast/rtmp', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ room: state.room, enabled: next, stream_key: streamKey }),
    }).then((r) => r.json()).catch(() => ({ ok: false }));
    if (!res.ok) return;
    state.media.rtmp_enabled = !!res.enabled;
    state.media.rtmp_url = res.rtmp_url || '';
    announceState();
  }

  function sendAudioChunk(b64, sampleRate) {
    sendJson(state.chatWs, 'audio_chunk', {
      encoding: 'linear16',
      channels: STT_TARGET_CHANNELS,
      sampleRate,
      data: b64,
    });
  }

  function floatToInt16(input) {
    const out = new Int16Array(input.length);
    for (let i = 0; i < input.length; i += 1) {
      const s = Math.max(-1, Math.min(1, input[i]));
      out[i] = s < 0 ? Math.round(s * 0x8000) : Math.round(s * 0x7fff);
    }
    return out;
  }

  function downsampleBuffer(input, inputRate, outputRate) {
    if (outputRate === inputRate) return input;
    const ratio = inputRate / outputRate;
    const outLength = Math.max(1, Math.round(input.length / ratio));
    const out = new Float32Array(outLength);
    let outOffset = 0;
    let inOffset = 0;
    while (outOffset < outLength) {
      const nextOffset = Math.min(input.length, Math.round((outOffset + 1) * ratio));
      let acc = 0;
      let count = 0;
      for (let i = inOffset; i < nextOffset; i += 1) {
        acc += input[i];
        count += 1;
      }
      out[outOffset] = count > 0 ? acc / count : 0;
      outOffset += 1;
      inOffset = nextOffset;
    }
    return out;
  }

  function int16ToBase64(samples) {
    const bytes = new Uint8Array(samples.buffer);
    let binary = '';
    const chunkSize = 0x8000;
    for (let i = 0; i < bytes.length; i += chunkSize) {
      binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
    }
    return btoa(binary);
  }

  async function startSpeechCaptureFromMic() {
    stopSpeechCapture();
    if (!state.media.stt_enabled || !state.media.mic_enabled) return;
    const cam = await startCameraStream();
    const track = cam.getAudioTracks()[0];
    if (!track) return;

    const sttStream = new MediaStream([track.clone()]);
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;

    const ctx = new Ctx({ sampleRate: STT_TARGET_SAMPLE_RATE });
    const source = ctx.createMediaStreamSource(sttStream);
    const processor = ctx.createScriptProcessor(4096, 1, 1);

    processor.onaudioprocess = (event) => {
    if (!state.chatWs || state.chatWs.readyState !== WebSocket.OPEN) return;
      const now = Date.now();
      sttFrameModulo = (sttFrameModulo + 1) % 3;
      if (sttFrameModulo !== 0 || (now - lastSttSentAt) < 120) return;
      const input = event.inputBuffer.getChannelData(0);
      const reduced = downsampleBuffer(input, ctx.sampleRate, STT_TARGET_SAMPLE_RATE);
      const pcm = floatToInt16(reduced);
      if (!pcm.length) return;
      sendAudioChunk(int16ToBase64(pcm), STT_TARGET_SAMPLE_RATE);
      lastSttSentAt = now;
    };

    source.connect(processor);
    processor.connect(ctx.destination);

    state.speechCtx = ctx;
    state.speechSource = source;
    state.speechProcessor = processor;
  }

  function connectChat() {
    const ws = new WebSocket(`${wsBase}/ws/chat`);
    state.chatWs = ws;
    ws.onopen = () => {
      chatRetryMs = 1200;
      updateConnectivity(true);
      sendJson(ws, 'join', { role: 'participant' });
      startSpeechCaptureFromMic().catch(() => {});
    };
    ws.onmessage = (ev) => {
      let msg; try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.type === 'state_sync' || msg.type === 'state_update') applyRoomState(msg.state || {});
      if (msg.type === 'presence') applyPresence(msg);
      if (msg.type === 'ai_status') updateAiStatus(msg.status || 'idle');
      if (['chat', 'ai', 'attachment'].includes(msg.type)) appendChat(msg);
      if (msg.type === 'ai' && msg.voice) playAiVoice(msg.voice);
      if (msg.type === 'web_search_result') {
        renderSearchResults(msg.query || '', msg.result || {});
      }
    };
    ws.onclose = () => {
      updateConnectivity(false);
      stopSpeechCapture();
      setTimeout(connectChat, chatRetryMs);
      chatRetryMs = Math.min(15000, Math.round(chatRetryMs * 1.7));
    };
  }

  function connectSignal() {
    const ws = new WebSocket(`${wsBase}/ws/broadcast`);
    state.signalWs = ws;
    ws.onopen = async () => {
      signalRetryMs = 1200;
      sendJson(ws, 'join', { role: 'broadcaster' });
      await syncTracks();
      sendJson(ws, 'media_ready');
    };
    ws.onmessage = async (ev) => {
      let msg; try { msg = JSON.parse(ev.data); } catch { return; }
      if (msg.type === 'viewer_joined' && msg.viewerId) {
        await createOfferForViewer(msg.viewerId);
      }
      if (msg.type === 'viewer_left' && msg.viewerId) {
        removeViewerPeer(msg.viewerId);
      }
      if (msg.type === 'answer' && msg.viewerId && msg.payload?.sdp) {
        const pc = state.peerConnections[msg.viewerId];
        if (pc) await pc.setRemoteDescription({ type: msg.payload.type || 'answer', sdp: msg.payload.sdp });
      }
      if (msg.type === 'ice-candidate' && msg.viewerId && msg.candidate) {
        const pc = state.peerConnections[msg.viewerId];
        if (pc) {
          try { await pc.addIceCandidate(msg.candidate); } catch (_) {}
        }
      }
      if (msg.type === 'webrtc_answer' && msg.sdp && state.pc) {
        await state.pc.setRemoteDescription({ type: msg.answerType || 'answer', sdp: msg.sdp });
      }
      if (msg.type === 'presence') applyPresence(msg);
      if (msg.type === 'state_sync' || msg.type === 'state_update') applyRoomState(msg.state || {});
    };
    ws.onclose = () => {
      Object.keys(state.peerConnections).forEach(removeViewerPeer);
      setTimeout(connectSignal, signalRetryMs);
      signalRetryMs = Math.min(15000, Math.round(signalRetryMs * 1.7));
    };
  }

  function announceState() {
    sendJson(state.chatWs, 'toggle_state', { state: state.media });
    sendJson(state.signalWs, 'toggle_state', { state: state.media });
    sendJson(state.signalWs, 'set_media_mode', { camera: state.media.camera_enabled, screen: state.media.screen_enabled, mic: state.media.mic_enabled });
    applyRoomState({ settings: state.media, runtime: { broadcaster_present: true, viewer_count: Number(dom.stWatchers?.textContent || 0) } });
  }

  function sendChatMessage() {
    const text = dom.chatInput?.value?.trim();
    if (!text) return;
    const now = Date.now();
    if (text === lastChatText && (now - lastChatSendAt) < 400) return;
    lastChatText = text;
    lastChatSendAt = now;
    if (DEBUG_CHAT) console.debug('[broadcast.chat] send', { chars: text.length });
    sendJson(state.chatWs, 'chat', { text });
    dom.chatInput.value = '';
  }

  dom.sendBtn?.addEventListener('click', sendChatMessage);
  dom.chatInput?.addEventListener('keydown', (ev) => {
    if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); sendChatMessage(); }
  });

  dom.webBtn?.addEventListener('click', () => {
    const query = (dom.chatInput?.value || '').trim();
    if (!query) return;
    if (DEBUG_CHAT) console.debug('[broadcast.chat] web_search send', { query_len: query.length });
    sendJson(state.chatWs, 'web_search', { query });
  });
  dom.searchCloseBtn?.addEventListener('click', () => dom.searchPane?.classList.remove('open'));

  dom.attachBtn?.addEventListener('click', () => dom.fileInput?.click());
  dom.fileInput?.addEventListener('change', async () => {
    const f = dom.fileInput.files?.[0];
    if (!f) return;
    const fd = new FormData(); fd.append('file', f);
    const res = await fetch('/api/upload', { method: 'POST', body: fd }).then((r) => r.json()).catch(() => ({}));
    sendJson(state.chatWs, 'attachment_uploaded', { attachment: { url: res.url || '', name: f.name, mime: f.type, size: f.size } });
    dom.fileInput.value = '';
  });

  dom.camBtn?.addEventListener('click', async () => {
    const modes = await buildCameraModes();
    if (!modes.length) return;
    cameraModeIndex = (cameraModeIndex + 1) % modes.length;
    const mode = modes[cameraModeIndex];
    const old = state.camStream;
    try {
      const next = await openCameraMode(mode);
      state.camStream = next;
      const track = next.getVideoTracks()[0];
      selectedVideoDeviceId = track?.getSettings?.().deviceId || selectedVideoDeviceId;
      const facing = track?.getSettings?.().facingMode;
      if (facing === 'environment' || facing === 'user') preferredFacingMode = facing;
      camSourceEl.srcObject = next;
      camSourceEl.play().catch(() => {});
      updateCameraLabel(track?.label || mode.label || 'camera');
      await syncTracks();
      old?.getVideoTracks?.().forEach((t) => t.stop());
      announceState();
    } catch (err) {
      console.warn('[broadcast/camera] fallback after failure', { mode, message: err?.message || String(err) });
      await cycleCameraDevice();
    }
  });
  dom.screenBtn?.addEventListener('click', async () => {
    if (state.media.screen_enabled) await switchToCamera(); else await switchToScreen();
  });
  dom.micBtn?.addEventListener('click', async () => {
    state.media.mic_enabled = !state.media.mic_enabled;
    await syncTracks();
    if (state.media.mic_enabled && state.media.stt_enabled) await startSpeechCaptureFromMic();
    else stopSpeechCapture();
    announceState();
  });
  dom.sttBtn?.addEventListener('click', async () => {
    state.media.stt_enabled = !state.media.stt_enabled;
    if (state.media.stt_enabled && state.media.mic_enabled) await startSpeechCaptureFromMic();
    else stopSpeechCapture();
    announceState();
  });
  dom.ncBtn?.addEventListener('click', async () => {
    state.media.noise_cancel_enabled = !state.media.noise_cancel_enabled;
    if (state.camStream) { state.camStream.getTracks().forEach((t) => t.stop()); state.camStream = null; }
    await syncTracks();
    if (state.media.stt_enabled && state.media.mic_enabled) await startSpeechCaptureFromMic();
    announceState();
  });
  dom.aiEnableBtn?.addEventListener('click', () => { state.media.ai_enabled = !state.media.ai_enabled; announceState(); });
  dom.ttsMonBtn?.addEventListener('click', () => { state.media.hear_ai_voice = !state.media.hear_ai_voice; announceState(); });
  dom.recordBtn?.addEventListener('click', () => { toggleRecording().catch(() => {}); });
  dom.rtmpBtn?.addEventListener('click', () => { toggleRtmp().catch(() => {}); });
  const pointerDown = (ev) => {
    if (!state.media.screen_enabled) return;
    const rect = dom.preview?.getBoundingClientRect();
    if (!rect || !programCanvas) return;
    const scaleX = programCanvas.width / rect.width;
    const scaleY = programCanvas.height / rect.height;
    const x = ((ev.clientX ?? ev.touches?.[0]?.clientX) - rect.left) * scaleX;
    const y = ((ev.clientY ?? ev.touches?.[0]?.clientY) - rect.top) * scaleY;
    const inside = x >= pip.x && x <= (pip.x + pip.w) && y >= pip.y && y <= (pip.y + pip.h);
    if (!inside) return;
    pip.dragging = true;
    pip.dragDx = x - pip.x;
    pip.dragDy = y - pip.y;
    console.info('[broadcast/pip] drag start');
  };
  const pointerMove = (ev) => {
    if (!pip.dragging) return;
    const rect = dom.preview?.getBoundingClientRect();
    if (!rect || !programCanvas) return;
    const scaleX = programCanvas.width / rect.width;
    const scaleY = programCanvas.height / rect.height;
    const x = ((ev.clientX ?? ev.touches?.[0]?.clientX) - rect.left) * scaleX;
    const y = ((ev.clientY ?? ev.touches?.[0]?.clientY) - rect.top) * scaleY;
    pip.x = Math.max(0, Math.min((programCanvas.width - pip.w), x - pip.dragDx));
    pip.y = Math.max(0, Math.min((programCanvas.height - pip.h), y - pip.dragDy));
    console.info('[broadcast/pip] moved', { x: pip.x, y: pip.y });
  };
  const pointerUp = () => {
    if (!pip.dragging) return;
    pip.dragging = false;
    console.info('[broadcast/pip] drag end', { x: pip.x, y: pip.y });
  };
  dom.preview?.addEventListener('pointerdown', pointerDown);
  window.addEventListener('pointermove', pointerMove, { passive: true });
  window.addEventListener('pointerup', pointerUp, { passive: true });
  dom.preview?.addEventListener('pointercancel', pointerUp);
  window.addEventListener('mousedown', pointerDown, { passive: true });
  window.addEventListener('mousemove', pointerMove, { passive: true });
  window.addEventListener('mouseup', pointerUp, { passive: true });
  dom.preview?.addEventListener('touchstart', pointerDown, { passive: true });
  window.addEventListener('touchmove', pointerMove, { passive: true });
  window.addEventListener('touchend', pointerUp, { passive: true });
  dom.chatCollapseBtn?.addEventListener('click', () => {
    if (!dom.chatPanel) return;
    dom.chatPanel.classList.toggle('collapsed');
    dom.chatCollapseBtn.textContent = dom.chatPanel.classList.contains('collapsed') ? 'Expand' : 'Collapse';
  });

  if (window.matchMedia && window.matchMedia('(max-width: 980px)').matches && dom.chatPanel) {
    dom.chatPanel.classList.add('collapsed');
    if (dom.chatCollapseBtn) dom.chatCollapseBtn.textContent = 'Expand';
  }
  applyRoomState({ settings: state.media, runtime: { broadcaster_present: false, viewer_count: 0 } });
  ensureProgramStream();
  installWakeLock();
  connectChat();
  connectSignal();

  // Best effort startup: UI stays ON even if browser prompts for permissions first.
  startCameraStream().then(refreshVideoInputs).then(syncTracks).then(() => { announceState(); startSpeechCaptureFromMic().catch(() => {}); }).catch(() => announceState());
})();
