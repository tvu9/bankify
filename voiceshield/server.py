#!/usr/bin/env python3
"""Local development-only token and static file server. No third-party Python packages."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import base64
import hashlib
import hmac
import json
import os
import time
import secrets
import threading

ROOT = Path(__file__).resolve().parent / 'dist'
HOST = '127.0.0.1'
PORT = 3000
API_KEY = os.getenv('LIVEKIT_API_KEY', 'devkey')
API_SECRET = os.getenv('LIVEKIT_API_SECRET', 'secret')
PUBLIC_WS_URL = os.getenv('LIVEKIT_PUBLIC_URL', 'wss://10.255.104.249:8443')
ROOM = 'fraud-test'
# Loopback-only worker token. Set explicitly in the environment for stable restarts.
WORKER_TOKEN = os.getenv('VOICESHIELD_WORKER_TOKEN') or secrets.token_urlsafe(32)
STATE_LOCK = threading.Lock()
STATE_CHANGED = threading.Condition(STATE_LOCK)
STATE_VERSION = 0
SSE_SLOTS = threading.BoundedSemaphore(8)  # avoid unbounded thread/stream growth
FRAUD = {'status': 'offline', 'asr_status': 'offline', 'risk_level': 'unresolved',
         'indicators': [], 'identity_status': 'not_checked',
         'reason': 'Fraud-language monitoring not connected', 'updated_at': 0,
         'audio_level_dbfs': None, 'asr_latency_ms': None, 'transcript_available': False,
         'verification_status': 'not_checked', 'verification_method': None}
FRAUD_VERSION = 0
VERIFICATION = {'status': 'not_checked', 'method': None}

DETECTION = {'status': 'offline', 'updated_at': 0, 'verdict': None,
             'p_fake': None, 'latency_ms': None, 'sample_age_ms': None,
             'queue_wait_ms': None, 'model_ms': None, 'preprocess_ms': None,
             'stale': False, 'dropped': 0, 'windows': 0, 'last_result_at': None,
             'alert': False, 'message': 'Detector not connected',
             'quality': None, 'level_dbfs': None, 'clipping_pct': None,
             'audio_activity': False}


def b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode()


def make_token(role):
    now = int(time.time())
    header = {'alg': 'HS256', 'typ': 'JWT'}
    payload = {
        'iss': API_KEY, 'sub': role, 'iat': now, 'nbf': now, 'exp': now + 3600,
        'video': {'roomJoin': True, 'room': ROOM, 'canPublish': True,
                  'canSubscribe': True, 'canPublishData': False,
                  'canPublishSources': ['microphone']},
    }
    signing_input = f'{b64(json.dumps(header,separators=(",", ":")).encode())}.{b64(json.dumps(payload,separators=(",", ":")).encode())}'
    signature = b64(hmac.new(API_SECRET.encode(), signing_input.encode(), hashlib.sha256).digest())
    return f'{signing_input}.{signature}'


class Handler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'  # required for reliable long-lived SSE streams
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/api/token':
            role = parse_qs(parsed.query).get('role', [''])[0]
            if role not in ('caller', 'receiver'):
                return self.json_response(400, {'error': 'role must be caller or receiver'})
            return self.json_response(200, {'token': make_token(role), 'url': PUBLIC_WS_URL})
        if parsed.path == '/api/fraud':
            with STATE_LOCK:
                result = dict(FRAUD)
            if time.time() - result.get('updated_at', 0) > 20:
                result.update(status='offline', asr_status='offline', risk_level='unresolved',
                              indicators=[], identity_status='not_checked',
                              reason='Fraud monitor offline; no conclusion')
            return self.json_response(200, result)
        if parsed.path == '/api/fraud/events':
            if not SSE_SLOTS.acquire(blocking=False):
                return self.json_response(503, {'error': 'too many subscribers'})
            try:
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-cache, no-transform')
                self.send_header('Connection', 'keep-alive')
                self.end_headers()
                seen = -1
                while True:
                    with STATE_CHANGED:
                        STATE_CHANGED.wait_for(lambda: FRAUD_VERSION != seen, timeout=8)
                        seen = FRAUD_VERSION
                        payload = dict(FRAUD)
                    if time.time() - payload.get('updated_at',0) > 20:
                        payload.update(status='offline', asr_status='offline', risk_level='unresolved',
                                       indicators=[], identity_status='not_checked',
                                       reason='Fraud monitor offline; no conclusion')
                    self.wfile.write(('data: ' + json.dumps(payload, separators=(',', ':')) + '\n\n').encode())
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            finally:
                SSE_SLOTS.release()
            return
        if parsed.path == '/api/detection':
            with STATE_LOCK:
                result = dict(DETECTION)
            # Never show stale risk values as if they were from the current call.
            if time.time() - result['updated_at'] > 12:
                result = {'status': 'offline', 'verdict': None, 'p_fake': None,
                          'latency_ms': None, 'alert': False, 'stale': False, 'sample_age_ms': None,
                          'last_result_at': None,
                          'windows': 0, 'message': 'Detector offline or waiting for audio'}
            return self.json_response(200, result)
        if parsed.path == '/api/detection/events':
            # EventSource streams same-origin only. Periodic snapshot fallback remains.
            if not SSE_SLOTS.acquire(blocking=False):
                return self.json_response(503, {'error': 'too many subscribers'})
            try:
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-cache, no-transform')
                self.send_header('Connection', 'keep-alive')
                self.end_headers()
                seen = -1
                while True:
                    with STATE_CHANGED:
                        STATE_CHANGED.wait_for(lambda: STATE_VERSION != seen, timeout=12)
                        seen = STATE_VERSION
                        payload = dict(DETECTION)
                    if time.time() - payload.get('updated_at', 0) > 12:
                        payload = {'status': 'offline', 'message': 'Detector offline',
                                   'verdict': None, 'p_fake': None, 'alert': False}
                    data = 'data: ' + json.dumps(payload, separators=(',', ':')) + '\n\n'
                    self.wfile.write(data.encode('utf-8'))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            finally:
                SSE_SLOTS.release()
            return
        if parsed.path == '/health':
            return self.json_response(200, {'status': 'ok'})
        if parsed.path == '/':
            self.path = '/index.html'
        return super().do_GET()

    def do_POST(self):
        global STATE_VERSION, FRAUD_VERSION
        if urlparse(self.path).path == '/api/internal/verification':
            if self.client_address[0] not in ('127.0.0.1', '::1'):
                return self.json_response(403, {'error': 'local only'})
            if not secrets.compare_digest(self.headers.get('X-Worker-Token', ''), WORKER_TOKEN):
                return self.json_response(403, {'error': 'unauthorized'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length < 1 or length > 512:
                    return self.json_response(413, {'error': 'invalid body length'})
                event = json.loads(self.rfile.read(length))
                if not isinstance(event, dict):
                    raise ValueError('expected object')
                method = event.get('method')
                status = event.get('status')
                if status not in ('not_checked','operator_attested','failed'):
                    raise ValueError('invalid verification status')
                if status == 'operator_attested' and method not in ('known_number_callback','verified_bank_session'):
                    raise ValueError('trusted verification method required')
                with STATE_CHANGED:
                    VERIFICATION.update(status=status, method=method if status == 'operator_attested' else None)
                    FRAUD['verification_status'] = status
                    FRAUD['verification_method'] = VERIFICATION['method']
                    FRAUD['updated_at'] = time.time()
                    FRAUD_VERSION += 1
                    STATE_CHANGED.notify_all()
                return self.json_response(200, {'ok': True})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self.json_response(400, {'error': str(exc)})
        if urlparse(self.path).path == '/api/internal/fraud':
            if self.client_address[0] not in ('127.0.0.1', '::1'):
                return self.json_response(403, {'error': 'local only'})
            if not secrets.compare_digest(self.headers.get('X-Worker-Token', ''), WORKER_TOKEN):
                return self.json_response(403, {'error': 'unauthorized'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length < 1 or length > 4096:
                    return self.json_response(413, {'error': 'invalid body length'})
                event = json.loads(self.rfile.read(length))
                if not isinstance(event, dict):
                    raise ValueError('expected object')
                status = event.get('status')
                if status not in ('active', 'listening', 'waiting', 'error', 'offline'):
                    raise ValueError('invalid status')
                allowed = {'credential_request','urgent_transfer','secrecy_pressure',
                           'remote_access','claimed_bank_identity'}
                if event.get('reset') is True:
                    result = {'status':status, 'asr_status':status, 'risk_level':'unresolved',
                              'indicators':[], 'identity_status':'not_checked',
                              'reason':'New caller: awaiting scam-language evidence'}
                else:
                    indicators = event.get('indicators', [])
                    if not isinstance(indicators, list):
                        raise ValueError('indicators must be a list')
                    result = {'status':status,
                              'asr_status':status,
                              'risk_level':event.get('risk_level') if event.get('risk_level') in ('high','elevated','unresolved') else 'unresolved',
                              'indicators':sorted(set(x for x in indicators if isinstance(x,str) and x in allowed)),
                              'identity_status':event.get('identity_status') if event.get('identity_status') in ('unverified','not_checked') else 'not_checked',
                              'reason':str(event.get('reason', ''))[:180]}
                    if status != 'active':
                        result.update(risk_level='unresolved',indicators=[],identity_status='not_checked')
                result['transcript_available'] = event.get('transcript_available') is True
                for metric, low, high in (('audio_level_dbfs', -90, 0), ('asr_latency_ms', 0, 120000)):
                    value = event.get(metric)
                    if isinstance(value, (int, float)) and not isinstance(value, bool) and __import__('math').isfinite(value):
                        result[metric] = round(max(low, min(high, float(value))), 1)
                    else:
                        result[metric] = None
                result['updated_at'] = time.time()
                with STATE_CHANGED:
                    if event.get('reset') is True:
                        VERIFICATION.update(status='not_checked', method=None)
                    result['verification_status'] = VERIFICATION['status']
                    result['verification_method'] = VERIFICATION['method']
                    FRAUD.update(result)
                    FRAUD_VERSION += 1
                    STATE_CHANGED.notify_all()
                return self.json_response(200, {'ok': True})
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                return self.json_response(400, {'error': str(exc)})
        if urlparse(self.path).path != '/api/internal/detection':
            return self.json_response(404, {'error': 'not found'})
        # A local process may publish updates. Never accept them from outside loopback.
        if self.client_address[0] not in ('127.0.0.1', '::1'):
            return self.json_response(403, {'error': 'local only'})
        if not secrets.compare_digest(self.headers.get('X-Worker-Token', ''), WORKER_TOKEN):
            return self.json_response(403, {'error': 'unauthorized'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 1 or length > 8192:
                return self.json_response(413, {'error': 'invalid body length'})
            event = json.loads(self.rfile.read(length))
            if not isinstance(event, dict):
                raise ValueError('expected object')
            status = event.get('status')
            if status not in ('monitoring', 'analyzing', 'result', 'quality', 'error', 'offline'):
                raise ValueError('invalid status')
            normalized = {
                'status': status, 'updated_at': time.time(), 'last_result_at': None,
                'verdict': event.get('verdict') if event.get('verdict') in ('REAL','FAKE','UNSURE') else None,
                'p_fake': None, 'latency_ms': None, 'sample_age_ms': None,
                'queue_wait_ms': None, 'model_ms': None, 'preprocess_ms': None,
                'stale': bool(event.get('stale', False)),
                'dropped': max(0, min(int(event.get('dropped', 0)), 999999)),
                'alert': bool(event.get('alert', False)),
                'windows': max(0, min(int(event.get('windows',0)), 999999)),
                'message': str(event.get('message',''))[:180],
                'quality': event.get('quality') if event.get('quality') in ('normal','quiet','loud','clipping','invalid') else None,
                'level_dbfs': None, 'clipping_pct': None,
                'audio_activity': bool(event.get('audio_activity', False)),
            }
            for key in ('p_fake','latency_ms','sample_age_ms','queue_wait_ms','preprocess_ms','model_ms'):
                val = event.get(key)
                if isinstance(val,(int,float)) and not isinstance(val,bool):
                    normalized[key] = max(0.,min(float(val),1. if key=='p_fake' else 1e6))
            for key, maximum in (('level_dbfs', 0.), ('clipping_pct', 100.)):
                val = event.get(key)
                if isinstance(val, (int, float)) and not isinstance(val, bool) and __import__('math').isfinite(val):
                    normalized[key] = max(-90., min(float(val), maximum)) if key == 'level_dbfs' else max(0., min(float(val), maximum))
            with STATE_CHANGED:
                if event.get('reset') is True:
                    # New call/track must never inherit a previous caller's risk/quality.
                    pass
                elif status == 'quality':
                    # Audio telemetry never overwrites an existing model verdict.
                    for key in ('status', 'verdict', 'p_fake', 'latency_ms', 'preprocess_ms',
                                'model_ms', 'queue_wait_ms', 'sample_age_ms', 'stale',
                                'dropped', 'last_result_at', 'alert', 'windows', 'message'):
                        normalized[key] = DETECTION.get(key)
                elif status in ('analyzing', 'monitoring'):
                    # Retain latest completed assessment only within its freshness window.
                    last = DETECTION.get('last_result_at')
                    if last and time.time() - last <= 10:
                        for key in ('verdict', 'p_fake', 'latency_ms', 'preprocess_ms',
                                    'model_ms', 'queue_wait_ms', 'sample_age_ms', 'stale',
                                    'dropped', 'last_result_at'):
                            normalized[key] = DETECTION.get(key)
                        normalized['alert'] = bool(DETECTION.get('alert'))
                if status != 'quality' and not event.get('reset'):
                    for key in ('quality', 'level_dbfs', 'clipping_pct', 'audio_activity'):
                        normalized[key] = DETECTION.get(key)
                if status == 'result':
                    normalized['last_result_at'] = normalized['updated_at']
                DETECTION.update(normalized)
                STATE_VERSION += 1
                STATE_CHANGED.notify_all()
            return self.json_response(200, {'ok': True})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return self.json_response(400, {'error': str(exc)})

    def json_response(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def end_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self' wss://10.255.104.249:8443; media-src 'self' blob:; object-src 'none'; frame-ancestors 'none'")
        super().end_headers()


if __name__ == '__main__':
    if not (ROOT / 'index.html').exists():
        raise SystemExit('Run npm install && npm run build first')
    print(f'VoiceShield running at http://{HOST}:{PORT} (proxy with Caddy for phones)')
    print('WARNING: Test-only token endpoint. Any LAN visitor can impersonate caller or receiver.')
    print('Detection worker token configured (value not printed).')
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
