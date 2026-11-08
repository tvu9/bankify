import importlib.util
import pathlib
import sys
import unittest
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'voice_detector'))
from audio_quality_v32 import AudioQuality


class QualityTests(unittest.TestCase):
    def test_silence(self):
        meter = AudioQuality()
        self.assertIsNone(meter.add(np.zeros(4000, dtype=np.float32)))
        result = meter.add(np.zeros(4000, dtype=np.float32))
        self.assertEqual(result['quality'], 'quiet')
        self.assertFalse(result['audio_activity'])

    def test_speech_level(self):
        meter = AudioQuality()
        x = np.sin(np.linspace(0, 100, 8000, dtype=np.float32)) * 0.08
        result = meter.add(x)
        self.assertEqual(result['quality'], 'normal')
        self.assertTrue(result['audio_activity'])

    def test_clip(self):
        result = AudioQuality().add(np.ones(8000, dtype=np.float32))
        self.assertEqual(result['quality'], 'clipping')

    def test_no_pcm_retention(self):
        meter = AudioQuality()
        meter.add(np.ones(8000, dtype=np.float32) * 0.03)
        self.assertEqual(meter.samples, 0)
        self.assertFalse(any(isinstance(v, np.ndarray) for v in vars(meter).values()))

    def test_bad_audio_does_not_crash(self):
        result = AudioQuality().add(np.full(8000, np.nan, dtype=np.float32))
        self.assertEqual(result['quality'], 'invalid')

    def test_server_keeps_results_for_quality_events(self):
        src = (ROOT / 'server.py').read_text()
        self.assertIn("elif status == 'quality':", src)
        self.assertIn("normalized[key] = DETECTION.get(key)", src)
        self.assertIn('STATE_CHANGED.notify_all()', src)

    def test_worker_preserves_inference_path(self):
        src = (ROOT / 'voice_detector/livekit_pella.py').read_text()
        self.assertIn('model.analyze_timed, pcm', src)
        self.assertIn('AudioRing(hop=int(hop_seconds * SAMPLE_RATE))', src)
        self.assertIn('quality_meter.add(x)', src)
        self.assertIn('queue.submit((generation, window, time.monotonic()))', src)

    def test_receiver_has_fallback(self):
        src = (ROOT / 'src/main.js').read_text()
        self.assertIn("new EventSource('/api/detection/events')", src)
        self.assertIn('setInterval(updateDetection, 1000)', src)


if __name__ == '__main__':
    unittest.main()
