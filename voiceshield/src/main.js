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

$('app').innerHTML = `
<main class="app-shell">
 <header class="topbar"><div class="brand"><span class="logo">◈</span><div><strong>VoiceShield</strong><small>SECURE AUDIO LAB</small></div></div><span class="connection-tag" id="connection-tag"><span class="status-dot"></span><span id="top-status">Ready</span></span></header>
 <section class="phone-frame" aria-label="Voice call control panel">
   <div class="upper"><div class="eyebrow">PRIVATE AUDIO SESSION</div><div class="avatar" aria-hidden="true"><svg viewBox="0 0 80 80" fill="none"><circle cx="40" cy="27" r="12" stroke="currentColor" stroke-width="2.5"/><path d="M19 65c0-14 9-22 21-22s21 8 21 22" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/></svg></div>
   <h1 id="peer-title">Receiver</h1><p class="peer-subtitle" id="peer-subtitle">Waiting to start a call</p><div class="timer" id="call-timer">00:00</div>
   <div class="wave" id="wave" aria-label="Audio activity"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div></div>
   <div class="bottom">
    <div class="role-area"><span class="field-label">THIS PHONE IS</span><div class="role-buttons" role="group" aria-label="Choose phone role"><button id="role-caller" class="role-btn" type="button">Caller</button><button id="role-receiver" class="role-btn" type="button">Receiver</button></div></div>
    <div class="controls"><button id="mute-btn" class="control" type="button" disabled aria-label="Mute microphone"><span class="control-icon" id="mic-icon">🎙</span><span id="mute-label">Mute</span></button><button id="speaker-btn" class="control active" type="button" disabled aria-label="Toggle speaker"><span class="control-icon" id="speaker-icon">🔊</span><span id="speaker-label">Speaker on</span></button></div>
    <button type="button" id="join-btn" class="primary-call"><span id="join-icon">☎</span><span id="join-label">Start audio call</span></button>
    <div class="security-line"><span>🔒</span> Audio-only encrypted transport · No camera</div>
   </div>
 </section>
 <div class="info" id="info" role="status" aria-live="polite">Choose your role and start the call. On the other phone, choose the opposite role.</div>
 <section class="detector-panel" id="detector-panel" aria-live="polite">
  <div class="detector-heading"><span>◉ VoiceShield AI voice monitoring</span><span id="detector-state">Offline</span></div>
  <div class="detector-message" id="detector-message">Waiting for the PellaV2 detection worker…</div>
  <div class="detector-score" id="detector-score">No analysis yet</div>
  <div class="detector-score" id="audio-quality">Audio: waiting for caller</div>
  <div class="detector-note">PellaV2 experimental model output. Not a calibrated probability or proof of human identity. Verify requests independently.</div>
 </section>
 <section class="detector-panel" id="fraud-panel" aria-live="polite">
  <div class="detector-heading"><span>◇ VoiceShield V3.2 + Speech Recognition</span><span id="fraud-state">Offline</span></div>
  <div class="detector-message" id="fraud-message">Transcription worker not connected</div>
  <div class="detector-score" id="fraud-indicators">No scam-language evidence yet</div>
  <div class="detector-score" id="fraud-identity">Identity: not independently verified</div>
  <div class="detector-note">Experimental phrase screening. No match does not mean a call is safe. AI voice is not proof of fraud; a human voice is not proof of legitimacy. Don't share verification codes or move funds based solely on a call.</div>
 </section>
 <section class="detector-panel" id="combined-panel" aria-live="polite">
  <div class="detector-heading"><span>♢ Combined call safety</span><span>Unverified</span></div>
  <div class="detector-message" id="combined-message">Monitoring both signals. No result establishes that the caller is safe.</div>
  <div class="detector-note">Voice authenticity and scam-language cues are different signals. Verification must happen via a known trusted channel.</div>
 </section>
 <footer>Local development prototype • Not a cellular phone call</footer>
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
  $('join-label').textContent = busy ? 'Connecting…' : joined ? 'Hang up' : 'Start audio call';
  $('join-icon').textContent = joined ? '✕' : '☎';
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
    $('mute-label').textContent = 'Mute'; $('mic-icon').textContent = '🎙'; $('mute-btn').classList.remove('off');
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
  try { await room.localParticipant.setMicrophoneEnabled(enabled); $('mute-label').textContent = enabled ? 'Mute' : 'Unmute'; $('mic-icon').textContent = enabled ? '🎙' : '🔇'; $('mute-btn').classList.toggle('off', !enabled); }
  catch (error) { setInfo(`Microphone error: ${error.message}`, true); }
});
$('speaker-btn').addEventListener('click', async () => {
  if (room && !room.canPlaybackAudio) {
    try { await room.startAudio(); } catch (error) { setInfo(`Audio playback blocked: ${error.message}`, true); }
  }
  speakerEnabled = !speakerEnabled;
  for (const el of audioElements.values()) { el.muted = !speakerEnabled; if (speakerEnabled) await el.play().catch(() => {}); }
  $('speaker-label').textContent = speakerEnabled ? 'Speaker on' : 'Speaker off';
  $('speaker-icon').textContent = speakerEnabled ? '🔊' : '🔇';
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
