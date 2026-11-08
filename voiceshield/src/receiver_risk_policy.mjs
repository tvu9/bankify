/**
 * A high-risk advisory is NOT proof that a call is fraudulent.
 * Authenticity is independent: a REAL voice can be used in a scam.
 * Pure functions: no DOM, no transcript or log retention.
 */
const VALID_VOICE = new Set(['REAL', 'FAKE', 'UNSURE']);
const CURRENT_AGE_LIMIT = 20; // seconds, matches fraud server freshness window
const VOICE_AGE_LIMIT = 12;

function freshTimestamp(value, now, minTimestamp, maxAge) {
  return Number.isFinite(value) && value > 0 && value >= minTimestamp &&
    value <= now + 2 && now - value <= maxAge;
}

export function summarizeVoice(voice = {}, now = Date.now() / 1000, callStartedAt = 0) {
  if (!voice || voice.stale || voice.status === 'offline' || voice.status === 'error') return 'UNSURE';
  if (!VALID_VOICE.has(voice.verdict)) return 'UNSURE';
  if (!freshTimestamp(voice.last_result_at, now, callStartedAt, VOICE_AGE_LIMIT)) return 'UNSURE';
  return voice.verdict;
}

/**
 * Only fresh evidence reported during this connected call can trigger a warning.
 * No warning for REAL/FAKE/UNSURE by themselves, ELEVATED, or UNRESOLVED.
 * The server's high-risk classification is itself advisory, not a verified finding.
 */
export function assessHighRisk(voice = {}, fraud = {}, { now = Date.now()/1000, callStartedAt = 0 } = {}) {
  if (!fraud || fraud.status !== 'active' || fraud.analysis_status === 'unavailable' ||
      !freshTimestamp(fraud.updated_at, now, callStartedAt, CURRENT_AGE_LIMIT)) {
    return null;
  }
  // Historical call risk alone is not sufficient: the development API has no
  // authenticated per-call ID, so it can refer to an earlier conversation.
  const hasHighRisk = fraud.risk_level === 'high' || fraud.verification_status === 'failed';
  if (!hasHighRisk) return null;

  const voiceLabel = summarizeVoice(voice, now, callStartedAt);
  const synthetic = voiceLabel === 'FAKE';
  return {
    title: 'Potential fraud or scam detected',
    message: synthetic
      ? 'Sentrix detected high-risk conversation signals, and the voice may be AI-generated. Do not share passwords, verification codes, account details, or transfer money. Hang up and contact your bank using a trusted official number.'
      : 'Sentrix detected high-risk conversation signals. Do not share passwords, verification codes, account details, or transfer money. Hang up and contact your bank using a trusted official number.',
    voiceLabel,
  };
}

/** One notification at most per call. Reset only for a new call. */
export class OneAlertPerCall {
  constructor() { this.reset(); }
  reset() { this.triggered = false; }
  evaluate(voice, fraud, options, aiWarning = null) {
    if (this.triggered) return null;
    // Semantic fraud can be high with a human voice; AI voice can be synthetic
    // with no scam content. Both independently qualify for ONE caution per call.
    const fraudWarning = assessHighRisk(voice, fraud, options);
    const warning = fraudWarning ? { ...fraudWarning, kind: 'fraud' } : aiWarning;
    if (warning) this.triggered = true;
    return warning;
  }
}
