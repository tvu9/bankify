import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1] / 'voice_detector' / 'decision_v31.py'
spec = importlib.util.spec_from_file_location('decision_v31', PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
EvidenceDecision = module.EvidenceDecision

class Tests(unittest.TestCase):
    def test_high_pair(self):
        d=EvidenceDecision()
        self.assertEqual(d.add(.002)[0], 'UNSURE')
        self.assertEqual(d.add(.997)[0], 'UNSURE')
        self.assertEqual(d.add(.963)[0], 'FAKE')

    def test_brief_contradiction_does_not_flip(self):
        d=EvidenceDecision()
        for x in [.1,.95,.96]: d.add(x)
        self.assertEqual(d.add(.001)[0], 'FAKE')
        self.assertEqual(d.add(.001)[0], 'FAKE')
        self.assertEqual(d.add(.001)[0], 'FAKE')
        self.assertEqual(d.add(.001)[0], 'UNSURE')

    def test_reset_drops_old_evidence(self):
        d=EvidenceDecision()
        d.add(.9); d.add(.9)
        d.reset()
        self.assertEqual(d.add(.01)[0], 'UNSURE')
        self.assertEqual(d.add(.01)[0], 'UNSURE')
        self.assertEqual(d.add(.01)[0], 'REAL')

    def test_history_bounded(self):
        d=EvidenceDecision()
        for _ in range(1000): d.add(.01)
        self.assertEqual(len(d.scores), 8)

    def test_bad_values_rejected(self):
        d=EvidenceDecision()
        for value in (float('nan'),float('inf'),-1,2):
            with self.assertRaises(ValueError): d.add(value)

    def test_disagreement_prevents_immediate_real(self):
        d=EvidenceDecision()
        for x in [.9,.9,.01,.01,.01,.01,.01,.01,.01]: verdict,_=d.add(x)
        self.assertEqual(verdict, 'UNSURE')

if __name__=='__main__': unittest.main()
