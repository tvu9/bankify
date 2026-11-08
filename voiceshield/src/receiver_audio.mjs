// Receiver-only *local* audio playback. Never publishes audio to LiveKit.
// Use prerecorded media rather than speechSynthesis: some iOS Safari versions
// can mute active getUserMedia tracks when browser speech synthesis speaks.
export const WARNING_AUDIO_URL = '/voiceshield_receiver_warning.m4a';
export const AI_WARNING_AUDIO_URL = '/voiceshield_ai_voice_warning.m4a';
export const READY_AUDIO_URL = '/voiceshield_audio_ready.m4a?brand=sentrix-v1';

/**
 * Uses one audio element so a receiver's deliberate "Enable audio warnings"
 * gesture can authorize later spoken alerts on browsers with autoplay rules.
 * A failure displays a manual-play fallback; there are no automatic retries.
 */
export class ReceiverWarningAudio {
  constructor({ AudioClass = globalThis.Audio, onPlaybackBlocked = () => {}, onReady = () => {} } = {}) {
    this.audio = typeof AudioClass === 'function' ? new AudioClass() : null;
    this.onPlaybackBlocked = onPlaybackBlocked;
    this.onReady = onReady;
    this.enabled = false;
    this.attemptedThisCall = false;
    this.startedThisCall = false;
    this.phase = 'idle';
    this.warningSource = WARNING_AUDIO_URL;
    this.serial = 0;
    if (this.audio) {
      this.audio.preload = 'auto';
      this.audio.src = WARNING_AUDIO_URL;
      this.audio.onended = () => {
        if (this.phase === 'ready') {
          this.phase = 'idle';
          this.audio.src = WARNING_AUDIO_URL;
          this.audio.load();
        } else if (this.phase === 'warning') {
          this.phase = 'idle';
        }
      };
    }
  }

  /** Must be invoked directly by receiver click (before awaiting anything). */
  enableFromGesture() {
    if (!this.audio) return Promise.resolve(false);
    const serial = ++this.serial;
    this.phase = 'ready';
    this.audio.pause();
    this.audio.src = READY_AUDIO_URL;
    this.audio.load();
    let promise;
    try { promise = this.audio.play(); } catch (error) { promise = Promise.reject(error); }
    return Promise.resolve(promise).then(() => {
      if (serial !== this.serial) return false;
      this.enabled = true;
      this.onReady(true);
      return true;
    }).catch(() => {
      if (serial !== this.serial) return false;
      this.enabled = false;
      this.phase = 'idle';
      this.onReady(false);
      return false;
    });
  }

  /** Called exactly when the high-risk banner is shown. */
  warnOnce(kind = 'fraud') {
    if (this.attemptedThisCall) return false;
    this.attemptedThisCall = true;
    this.warningSource = kind === 'ai_voice' ? AI_WARNING_AUDIO_URL : WARNING_AUDIO_URL;
    // Muted by the receiver: record the one-time event but play nothing.
    if (!this.enabled) return false;
    this._playWarning();
    return true;
  }

  /** Human click fallback, only if automatic playback did not start. */
  replayFromGesture() {
    if (!this.enabled || !this.attemptedThisCall || this.startedThisCall) return false;
    this._playWarning();
    return true;
  }

  _playWarning() {
    if (!this.audio) { this.onPlaybackBlocked(); return; }
    const serial = ++this.serial;
    this.phase = 'warning';
    this.audio.pause();
    this.audio.src = this.warningSource;
    this.audio.load();
    let promise;
    try { promise = this.audio.play(); } catch (error) { promise = Promise.reject(error); }
    Promise.resolve(promise).then(() => {
      if (serial !== this.serial) return;
      this.startedThisCall = true;
    }).catch(() => {
      if (serial !== this.serial) return;
      this.onPlaybackBlocked();
    });
  }

  /** Reset only when this receiver's connected call ends. */
  resetForNewCall() {
    this.serial += 1; // Ignore delayed play promise callbacks from previous call.
    this.attemptedThisCall = false;
    this.startedThisCall = false;
    this.phase = 'idle';
    this.warningSource = WARNING_AUDIO_URL;
    if (this.audio) {
      this.audio.pause();
      this.audio.src = WARNING_AUDIO_URL;
      this.audio.load();
    }
  }

  /** Explicit receiver choice: turn spoken warnings OFF without disabling visual alerts. */
  disable() {
    this.serial += 1; // Invalidates any pending activation or playback Promise.
    this.enabled = false;
    this.phase = 'idle';
    if (this.audio) {
      this.audio.pause();
      this.audio.src = WARNING_AUDIO_URL;
      this.audio.load();
    }
  }

  stop() {
    this.serial += 1;
    this.phase = 'idle';
    if (this.audio) this.audio.pause();
  }
}
