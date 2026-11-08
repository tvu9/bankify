import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'fraud_monitor'))
from risk_engine import analyze_text, CallRisk

class TestScamIndicators(unittest.TestCase):
    def test_password(self): self.assertIn('credential_request', analyze_text('Tell me your password.'))
    def test_text_code(self): self.assertIn('credential_request', analyze_text('Read me the six digit code.'))
    def test_security_code(self): self.assertIn('credential_request', analyze_text('What is your security code?'))
    def test_advice(self): self.assertNotIn('credential_request', analyze_text('Never share your verification code.'))
    def test_hypothetical(self): self.assertNotIn('credential_request', analyze_text('For example, scammers might say tell me your password.'))
    def test_transfer(self): self.assertIn('urgent_transfer', analyze_text('Immediately transfer money to another account.'))
    def test_safe_account(self): self.assertIn('urgent_transfer', analyze_text('Move your money to a safe account.'))
    def test_normal_transfer(self): self.assertNotIn('urgent_transfer', analyze_text('My bank sent money last month.'))
    def test_remote(self): self.assertIn('remote_access', analyze_text('Please download AnyDesk.'))
    def test_secrecy(self): self.assertIn('secrecy_pressure', analyze_text("Don't tell anyone about this."))
    def test_claim(self): self.assertIn('claimed_bank_identity', analyze_text("I'm calling from your bank."))
    def test_greeting(self): self.assertEqual([], analyze_text('Hello, how are you?'))
    def test_no_proof(self): self.assertEqual('unresolved', CallRisk().add('Good morning')['risk_level'])
    def test_identity_unverified(self): self.assertEqual('unverified', CallRisk().add("I'm calling from your bank.")['identity_status'])
    def test_high(self): self.assertEqual('high', CallRisk().add('Tell me your password')['risk_level'])
    def test_bounded(self):
        r = CallRisk()
        for i in range(100): r.add('Tell me your password')
        self.assertLessEqual(len(r.events), 24)
    def test_reset(self):
        r = CallRisk(); r.add('Tell me your password'); r.reset()
        self.assertEqual('unresolved', r.add('Hello')['risk_level'])
    def test_expires(self):
        now = [0.0]
        r = CallRisk(clock=lambda: now[0])
        r.add('Tell me your password')
        now[0] = 46.0
        self.assertEqual('unresolved', r.add('Hello')['risk_level'])
    def test_no_word_content_stored(self):
        r = CallRisk(); r.add('Tell me your password')
        self.assertNotIn('password', str(r.events))

if __name__ == '__main__': unittest.main()
