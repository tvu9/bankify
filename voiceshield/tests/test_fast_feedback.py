"""Run with: python3 -m unittest discover -s tests -p 'test_fast_*.py' -v"""
import unittest
import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'voice_detector'))
from fast_status import EarlyAudioProgress
from stream_utils import AudioRing

class TestFastAudio(unittest.TestCase):
    def test_first_frame_and_activity(self):
        p = EarlyAudioProgress()
        first = p.observe(np.zeros(1600, dtype=np.float32), 0.0)
        self.assertTrue(first.first_frame)
        self.assertFalse(first.first_activity)
        self.assertTrue(first.report)
        second = p.observe(np.full(1600, 0.08, dtype=np.float32), 0.1)
        self.assertFalse(second.first_frame)
        self.assertTrue(second.first_activity)
        self.assertTrue(second.active)
        self.assertFalse(second.report)

    def test_progress_half_second_throttle(self):
        p = EarlyAudioProgress()
        reports = []
        for i in range(40):
            sample = p.observe(np.zeros(1600, dtype=np.float32), 0.1*i)
            if sample.report: reports.append(sample.seconds)
        self.assertGreaterEqual(len(reports), 6)
        self.assertLessEqual(len(reports), 9)
        self.assertAlmostEqual(reports[0], 0.1)
        self.assertAlmostEqual(p.samples / 16000, 4.0)
        self.assertFalse(p.observe(np.zeros(1600, dtype=np.float32), 5.0).report)

    def test_first_inference_window_at_four_seconds(self):
        r = AudioRing(hop=16000)
        x = np.ones(1600, dtype=np.float32)
        windows = []
        for i in range(50):
            got = r.add(x)
            if got: windows.append((i, got))
        self.assertEqual([i for i,_ in windows], [39,49])
        self.assertTrue(all(len(w) == 64000 for _, arr in windows for w in arr))

if __name__ == '__main__': unittest.main()
