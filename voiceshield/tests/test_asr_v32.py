import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

class HybridTests(unittest.TestCase):
    def test_asr_no_vad_filter(self):
        source=(ROOT/'fraud_monitor/asr_backend.py').read_text()
        self.assertIn('vad_filter=False',source)
    def test_asr_only_subscribes_to_caller(self):
        source=(ROOT/'fraud_monitor/livekit_fraud.py').read_text()
        self.assertIn('participant.identity == CALLER',source)
    def test_audio_quality_diagnostics(self):
        source=(ROOT/'fraud_monitor/livekit_fraud.py').read_text()
        self.assertIn('audio_level_dbfs',source)
        self.assertIn('words={words}',source)
    def test_no_default_transcript_logging(self):
        source=(ROOT/'fraud_monitor/livekit_fraud.py').read_text()
        self.assertIn("VOICE_ASR_DEBUG_TEXT', '0'",source)
    def test_web_keeps_v32_detection(self):
        import hashlib
        b=(ROOT/'baseline/server.py').read_text()
        c=(ROOT/'server.py').read_text()
        self.assertEqual(b[b.index("        if urlparse(self.path).path != '/api/internal/detection':"):],
                         c[c.index("        if urlparse(self.path).path != '/api/internal/detection':"):])
    def test_python_syntax(self):
        for f in ('server.py','fraud_monitor/livekit_fraud.py','fraud_monitor/asr_backend.py'):
            ast.parse((ROOT/f).read_text())

if __name__=='__main__': unittest.main()
