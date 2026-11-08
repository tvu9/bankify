import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fraud_monitor'))
from risk_engine import CallRisk, analyze_text

class CurrentRiskTests(unittest.TestCase):
    def test_high_then_harmless(self):
        risk=CallRisk()
        a=risk.add('Tell me your password.')
        self.assertEqual('high',a['risk_level'])
        b=risk.add('How are you today?')
        self.assertEqual('unresolved',b['risk_level'])
        self.assertEqual([],b['indicators'])
        self.assertEqual('high',b['call_risk_level'])
        self.assertIn('credential_request',b['call_indicators'])
    def test_new_high_again(self):
        risk=CallRisk();risk.add('Tell me your password.')
        risk.add('How are you today?')
        self.assertEqual('high',risk.add('Move your money to a safe account.')['risk_level'])
    def test_history_expires(self):
        t=[0.0]; risk=CallRisk(clock=lambda:t[0]);risk.add('Tell me your password.')
        t[0]=46
        result=risk.add('Hi there')
        self.assertEqual('unresolved',result['risk_level'])
        self.assertEqual('unresolved',result['call_risk_level'])
    def test_reset(self):
        risk=CallRisk();risk.add('Tell me your password.')
        risk.reset(); result=risk.add('Hello')
        self.assertEqual([],result['call_indicators'])
    def test_no_raw_text_retained(self):
        risk=CallRisk();risk.add('Tell me your password.')
        self.assertNotIn('password',str(risk.events))
    def test_safe_advice(self):
        self.assertNotIn('credential_request',analyze_text('Never share your verification code.'))
if __name__=='__main__':unittest.main()
