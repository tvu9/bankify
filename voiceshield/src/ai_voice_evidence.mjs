/**
 * Experimental AI-voice evidence, independent from semantic fraud.
 * Count every DISTINCT completed inference window. Four consecutive valid
 * FAKE verdicts issue one receiver-only advisory. NO raw-score requirement.
 * A repeated browser poll of the same window does not count. Invalid/quiet,
 * stale, REAL, or UNSURE new windows break the four-result streak.
 * These ~4s audio windows overlap and are NOT independent. False positives
 * are possible; validate on labeled real and synthetic telephone calls.
 */
export const AI_VOICE_RULE = Object.freeze({
  count: 4,
  minimumHigh: 4,
  minimumWindowGap: 1,      // Count every distinct completed window.
  minimumTimeGap: 0,
  maxAge: 12,
  maxInferenceAgeMs: 10000,
  maxEvidenceSpan: 120,
});

const finite = Number.isFinite;

export class AiVoiceEvidence {
  constructor(rule = AI_VOICE_RULE) {
    this.rule = rule;
    this.reset();
  }

  reset() {
    this.samples = [];
    this.lastSeenWindow = null;
    this.lastSeenResultAt = 0;
    this.triggered = false;
  }

  /**
   * Ingest a completed result from GET /api/detection.
   * Returns an AI-only advisory only when the evidence threshold is reached.
   * The caller UI never invokes this; only the receiver uses it.
   */
  observe(voice, { now = Date.now() / 1000, callStartedAt = 0 } = {}) {
    if (this.triggered || !voice || typeof voice !== 'object') return null;
    const counter = voice.windows;
    const finished = voice.last_result_at;
    if (!Number.isSafeInteger(counter) || counter < 1 || !finite(finished)) return null;

    // A new worker/caller track may reset the counter while the UI is open.
    if (this.lastSeenWindow !== null && counter < this.lastSeenWindow) this.reset();
    if (this.lastSeenWindow !== null && counter === this.lastSeenWindow &&
        finished === this.lastSeenResultAt) return null;

    // Never reprocess the same window or a previously published result.
    if (this.lastSeenWindow !== null && counter <= this.lastSeenWindow) return null;
    this.lastSeenWindow = counter;
    this.lastSeenResultAt = finished;

    // Reject old, stale, invalid/low-quality, and cross-call evidence.
    if (voice.status === 'offline' || voice.status === 'error' || voice.stale === true ||
        finished < callStartedAt || finished > now + 2 || now - finished > this.rule.maxAge ||
        voice.quality !== 'normal' || voice.audio_activity !== true ||
        (voice.verdict !== 'REAL' && voice.verdict !== 'FAKE' && voice.verdict !== 'UNSURE') ||
        !finite(voice.sample_age_ms) || voice.sample_age_ms < 0 ||
        voice.sample_age_ms > this.rule.maxInferenceAgeMs) {
      this.samples = []; // Invalid new evidence breaks the consecutive streak.
      return null;
    }

    // A new, valid non-FAKE verdict breaks the streak immediately.
    // Ignore the raw p_fake score entirely: the published verdict is the vote.
    if (voice.verdict !== 'FAKE') {
      this.samples = [];
      return null;
    }

    const prior = this.samples.at(-1);
    if (prior && (counter - prior.window < this.rule.minimumWindowGap ||
                  finished - prior.at < this.rule.minimumTimeGap)) return null;

    // Drop old evidence after prolonged silence/analysis gaps.
    if (prior && finished - prior.at > this.rule.maxEvidenceSpan) this.samples = [];
    this.samples.push({ window: counter, at: finished, label: voice.verdict });
    if (this.samples.length > this.rule.count) this.samples.shift();
    if (this.samples.length < this.rule.count) return null;

    const strong = this.samples.filter(x => x.label === 'FAKE').length;
    if (strong < this.rule.minimumHigh) return null;

    this.triggered = true;
    return {
      kind: 'ai_voice',
      title: 'Possible AI-generated voice detected',
      message: 'Sentrix detected repeated patterns consistent with synthetic speech. This does not prove the call is fraudulent. Do not share personal, banking, or verification information until you independently verify the caller.',
      voiceLabel: 'FAKE',
      evidenceSegments: this.rule.count,
      strongSegments: strong,
    };
  }
}
