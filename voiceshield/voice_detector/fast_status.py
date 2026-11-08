"""Fast, low-cost audio arrival/activity reporting for VoiceShield.

Audio activity is measured with a simple energy threshold. This is NOT deepfake
classification or a speech VAD. The counter resets for each caller track.
"""
from dataclasses import dataclass
import math
import numpy as np


@dataclass(frozen=True)
class Progress:
    first_frame: bool
    first_activity: bool
    seconds: float
    active: bool
    report: bool


class EarlyAudioProgress:
    def __init__(self, sample_rate=16000, window_seconds=4.0,
                 report_interval_seconds=0.5, energy_threshold=0.004):
        if sample_rate <= 0 or window_seconds <= 0 or report_interval_seconds <= 0:
            raise ValueError('Sample rate, window, interval must be positive')
        self.sample_rate = int(sample_rate)
        self.window_seconds = float(window_seconds)
        self.report_interval_seconds = float(report_interval_seconds)
        self.energy_threshold = float(energy_threshold)
        self.samples = 0
        self.has_activity = False
        self.last_report = None

    def observe(self, chunk, now):
        x = np.asarray(chunk, dtype=np.float32).ravel()
        if not len(x):
            return Progress(False, False, self.samples / self.sample_rate,
                            self.has_activity, False)
        first_frame = self.samples == 0
        self.samples += len(x)
        rms = math.sqrt(float(np.mean(np.square(x))))
        first_activity = not self.has_activity and rms >= self.energy_threshold
        self.has_activity = self.has_activity or first_activity
        seconds = min(self.samples / self.sample_rate, self.window_seconds)
        report = (seconds <= self.window_seconds and
                  self.samples <= self.sample_rate * self.window_seconds and
                  (self.last_report is None or now - self.last_report >= self.report_interval_seconds))
        if report:
            self.last_report = now
        return Progress(first_frame, first_activity, seconds,
                        self.has_activity, report)
