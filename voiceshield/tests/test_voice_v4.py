import importlib.util
import json
from pathlib import Path
import sys
import threading
import unittest
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'fraud_monitor'))
from risk_engine import analyze_text, CallRisk


class TextScreeningTests(unittest.TestCase):
    def test_credential_request(self):
        self.assertIn('credential_request', analyze_text('Please tell me your verification code.'))

    def test_no_credential_warning_for_safety_message(self):
        self.assertNotIn('credential_request', analyze_text('Never share your verification code with anyone.'))

    def test_transfer(self):
        self.assertIn('urgent_transfer', analyze_text('Immediately transfer money to another account.'))

    def test_benign_transfer(self):
        self.assertNotIn('urgent_transfer', analyze_text('My bank made a transfer last month.'))

    def test_secrecy(self):
        self.assertIn('secrecy_pressure', analyze_text("Don't tell anyone about this."))

    def test_identity_claim_unverified(self):
        r = CallRisk().add("I'm calling from your bank.")
        self.assertEqual(r['identity_status'], 'unverified')
        self.assertEqual(r['risk_level'], 'elevated')

    def test_no_match_does_not_mean_safe(self):
        r = CallRisk().add('Hello how are you doing?')
        self.assertEqual(r['risk_level'], 'unresolved')

    def test_resets(self):
        r = CallRisk(); r.add('Tell me your password'); r.reset()
        self.assertEqual(r.add('Hello')['risk_level'], 'unresolved')

    def test_bounded_evidence(self):
        r = CallRisk()
        for i in range(50): r.add('Tell me your password')
        self.assertLessEqual(len(r.events), 24)


class WebAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location('vs4_server', ROOT / 'server.py')
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)
        cls.mod.WORKER_TOKEN = 'test-token-only'
        cls.http = cls.mod.ThreadingHTTPServer(('127.0.0.1', 0), cls.mod.Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f'http://127.0.0.1:{cls.http.server_address[1]}'

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join(timeout=2)

    def post(self, endpoint, event, token='test-token-only'):
        request = urllib.request.Request(self.base + endpoint, data=json.dumps(event).encode(), method='POST',
                                         headers={'Content-Type': 'application/json', 'X-Worker-Token':token})
        return urllib.request.urlopen(request, timeout=2)

    def get(self, endpoint):
        return json.load(urllib.request.urlopen(self.base + endpoint, timeout=2))

    def test_rejects_unauthorized_fraud_event(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post('/api/internal/fraud', {'status': 'active'}, token='wrong')
        self.assertEqual(ctx.exception.code, 403)

    def test_fraud_screening_event(self):
        self.post('/api/internal/fraud', {'status':'active','risk_level':'high',
                  'indicators':['credential_request','unknown'],
                  'identity_status':'unverified', 'reason':'Sensitive request detected'})
        state = self.get('/api/fraud')
        self.assertEqual(state['risk_level'], 'high')
        self.assertEqual(state['indicators'], ['credential_request'])
        self.assertNotIn('transcript', state)

    def test_new_caller_resets_fraud(self):
        self.post('/api/internal/fraud', {'status':'listening','reset':True})
        state = self.get('/api/fraud')
        self.assertEqual(state['risk_level'], 'unresolved')
        self.assertEqual(state['indicators'], [])

    def test_verification_requires_known_channel(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post('/api/internal/verification', {'status':'operator_attested','method':'guess'})
        self.assertEqual(ctx.exception.code, 400)

    def test_manual_verification_resets_with_call(self):
        self.post('/api/internal/verification', {'status':'operator_attested','method':'known_number_callback'})
        self.assertEqual(self.get('/api/fraud')['verification_status'], 'operator_attested')
        self.post('/api/internal/fraud', {'status':'listening','reset':True})
        self.assertEqual(self.get('/api/fraud')['verification_status'], 'not_checked')

    def test_original_detection_path_unchanged(self):
        self.assertEqual(self.get('/api/detection')['status'], 'offline')

    def test_status_rejects_bad_payload(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post('/api/internal/fraud', {'status':'anything'})
        self.assertEqual(ctx.exception.code, 400)


if __name__ == '__main__': unittest.main()
