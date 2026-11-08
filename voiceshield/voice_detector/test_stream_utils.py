import unittest
import numpy as np
try:
    from .stream_utils import AudioRing, RiskSmoother, WINDOW, HOP, SAMPLE_RATE, has_usable_speech
except ImportError:
    from stream_utils import AudioRing, RiskSmoother, WINDOW, HOP, SAMPLE_RATE, has_usable_speech

class AudioRingTests(unittest.TestCase):
    def test_windows_exact_hops(self):
        r = AudioRing()
        data = np.arange(7 * SAMPLE_RATE, dtype=np.float32)
        results = []
        for chunk in np.array_split(data, 179):
            results.extend(r.add(chunk))
        self.assertEqual(len(results), 4)
        for i, x in enumerate(results):
            np.testing.assert_array_equal(x, data[i * HOP: i * HOP + WINDOW])
        self.assertEqual(r.buffer.size, WINDOW)

    def test_large_chunk(self):
        r = AudioRing()
        result = r.add(np.arange(6 * SAMPLE_RATE, dtype=np.float32))
        self.assertEqual(len(result), 3)
        np.testing.assert_array_equal(result[-1], np.arange(2*SAMPLE_RATE, 6*SAMPLE_RATE, dtype=np.float32))

    def test_gate(self):
        self.assertFalse(has_usable_speech(np.zeros(WINDOW)))
        self.assertTrue(has_usable_speech(np.ones(WINDOW) * 0.05))

    def test_temporal_decisions(self):
        s = RiskSmoother()
        self.assertEqual(s.add(0.94)[0], 'UNSURE')
        self.assertEqual(s.add(0.88)[0], 'FAKE')
        s = RiskSmoother()
        self.assertEqual(s.add(0.1)[0], 'UNSURE')
        self.assertEqual(s.add(0.2)[0], 'UNSURE')
        self.assertEqual(s.add(0.15)[0], 'REAL')
        with self.assertRaises(ValueError):
            s.add(float('nan'))

if __name__ == '__main__':
    unittest.main()
