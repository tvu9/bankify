import { Room, RoomEvent, Track, createLocalAudioTrack } from 'livekit-client';
import './style.css';

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const roleQuery = params.get('role');
// Opt-in telephone test profile; keep AEC to prevent feedback.
const preserveAudio = params.get('audio') === 'preserve';
let selectedRole = roleQuery === 'receiver' ? 'receiver' : 'caller';
let room = null;
let connectedAt = 0;
let timer = null;
let speakerEnabled = true;
let joined = false;
let connecting = false;
const audioElements = new Map();

const ICONS = {
  lock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>',
  mic: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v4"/></svg>',
  micOff: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3l18 18M9 9v1a3 3 0 0 0 5.1 2.1M15 9.3V5a3 3 0 0 0-5.7-1.3"/><path d="M5 10a7 7 0 0 0 11.6 5.3M19 10a7 7 0 0 1-.5 2.6M12 17v4"/></svg>',
  speaker: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9v6h4l5 4V5L8 9H4z"/><path d="M16.5 8.5a5 5 0 0 1 0 7M19 6a8.5 8.5 0 0 1 0 12"/></svg>',
  speakerOff: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 9v6h4l5 4V5L8 9H4z"/><path d="M17 9l5 6M22 9l-5 6"/></svg>',
  phone: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M6.6 10.8a15.1 15.1 0 0 0 6.6 6.6l2.2-2.2a1 1 0 0 1 1-.25 11.4 11.4 0 0 0 3.6.57 1 1 0 0 1 1 1V20a1 1 0 0 1-1 1A17 17 0 0 1 3 4a1 1 0 0 1 1-1h3.5a1 1 0 0 1 1 1c0 1.25.2 2.45.57 3.57a1 1 0 0 1-.25 1L6.6 10.8z"/></svg>',
  shield: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z"/></svg>',
};

$('app').innerHTML = `
<main class="call-screen">
  <header class="call-top">
    <div class="e2e">${ICONS.lock}<span>Sentrix · Encrypted audio call</span></div>
    <span class="connection-tag" id="connection-tag"><span class="status-dot"></span><span id="top-status">Ready</span></span>
  </header>

  <section class="peer" aria-label="Call status">
    <h1 id="peer-title">Receiver</h1>
    <p class="peer-subtitle" id="peer-subtitle">Waiting to start a call</p>
    <div class="timer" id="call-timer">00:00</div>
    <div class="avatar" aria-hidden="true">
      <svg viewBox="0 0 80 80" fill="currentColor"><circle cx="40" cy="29" r="14"/><path d="M14 72c0-15 11.5-24 26-24s26 9 26 24z"/></svg>
    </div>
    <div class="wave" id="wave" aria-label="Audio activity"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
  </section>

  <section class="feed" aria-label="Call safety">
    <div class="notice" id="info" role="status" aria-live="polite"></div>

    <article class="card" id="combined-panel" aria-live="polite">
      <div class="card-head"><span class="card-title">${ICONS.shield}Call safety</span><span class="pill">Unverified</span></div>
      <p class="card-message" id="combined-message">Monitoring both signals. No result establishes that the caller is safe.</p>
      <p class="card-note">Voice authenticity and scam-language cues are separate signals. Verify through a channel you already trust.</p>
    </article>

    <article class="card" id="detector-panel" aria-live="polite">
      <div class="card-head"><span class="card-title">Voice analysis</span><span class="pill" id="detector-state">Offline</span></div>
      <p class="card-message" id="detector-message">Waiting for the PellaV2 detection worker…</p>
      <p class="card-meta" id="detector-score">No analysis yet</p>
      <p class="card-meta" id="audio-quality">Audio: waiting for caller</p>
      <p class="card-note">Experimental model output. Not a calibrated probability or proof of identity.</p>
    </article>

    <article class="card" id="fraud-panel" aria-live="polite">
      <div class="card-head"><span class="card-title">Conversation screening</span><span class="pill" id="fraud-state">Offline</span></div>
      <p class="card-message" id="fraud-message">Transcription worker not connected</p>
      <p class="card-meta" id="fraud-indicators">No scam-language evidence yet</p>
      <p class="card-meta" id="fraud-identity">Identity: not independently verified</p>
      <p class="card-note">No match doesn't mean a call is safe. Never share codes or move money based only on a call.</p>
    </article>
  </section>

  <footer class="call-bar">
    <div class="role-switch" role="group" aria-label="This phone is">
      <button id="role-caller" class="role-btn" type="button">Caller</button>
      <button id="role-receiver" class="role-btn" type="button">Receiver</button>
    </div>
    <div class="controls">
      <button id="speaker-btn" class="control active" type="button" disabled aria-label="Toggle speaker">
        <span class="control-icon" id="speaker-icon">${ICONS.speaker}</span><span class="control-label" id="speaker-label">Speaker on</span>
      </button>
      <button id="mute-btn" class="control" type="button" disabled aria-label="Mute microphone">
        <span class="control-icon" id="mic-icon">${ICONS.mic}</span><span class="control-label" id="mute-label">Mute</span>
      </button>
      <button type="button" id="join-btn" class="control call-btn" aria-label="Start audio call">
        <span class="control-icon" id="join-icon">${ICONS.phone}</span><span class="control-label" id="join-label">Call</span>
      </button>
    </div>
  </footer>
  <div id="audio-container" aria-hidden="true"></div>
</main>`;

function setInfo(message, isError = false) { $('info').textContent = message; $('info').classList.toggle('error', isError); }
function formatElapsed(seconds) { const m = Math.floor(seconds / 60); const s = seconds % 60; return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`; }
function updateTimer() { $('call-timer').textContent = connectedAt ? formatElapsed(Math.floor((Date.now() - connectedAt) / 1000)) : '00:00'; }
function updateRole() {
  $('role-caller').classList.toggle('selected', selectedRole === 'caller');
  $('role-receiver').classList.toggle('selected', selectedRole === 'receiver');
  $('peer-title').textContent = selectedRole === 'caller' ? 'Receiver' : 'Caller';
  $('role-caller').disabled = joined || connecting;
  $('role-receiver').disabled = joined || connecting;
  const url = new URL(location.href); url.searchParams.set('role', selectedRole); history.replaceState(null, '', url);
}
function setState(state) {
  const busy = state === 'connecting'; joined = state === 'connected'; connecting = busy;
  $('join-btn').disabled = busy;
  $('join-label').textContent = busy ? 'Connecting' : joined ? 'End' : 'Call';
  $('join-btn').setAttribute('aria-label', joined ? 'Hang up' : 'Start audio call');
  $('join-icon').innerHTML = ICONS.phone;
  document.body.dataset.call = state;
  $('join-btn').classList.toggle('hangup', joined);
  $('mute-btn').disabled = !joined;
  $('speaker-btn').disabled = !joined;
  $('top-status').textContent = busy ? 'Connecting' : joined ? 'Connected' : 'Ready';
  $('connection-tag').classList.toggle('connected', joined);
  $('wave').classList.toggle('animated', joined);
  updateRole();
  if (!joined) { clearInterval(timer); timer = null; connectedAt = 0; updateTimer(); }
}
function refreshPeerStatus() {
  if (!room || !joined) return;
  const peer = [...room.remoteParticipants.values()].find(p => p.identity === (selectedRole === 'caller' ? 'receiver' : 'caller'));
  $('peer-subtitle').textContent = peer ? 'Audio call connected' : 'Waiting for other phone to join';
  if (peer) setInfo('Connected. You can hear and speak to the other phone.');
  else setInfo('Connected to LiveKit. Waiting for the other phone to join.');
}
function detachAll() { for (const [track, el] of audioElements) { try { track.detach(el); el.remove(); } catch {} } audioElements.clear(); }
function attachTrack(track, _publication, participant) {
  if (track.kind !== Track.Kind.Audio || !['caller','receiver'].includes(participant.identity)) return;
  if (audioElements.has(track)) return;
  const el = track.attach(); el.autoplay = true; el.playsInline = true; el.muted = !speakerEnabled;
  $('audio-container').appendChild(el); audioElements.set(track, el);
  el.play().catch(() => setInfo('Tap Speaker to enable sound. Mobile browsers may require an extra tap.', true));
}
function detachTrack(track) { const el = audioElements.get(track); if (el) { track.detach(el); el.remove(); audioElements.delete(track); } }
async function startCall() {
  setState('connecting');
  setInfo('Requesting microphone permission…');
  let micTrack = null;
  let phase = 'microphone';
  try {
    // This call is invoked immediately in the button's click event, before
    // token-fetch and network awaits. Important for permission on iOS Safari.
    micTrack = await createLocalAudioTrack({
      echoCancellation: true, noiseSuppression: !preserveAudio, autoGainControl: !preserveAudio,
    });
    phase = 'token';
    setInfo(preserveAudio ? 'Audio preservation test mode (AEC on, NS/AGC requested off). Getting credentials…' : 'Microphone ready. Getting call credentials…');
    const response = await fetch(`/api/token?role=${encodeURIComponent(selectedRole)}`, { cache: 'no-store' });
    const payload = await response.json();
    if (!response.ok) throw Error(payload.error || `Token request failed (${response.status})`);
    phase = 'connection';
    const newRoom = new Room({
      adaptiveStream: false, dynacast: false,
      singlePeerConnection: false,
    });
    room = newRoom;
    newRoom.on(RoomEvent.TrackSubscribed, attachTrack);
    newRoom.on(RoomEvent.TrackUnsubscribed, detachTrack);
    newRoom.on(RoomEvent.ParticipantConnected, refreshPeerStatus);
    newRoom.on(RoomEvent.ParticipantDisconnected, refreshPeerStatus);
    newRoom.on(RoomEvent.Disconnected, () => {
      if (room === newRoom) { room = null; detachAll(); setState('idle'); $('peer-subtitle').textContent = 'Call ended'; setInfo('Call ended. You can start another call.'); }
    });
    await newRoom.connect(payload.url, payload.token);
    phase = 'publish microphone';
    await newRoom.localParticipant.publishTrack(micTrack, { source: Track.Source.Microphone });
    micTrack = null; // Owned by LiveKit until the room disconnects.
    connectedAt = Date.now();
    setState('connected');
    timer = setInterval(updateTimer, 1000);
    updateTimer(); refreshPeerStatus();
    $('mute-label').textContent = 'Mute'; $('mic-icon').innerHTML = ICONS.mic; $('mute-btn').classList.remove('off');
    if (!newRoom.canPlaybackAudio) setInfo('Connected. Tap Speaker on to enable remote audio.');
  } catch (error) {
    if (micTrack) micTrack.stop();
    const failedRoom = room; room = null;
    if (failedRoom) await failedRoom.disconnect().catch(() => {});
    detachAll(); setState('idle');
    $('peer-subtitle').textContent = 'Unable to connect';
    const reason = error?.message || String(error);
    setInfo(`Failed during ${phase}: ${reason}`, true);
  }
}
async function hangUp() { const previous = room; room = null; if (previous) await previous.disconnect(); detachAll(); setState('idle'); $('peer-subtitle').textContent = 'Call ended'; setInfo('Call ended. The other phone remains connected until it hangs up.'); }
$('join-btn').addEventListener('click', async () => { if (joined) await hangUp(); else if (!connecting) await startCall(); });
$('role-caller').addEventListener('click', () => { if (!joined && !connecting) { selectedRole = 'caller'; updateRole(); } });
$('role-receiver').addEventListener('click', () => { if (!joined && !connecting) { selectedRole = 'receiver'; updateRole(); } });
$('mute-btn').addEventListener('click', async () => {
  if (!room) return;
  const enabled = !room.localParticipant.isMicrophoneEnabled;
  try { await room.localParticipant.setMicrophoneEnabled(enabled); $('mute-label').textContent = enabled ? 'Mute' : 'Unmute'; $('mic-icon').innerHTML = enabled ? ICONS.mic : ICONS.micOff; $('mute-btn').classList.toggle('off', !enabled); }
  catch (error) { setInfo(`Microphone error: ${error.message}`, true); }
});
$('speaker-btn').addEventListener('click', async () => {
  if (room && !room.canPlaybackAudio) {
    try { await room.startAudio(); } catch (error) { setInfo(`Audio playback blocked: ${error.message}`, true); }
  }
  speakerEnabled = !speakerEnabled;
  for (const el of audioElements.values()) { el.muted = !speakerEnabled; if (speakerEnabled) await el.play().catch(() => {}); }
  $('speaker-label').textContent = speakerEnabled ? 'Speaker on' : 'Speaker off';
  $('speaker-icon').innerHTML = speakerEnabled ? ICONS.speaker : ICONS.speakerOff;
  $('speaker-btn').classList.toggle('off', !speakerEnabled);
  $('speaker-btn').classList.toggle('active', speakerEnabled);
});
window.addEventListener('pagehide', () => { if (room) room.disconnect(); });
updateRole(); setState('idle');

// Receiver-side risk display (read-only; no audio is sent from the browser).
// This local prototype does not authenticate users; the endpoint is LAN-visible.
function renderDetection(d) {
  const panel = $('detector-panel');
  panel.hidden = selectedRole !== 'receiver';
  if (panel.hidden) return;
  const age = typeof d.last_result_at === 'number'
    ? Math.max(0, Date.now() - d.last_result_at * 1000) : Infinity;
  const hasResult = !!d.verdict && typeof d.p_fake === 'number';
  const delayed = !!d.stale || (d.sample_age_ms || 0) + age > 10000;
  const valid = hasResult && !delayed && !['offline','error'].includes(d.status);
  panel.classList.toggle('risk-high', valid && d.alert && d.verdict === 'FAKE');
  panel.classList.toggle('risk-low', valid && d.verdict === 'REAL');
  $('detector-state').textContent = d.status === 'offline' ? 'Offline'
    : d.status === 'error' ? 'Error'
    : hasResult && delayed ? 'Delayed result'
    : valid && d.alert ? 'Elevated risk'
    : valid ? 'Monitoring live'
    : d.status === 'analyzing' ? 'Analyzing…' : 'Listening';
  if (hasResult) {
    const labels = {
      FAKE: 'Synthetic-voice indicators observed — verify independently',
      REAL: 'No strong synthetic indicators in recent audio; identity unverified',
      UNSURE: 'Inconclusive — verify independently'
    };
    $('detector-message').textContent = delayed
      ? 'Previous AI result is too old. Monitoring continues.'
      : (labels[d.verdict] || 'Monitoring audio…');
    $('detector-score').textContent = `Raw score: ${d.p_fake.toFixed(3)} · model ${Math.round(d.model_ms||0)} ms · dropped ${d.dropped||0}`;
  } else {
    $('detector-message').textContent = d.message || 'Listening for caller audio…';
    $('detector-score').textContent = 'PellaV2 analysis starts after 4 seconds of audio';
  }
  const quality = d.quality || 'waiting';
  const level = typeof d.level_dbfs === 'number' ? ` · ${d.level_dbfs.toFixed(1)} dBFS` : '';
  const clip = typeof d.clipping_pct === 'number' && d.clipping_pct >= 0.5
    ? ` · clipped ${d.clipping_pct.toFixed(1)}%` : '';
  $('audio-quality').textContent = `Audio: ${quality}${level}${clip}`
    + (d.audio_activity ? ' · activity detected' : ' · no significant activity');
}
async function updateDetection() {
  if (selectedRole !== 'receiver') return;
  try {
    const response = await fetch('/api/detection', {cache: 'no-store'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderDetection(await response.json());
  } catch (_) {
    $('detector-state').textContent = 'Offline';
    $('detector-message').textContent = 'Cannot reach detection status service';
  }
}
// Server-sent events deliver status immediately; polling is a reliable fallback
// on mobile browsers or proxies that interrupt long-lived connections.
let statusEvents = null;
let statusPoll = null;
function startFallbackPoll() {
  if (!statusPoll) statusPoll = setInterval(updateDetection, 1000);
}
function stopFallbackPoll() {
  if (statusPoll) { clearInterval(statusPoll); statusPoll = null; }
}
function subscribeDetection() {
  updateDetection();
  if (typeof EventSource === 'undefined') { startFallbackPoll(); return; }
  statusEvents = new EventSource('/api/detection/events');
  statusEvents.onmessage = (event) => {
    try { renderDetection(JSON.parse(event.data)); } catch (_) { /* ignore malformed event */ }
  };
  statusEvents.onopen = stopFallbackPoll;
  statusEvents.onerror = startFallbackPoll;
}
subscribeDetection();
window.addEventListener('pagehide', () => {
  if (statusEvents) statusEvents.close();
  stopFallbackPoll();
});

// V4 fraud-language status is independent of PellaV2. No raw transcript is displayed or retained.
function renderFraud(f) {
  const panel = $('fraud-panel');
  panel.hidden = selectedRole !== 'receiver';
  if (panel.hidden) return;
  const ready = f.status === 'active';
  const risk = ready ? f.risk_level : 'unresolved';
  $('fraud-state').textContent = !ready ? (f.status === 'listening' ? 'Listening' : 'Offline') :
    risk === 'high' ? 'Sensitive request' : risk === 'elevated' ? 'Possible concern' : 'No matched phrase';
  const level = Number.isFinite(f.audio_level_dbfs) ? ` · audio ${f.audio_level_dbfs.toFixed(0)} dBFS` : '';
  const speed = Number.isFinite(f.asr_latency_ms) ? ` · ASR ${f.asr_latency_ms.toFixed(0)} ms` : '';
  $('fraud-message').textContent = (f.reason || 'No conclusion') + level + speed;
  const labels = {credential_request:'Credential/code request', urgent_transfer:'Urgent money transfer',
    secrecy_pressure:'Secrecy pressure',remote_access:'Remote access request',
    claimed_bank_identity:'Claimed bank identity'};
  const indicators = Array.isArray(f.indicators) ? f.indicators.map(i=>labels[i]).filter(Boolean) : [];
  $('fraud-indicators').textContent = indicators.length ? `Indicators: ${indicators.join(' · ')}` : 'No matched scam-language indicators';
  $('fraud-identity').textContent = f.verification_status === 'operator_attested' ? 'Operator reports independently verified (not automated)' : f.verification_status === 'failed' ? 'Independent verification failed' : f.identity_status === 'unverified' ? 'Bank identity claimed — NOT independently verified' : 'Identity: not independently verified';
}
async function updateFraud() {
  if (selectedRole !== 'receiver') return;
  try {
    const response = await fetch('/api/fraud', {cache:'no-store'});
    if (!response.ok) throw Error(`HTTP ${response.status}`);
    renderFraud(await response.json());
  } catch (_) { $('fraud-state').textContent = 'Offline'; }
}
let fraudEvents;
let fraudPoll;
function fraudFallback() { if (!fraudPoll) fraudPoll = setInterval(updateFraud, 1500); }
function fraudStopFallback() { if (fraudPoll) { clearInterval(fraudPoll); fraudPoll=null; } }
updateFraud();
if (typeof EventSource !== 'undefined') {
  fraudEvents = new EventSource('/api/fraud/events');
  fraudEvents.onmessage = event => { try { renderFraud(JSON.parse(event.data)); } catch (_) {} };
  fraudEvents.onerror = fraudFallback;
  fraudEvents.onopen = fraudStopFallback;
} else fraudFallback();
window.addEventListener('pagehide', () => { if (fraudEvents) fraudEvents.close(); fraudStopFallback(); });

// Cross-signal summary. Never treat a REAL voice label as identity verification.
let latestVoiceAssessment = null;
let latestFraudAssessment = null;
const previousVoiceRender = renderDetection;
renderDetection = function (d) {
  latestVoiceAssessment = d;
  previousVoiceRender(d);
  renderCombined();
};
const previousFraudRender = renderFraud;
renderFraud = function (f) {
  latestFraudAssessment = f;
  previousFraudRender(f);
  renderCombined();
};
function renderCombined() {
  const output = $('combined-message');
  if (!output) return;
  const v = latestVoiceAssessment;
  const f = latestFraudAssessment;
  const synthetic = v && v.verdict === 'FAKE' && !v.stale &&
    v.status !== 'offline' && v.status !== 'error';
  const sensitive = f && f.status === 'active' && f.risk_level === 'high';
  const identityClaim = f && f.status === 'active' &&
    Array.isArray(f.indicators) && f.indicators.includes('claimed_bank_identity');
  if (sensitive) output.textContent = 'Sensitive request detected. Do not share codes or move funds; independently contact your bank.';
  else if (synthetic && identityClaim) output.textContent = 'Possible synthetic voice with an unverified bank identity claim. Verify independently.';
  else if (synthetic) output.textContent = 'Synthetic speech suspected. This alone does not establish fraud.';
  else if (identityClaim) output.textContent = 'Caller claims bank affiliation; identity not verified.';
  else output.textContent = 'Monitoring both channels. No result here establishes that the caller is safe.';
  $('combined-panel').hidden = selectedRole !== 'receiver';
}
renderCombined();

// Sentrix receiver-only one-time fraud and spoken warning (preserved by UI merge).
import "./receiver_warning.js";
import "./ver12-warning-layout.css";
