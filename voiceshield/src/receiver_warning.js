import { OneAlertPerCall } from './receiver_risk_policy.mjs';
import { AiVoiceEvidence } from './ai_voice_evidence.mjs';
// Sentrix second independent AI-voice trigger — 2026-11-08
import { ReceiverWarningAudio } from './receiver_audio.mjs';
import './receiver_warning.css';

// Receiver-only visual and spoken advisory. The development server does not
// authenticate roles; this UI restriction is not a security boundary.
function startReceiverAlerts() {
  const app = document.getElementById('app');
  if (!app || document.getElementById('vs-receiver-warning')) return;

  const banner = document.createElement('section');
  banner.id = 'vs-receiver-warning';
  banner.className = 'vs-alert';
  banner.hidden = true;
  banner.setAttribute('aria-label', 'Call safety notification');
  banner.innerHTML = `
    <div class="vs-alert-head">
      <strong id="vs-warning-title">Potential fraud or scam detected</strong>
      <span class="vs-alert-label" id="vs-warning-label">HIGH RISK</span>
    </div>
    <p id="vs-warning-message"></p>
    <small class="vs-alert-disclaimer">This is a precaution, not proof that the caller is fraudulent.</small>
    <div class="vs-warning-actions">
      <button id="vs-warning-play" type="button" hidden>Play spoken warning</button>
      <button id="vs-warning-dismiss" type="button">Dismiss warning</button>
    </div>
  `;

  const anchor = document.getElementById('detector-panel') || document.getElementById('info');
  if (anchor?.parentNode) anchor.parentNode.insertBefore(banner, anchor);
  else app.appendChild(banner);

  // Browsers, particularly iOS Safari, can block delayed media playback unless
  // the receiver first taps a button. One tap arms the SAME media element.
  const audioControls = document.createElement('div');
  // Sentrix compact receiver audio control — ver1.2
  audioControls.id = 'vs-audio-controls';
  audioControls.className = 'vs-audio-compact';
  audioControls.dataset.state = 'idle';
  audioControls.hidden = true;
  audioControls.innerHTML = `
    <button id="vs-enable-spoken-warnings" type="button"
            aria-describedby="vs-audio-controls-help">
      <svg class="vs-voice-chip-icon" viewBox="0 0 24 24" fill="none"
           stroke="currentColor" stroke-width="1.8" stroke-linecap="round"
           stroke-linejoin="round" aria-hidden="true">
        <path d="M4 9v6h4l5 4V5L8 9H4z"/>
        <path d="M16 9a4 4 0 0 1 0 6M19 6a8 8 0 0 1 0 12"/>
      </svg>
      <span id="vs-audio-button-label">Enable voice alerts</span>
    </button>
    <span id="vs-audio-controls-help" role="status" aria-live="polite">
      Tap once to allow spoken scam warnings on this phone.
    </span>
  `;
  // Keep this compact control alongside call buttons, not as a large feed card.
  const callBar = document.querySelector('.call-bar');
  const callButtons = callBar?.querySelector('.controls');
  const info = document.getElementById('info');
  if (callBar && callButtons) callBar.insertBefore(audioControls, callButtons);
  else if (info?.parentNode) info.parentNode.insertBefore(audioControls, info);
  else app.appendChild(audioControls);

  const playButton = document.getElementById('vs-warning-play');
  const enableButton = document.getElementById('vs-enable-spoken-warnings');
  const buttonLabel = document.getElementById('vs-audio-button-label');
  const helpText = document.getElementById('vs-audio-controls-help');
  function setAudioControlState(state, label, help) {
    audioControls.dataset.state = state;
    buttonLabel.textContent = label;
    helpText.textContent = help;
    enableButton.disabled = ['enabling', 'unavailable'].includes(state);
    enableButton.setAttribute('aria-pressed', String(state === 'enabled' || state === 'blocked'));
    enableButton.setAttribute('aria-label', (state === 'enabled' || state === 'blocked')
      ? 'Disable spoken fraud warnings' : 'Enable spoken fraud warnings');
  }
  const roleIsReceiver = () => {
    const receiver = document.getElementById('role-receiver');
    if (receiver?.classList.contains('selected')) return true;
    const caller = document.getElementById('role-caller');
    if (caller?.classList.contains('selected')) return false;
    return new URLSearchParams(location.search).get('role') === 'receiver';
  };
  const connected = () => document.getElementById('top-status')?.textContent?.trim() === 'Connected';

  const audio = new ReceiverWarningAudio({
    onPlaybackBlocked: () => {
      // Only display a tap-to-play fallback on the actual receiver warning.
      if (roleIsReceiver() && activeCall && !banner.hidden) {
        playButton.hidden = false;
        setAudioControlState('blocked', 'Voice alerts on',
          'Automatic playback was blocked. Use Play spoken warning, or tap again to turn off voice alerts.');
      }
    },
    onReady: (ready) => {
      setAudioControlState(
        ready ? 'enabled' : 'error',
        ready ? 'Voice alerts on' : 'Retry voice alerts',
        ready
          ? 'Tap again to disable spoken warnings on this phone.'
          : 'Browser audio was blocked. Tap to retry. A manual play option appears with an alert.'
      );
    },
  });
  if (!audio.audio) {
    setAudioControlState('unavailable', 'Voice alerts unavailable',
      'This browser cannot play spoken warnings. Visual warnings remain active.');
  }

  // Sentrix audio ON/OFF toggle — 2026-11-08
  enableButton.addEventListener('click', () => {
    if (!roleIsReceiver() || enableButton.disabled) return;
    if (audio.enabled) {
      // Disable both automatic and manual spoken warnings immediately.
      // The one-time visual high-risk fraud banner remains enabled.
      audio.disable();
      playButton.hidden = true;
      setAudioControlState('disabled', 'Enable voice alerts',
        'Spoken warnings are off. Tap to turn them back on. Visual fraud warnings remain active.');
      return;
    }
    setAudioControlState('enabling', 'Enabling voice alerts…',
      'Checking permission to play spoken warnings on this phone.');
    // iOS requires this playback authorization within the direct button gesture.
    audio.enableFromGesture();
  });
  playButton.addEventListener('click', () => {
    if (!roleIsReceiver() || !activeCall || !audio.enabled) return;
    playButton.hidden = true;
    // Manual fallback only if the first attempt failed; never auto-repeat.
    if (!audio.replayFromGesture()) playButton.hidden = true;
  });

  const oneAlert = new OneAlertPerCall();
  const aiVoiceEvidence = new AiVoiceEvidence();
  let latestVoice = null;
  let latestFraud = null;
  let activeCall = false;
  let startedAt = 0;
  let requestSerial = 0;
  let pending = false;

  function resetCall() {
    activeCall = false;
    startedAt = 0;
    requestSerial += 1;
    latestVoice = null;
    latestFraud = null;
    oneAlert.reset();
    aiVoiceEvidence.reset();
    audio.resetForNewCall();
    // Allow the receiver to retry audio activation after a blocked call.
    if (audioControls.dataset.state === 'blocked') {
      setAudioControlState('enabled', 'Voice alerts on',
        'Spoken warnings remain enabled for the next call. Tap again to turn them off.');
    }
    banner.hidden = true;
    playButton.hidden = true;
    banner.setAttribute('role', 'status');
  }

  function synchronizeCallState() {
    const isReceiver = roleIsReceiver();
    // Hide existing raw detection/status panels on the receiver at all times.
    document.body.classList.toggle('vs-receiver-silent', isReceiver);
    audioControls.hidden = !isReceiver;
    if (!(isReceiver && connected())) {
      if (activeCall) resetCall();
      else banner.hidden = true;
      return false;
    }
    if (!activeCall) {
      activeCall = true;
      startedAt = Date.now() / 1000;
      latestVoice = null;
      latestFraud = null;
      oneAlert.reset();
    aiVoiceEvidence.reset();
      audio.resetForNewCall();
      // Allow the receiver to retry audio activation after a blocked call.
      if (audioControls.dataset.state === 'blocked') {
        setAudioControlState('enabled', 'Voice alerts on',
            'Spoken warnings remain enabled for the next call. Tap again to turn them off.');
      }
      banner.hidden = true;
      playButton.hidden = true;
      requestSerial += 1;
    }
    return true;
  }

  function maybeWarn() {
    if (!synchronizeCallState()) return;
    // Count only distinct, fresh, normal-quality PellaV2 inference results.
    // Synthetic voice and scam-language screening are INDEPENDENT triggers.
    const options = { now: Date.now() / 1000, callStartedAt: startedAt };
    const voiceWarning = aiVoiceEvidence.observe(latestVoice, options);
    const warning = oneAlert.evaluate(latestVoice, latestFraud, options, voiceWarning);
    if (!warning) return;

    document.getElementById('vs-warning-label').textContent =
      warning.kind === 'ai_voice' ? 'VOICE CAUTION' : 'HIGH RISK';
    document.getElementById('vs-warning-title').textContent = warning.title;
    document.getElementById('vs-warning-message').textContent = warning.message;
    banner.setAttribute('role', 'alert');
    banner.hidden = false;
    playButton.hidden = true;

    // THE SAME ONE-TIME EVENT displays the banner and plays the local voice file.
    // No browser audio is published to LiveKit (but physical speaker audio can
    // be picked up by an unmuted microphone; headphones are recommended).
    audio.warnOnce(warning.kind);
    if (typeof navigator.vibrate === 'function') {
      try { navigator.vibrate([200, 100, 200]); } catch (_) { /* optional */ }
    }
  }

  document.getElementById('vs-warning-dismiss').addEventListener('click', () => {
    banner.hidden = true;
    playButton.hidden = true;
    banner.setAttribute('role', 'status');
    // Even if dismissed, oneAlert.triggered remains true for this call.
  });

  async function refresh() {
    if (!synchronizeCallState() || pending || oneAlert.triggered) return;
    const serial = requestSerial;
    pending = true;
    try {
      const getSnapshot = async (url) => {
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 3500);
        try {
          const response = await fetch(url, { cache: 'no-store', signal: controller.signal });
          return response.ok ? await response.json() : null;
        } catch (_) { return null; }
        finally { clearTimeout(timeout); }
      };
      // Each independent detector can trigger immediately even if the other is offline.
      const applyResult = (kind, snapshot) => {
        if (!snapshot || serial !== requestSerial || !synchronizeCallState() || oneAlert.triggered) return;
        if (kind === 'voice') latestVoice = snapshot;
        else latestFraud = snapshot;
        maybeWarn();
      };
      await Promise.all([
        getSnapshot('/api/detection').then(v => applyResult('voice', v)),
        getSnapshot('/api/fraud').then(f => applyResult('fraud', f)),
      ]);
    } catch (_) { /* No fraud-safety conclusions from failed fetches. */ }
    finally { pending = false; }
  }

  const statusEl = document.getElementById('top-status');
  const observer = statusEl ? new MutationObserver(() => {
    synchronizeCallState();
    refresh();
  }) : null;
  observer?.observe(statusEl, { childList: true, characterData: true, subtree: true });

  for (const id of ['role-caller', 'role-receiver', 'join-btn']) {
    document.getElementById(id)?.addEventListener('click', () => {
      setTimeout(() => { synchronizeCallState(); refresh(); }, 0);
    });
  }
  const timer = setInterval(() => { synchronizeCallState(); refresh(); }, 1400);
  window.addEventListener('pagehide', () => {
    clearInterval(timer);
    observer?.disconnect();
    requestSerial += 1;
    audio.stop();
  });
  synchronizeCallState();
  refresh();
}

// Existing main.js builds its UI synchronously in its module.
setTimeout(startReceiverAlerts, 0);
