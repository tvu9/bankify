"""Bounded PCM framing, speech quality gate, and conservative temporal decisions.

No model dependencies. No disk writes. These are prototype settings and must be
benchmarked with your real phone-call audio before being used for security actions.
"""
from collections import deque
import numpy as np

SAMPLE_RATE = 16_000
WINDOW_SECONDS = 4
HOP_SECONDS = 1
WINDOW = SAMPLE_RATE * WINDOW_SECONDS
HOP = SAMPLE_RATE * HOP_SECONDS


class AudioRing:
    """O(samples) rolling ring buffer; never retains more than four seconds."""

    def __init__(self, window=WINDOW, hop=HOP):
        if not 0 < hop <= window:
            raise ValueError('Expected 0 < hop <= window')
        self.window = window
        self.hop = hop
        self.buffer = np.zeros(window, dtype=np.float32)
        self.write = 0
        self.total = 0
        self.next_emit = window

    def add(self, samples):
        samples = np.asarray(samples, dtype=np.float32).ravel()
        out = []
        pos = 0
        while pos < len(samples):
            n = min(len(samples) - pos, self.next_emit - self.total, self.window - self.write)
            if n <= 0:
                raise RuntimeError('AudioRing could not advance')
            self.buffer[self.write:self.write + n] = samples[pos:pos + n]
            self.write = (self.write + n) % self.window
            self.total += n
            pos += n
            if self.total == self.next_emit:
                # The oldest sample starts at self.write once ring is full.
                out.append(np.concatenate((self.buffer[self.write:], self.buffer[:self.write])))
                self.next_emit += self.hop
        return out


def has_usable_speech(window, min_rms=0.004, frame_ms=20, min_active_fraction=0.12):
    """Fast energy gate (not a voice activity detector). Discard silence/near-silence.

    Noise/music can pass; use a proper VAD and domain evaluation before deployment.
    """
    x = np.asarray(window, dtype=np.float32)
    if len(x) < WINDOW // 2 or not np.all(np.isfinite(x)):
        return False
    if np.sqrt(np.mean(x * x)) < min_rms:
        return False
    frame = SAMPLE_RATE * frame_ms // 1000
    n = len(x) // frame
    if not n:
        return False
    rms = np.sqrt(np.mean(x[:n * frame].reshape(n, frame) ** 2, axis=1))
    return float(np.mean(rms > min_rms)) >= min_active_fraction


class RiskSmoother:
    """Flag sustained evidence, not a single score; never claims to prove 'human'."""
    def __init__(self, high_threshold=0.60, low_threshold=0.25):
        self.scores = deque(maxlen=3)
        self.high_threshold = high_threshold
        self.low_threshold = low_threshold

    def add(self, score):
        if not np.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('Bad model score')
        self.scores.append(float(score))
        vals = list(self.scores)
        # Two elevated observations within the latest three are required.
        if len(vals) >= 2 and sum(s >= self.high_threshold for s in vals) >= 2:
            return 'FAKE', float(np.mean(vals))
        if len(vals) == 3 and max(vals) < self.low_threshold:
            return 'REAL', float(np.mean(vals))
        return 'UNSURE', float(np.mean(vals))
