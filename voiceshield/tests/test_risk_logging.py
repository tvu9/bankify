import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'fraud_monitor'))
from risk_logging import format_risk_log
from risk_engine import CallRisk


class RiskLoggingTests(unittest.TestCase):
    def test_high_risk_logged(self):
        line = format_risk_log({'risk_level': 'high', 'call_risk_level': 'high',
                                'indicators': ['credential_request'],
                                'call_indicators': ['credential_request']})
        self.assertIn('current=HIGH call=HIGH', line)
        self.assertIn('credential_request', line)

    def test_history_remains_high_without_marking_current_high(self):
        now = [0.0]
        risk = CallRisk(clock=lambda: now[0])
        risk.add('Tell me your password')
        now[0] = 1.0
        line = format_risk_log(risk.add('The weather is nice today'))
        self.assertIn('current=UNRESOLVED call=HIGH', line)
        self.assertIn('call_flags=[credential_request]', line)
        self.assertIn('current_flags=[none]', line)

    def test_history_expires(self):
        now = [0.0]
        risk = CallRisk(clock=lambda: now[0])
        risk.add('Tell me your password')
        now[0] = 46.0
        self.assertIn('current=UNRESOLVED call=UNRESOLVED',
                      format_risk_log(risk.add('The weather is nice today')))

    def test_clean_speech_displays_no_warning(self):
        self.assertEqual('[SCAM] current=UNRESOLVED call=UNRESOLVED '
                         'current_flags=[none] call_flags=[none]',
                         format_risk_log({'risk_level': 'unresolved',
                                          'call_risk_level': 'unresolved',
                                          'indicators': [], 'call_indicators': []}))

if __name__ == '__main__':
    unittest.main()
