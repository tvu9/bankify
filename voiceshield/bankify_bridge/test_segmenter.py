"""Optional test after installing dependencies and obtaining Bankify checkpoint.
Run: python -m unittest bankify_bridge.test_segmenter
"""
import unittest
import numpy as np

# Importing the bridge loads Bankify and livekit dependencies, so the test is
# intended for the configured target Mac environment.
from bankify_bridge.livekit_bankify import Segmenter, SR

class SegmenterTests(unittest.TestCase):
    def test_window_hops_and_bounded_buffer(self):
        seg = Segmenter()
        results = []
        for _ in range(12):
            results.extend(seg.add(np.zeros(SR, dtype=np.float32)))
        self.assertEqual(len(results), 10)
        self.assertTrue(all(x.shape == (3 * SR,) for x in results))
        self.assertLessEqual(len(seg.buffer), 4 * SR)

if __name__ == '__main__':
    unittest.main()
