"""Auditable, bounded decision state for a real-time *research* voice detector.

Does not change the neural model, audio preprocessing, or input windows.
Scores are uncalibrated. Labels are screening indicators, never identity proof.
This evidence-hold policy is experimental until validated on labeled call audio.
"""
from collections import deque
import math

class EvidenceDecision:
    """Conservative decision rules; newest scores are highly correlated.

    A recent pair of high scores produces a warning; a warning is held briefly
    when the very next overlapping window disagrees. Evidence expires, and
    low scores cannot certify a human voice. No claims of statistical independence.
    """
    def __init__(self, high=0.60, low=0.25, history=8, warning_hold=3):
        if not 0 <= low < high <= 1:
            raise ValueError('Invalid thresholds')
        if history < 4 or warning_hold < 0:
            raise ValueError('Invalid history or hold')
        self.high = high
        self.low = low
        self.history = deque(maxlen=history)
        self.warning_hold = warning_hold
        self.hold_remaining = 0
        self.last_state = 'UNSURE'

    def reset(self):
        self.history.clear()
        self.hold_remaining = 0
        self.last_state = 'UNSURE'

    @property
    def scores(self):
        return self.history

    def add(self, score):
        if not isinstance(score, (int,float)) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('Invalid model score')
        score = float(score)
        self.history.append(score)
        recent = list(self.history)
        mean = sum(recent[-3:]) / min(3, len(recent))
        high_count = sum(s >= self.high for s in recent[-3:])
        if high_count >= 2 and score >= self.high:
            # Enter once; don't silently extend the hold just because two
            # overlapping high windows are still in the rolling history.
            if self.last_state != 'FAKE':
                self.hold_remaining = self.warning_hold
            self.last_state = 'FAKE'
            return 'FAKE', mean
        if self.hold_remaining > 0:
            self.hold_remaining -= 1
            self.last_state = 'FAKE'
            return 'FAKE', mean
        if any(s >= self.high for s in recent):
            self.last_state = 'UNSURE'
            return 'UNSURE', mean
        if len(recent) >= 3 and all(s < self.low for s in recent[-3:]):
            self.last_state = 'REAL'
            return 'REAL', mean
        self.last_state = 'UNSURE'
        return 'UNSURE', mean
