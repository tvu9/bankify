import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'fraud_monitor'))
from transcript_delta import TranscriptDelta

class TranscriptDeltaTest(unittest.TestCase):
    def test_repeated_window_is_silent(self):
        d = TranscriptDelta()
        self.assertEqual('Hello there.', d.consume('Hello there.'))
        self.assertEqual('', d.consume('Hello there.'))
    def test_overlap_emits_only_new_words(self):
        d = TranscriptDelta()
        self.assertEqual('Hello how are you today',d.consume('Hello how are you today'))
        self.assertEqual('I am fine',d.consume('are you today I am fine'))
        self.assertEqual('',d.consume('I am fine'))
    def test_new_words_alone_drive_risk(self):
        from risk_engine import CallRisk
        d = TranscriptDelta(); r = CallRisk()
        first = d.consume('Tell me your password')
        self.assertEqual('high',r.add(d.context_text(first))['risk_level'])
        more = d.consume('your password The weather is nice today')
        self.assertEqual('The weather is nice today',more)
        self.assertEqual('unresolved',r.add(d.context_text(more))['risk_level'])
    def test_empty_is_silent(self):
        d = TranscriptDelta();self.assertEqual('',d.consume('   '))
    def test_silence_resets(self):
        d = TranscriptDelta();d.consume('Hello there');d.mark_silence()
        self.assertEqual('Hello there',d.consume('Hello there'))
    def test_shortened_previous_is_silent(self):
        d = TranscriptDelta();d.consume('one two three four')
        self.assertEqual('',d.consume('two three'))
    def test_reset(self):
        d = TranscriptDelta();d.consume('hello');d.reset()
        self.assertEqual('hello',d.consume('hello'))

if __name__ == '__main__': unittest.main()
