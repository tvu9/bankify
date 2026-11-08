"""Fast, read-only PCM telemetry. Energy activity is NOT speech recognition.

No filtering, gain changes, audio retention, or neural inference.
"""
import math
import numpy as np


class AudioQuality:
    def __init__(self, sample_rate=16000, publish_every=0.5):
        self.sample_rate = sample_rate
        self.target = max(1, int(sample_rate * publish_every))
        self.reset()

    def reset(self):
        self.samples = 0
        self.sum_squares = 0.0
        self.clipped = 0
        self.peak = 0.0
        self.active = 0

    def add(self, samples):
        """Return a 0.5s summary or None. Bounded scalar state only."""
        x = np.asarray(samples, dtype=np.float32).ravel()
        if not len(x):
            return None
        if not np.all(np.isfinite(x)):
            self.reset()
            return {'quality': 'invalid', 'level_dbfs': -90.0, 'clipping_pct': 0.0,
                    'audio_activity': False}
        # Accumulate statistics without retaining actual PCM.
        self.samples += len(x)
        self.sum_squares += float(np.sum(x.astype(np.float64) ** 2))
        self.clipped += int(np.count_nonzero(np.abs(x) >= 0.98))
        self.peak = max(self.peak, float(np.max(np.abs(x))))
        if self.samples < self.target:
            return None
        rms = math.sqrt(self.sum_squares / self.samples)
        level = max(-90.0, 20.0 * math.log10(max(rms, 1e-9)))
        clipped_pct = 100.0 * self.clipped / self.samples
        active = rms >= 0.004  # energy only; noise/music may trigger this
        if clipped_pct >= 0.5:
            quality = 'clipping'
        elif level < -48:
            quality = 'quiet'
        elif level > -6:
            quality = 'loud'
        else:
            quality = 'normal'
        event = {'quality': quality, 'level_dbfs': round(level, 1),
                 'clipping_pct': round(clipped_pct, 2), 'audio_activity': active}
        self.reset()
        return event
