import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'fraud_monitor'))
from risk_engine import analyze_text, CallRisk, HIGH_INDICATORS

CASES = {
    'credential_request': 'Tell me your password.',
    'card_data_request': 'Give me your credit card number.',
    'identity_data_request': 'Provide your social security number.',
    'mfa_approval': 'Approve the login request.',
    'security_disablement': 'Disable your two factor authentication.',
    'phishing_link': 'Click the link I just sent.',
    'payment_app_request': 'Send the money through Zelle.',
    'crypto_payment_request': 'Send bitcoin to my wallet.',
    'gift_card_payment': 'Read me the code on the gift card.',
    'wire_redirection': 'Wire the invoice to this new account.',
    'cash_courier': 'Our courier will pick up your cash.',
    'advance_fee': 'Pay the processing fee before you receive your prize.',
    'refund_overpayment': 'Send us back the extra money.',
    'account_takeover': 'Add my phone as your trusted device.',
    'extortion_payment': 'Pay me money or I will release it.',
    'money_mule': 'Keep a commission and send the rest.',
    'job_fee': 'Pay the training fee before you start the job.',
    'recovery_scam': 'Recover your lost money after you pay.',
    'prize_fee': 'You have won a prize but you must pay.',
    'romance_pressure': 'I love you please send me money.',
    'charity_pressure': 'Donate money to my private account for disaster relief.',
}
BENIGN = [
    'I bought a gift card yesterday.', 'We use Zelle sometimes.',
    'Bitcoin prices are volatile.', 'I am calling my bank tomorrow.',
    'Never share your verification code.', 'Do not click the link I sent.',
    'How is your family doing?', 'I need to pay rent next week.',
    'We discussed an investment without making any guarantees.',
    'For example, scammers may say tell me your password.',
    'We must never ask you for your PIN.',
    'This is your bank fraud department.',
]

class ExpandedRiskTests(unittest.TestCase):
    def test_high_categories(self):
        for category, sample in CASES.items():
            with self.subTest(category=category):
                self.assertIn(category, analyze_text(sample))
                self.assertIn(category, HIGH_INDICATORS)
    def test_benign_not_high(self):
        for sample in BENIGN:
            with self.subTest(sample=sample):
                self.assertFalse(HIGH_INDICATORS.intersection(analyze_text(sample)), analyze_text(sample))
    def test_safety_advice_does_not_cancel_later_request(self):
        result = analyze_text('Never share your password. But send me your verification code.')
        self.assertIn('credential_request', result)
    def test_current_independent_from_history(self):
        clock=[0]; risk=CallRisk(clock=lambda:clock[0]); a=risk.add('Send the money through Zelle.')
        self.assertEqual('high', a['risk_level']); clock[0]=2
        b=risk.add('The weather is lovely.')
        self.assertEqual('unresolved', b['risk_level']); self.assertEqual('high', b['call_risk_level'])
        clock[0]=49; c=risk.add('Hello.')
        self.assertEqual('unresolved', c['call_risk_level'])
    def test_reset(self):
        r=CallRisk();r.add('Read me the code on the gift card.');r.reset()
        self.assertEqual('unresolved',r.add('Hello.')['call_risk_level'])
    def test_memory_contains_only_indicators(self):
        r=CallRisk();r.add('Give me your credit card number.')
        self.assertNotIn('credit card number',str(r.events))

if __name__=='__main__':unittest.main()
