#!/usr/bin/env python3
"""Operator attestation for a call, only AFTER out-of-band identity confirmation."""
import json
import os
import sys
import urllib.request

OPTIONS = {
    'verified-callback': {'status':'operator_attested','method':'known_number_callback'},
    'verified-bank-session': {'status':'operator_attested','method':'verified_bank_session'},
    'failed': {'status':'failed'},
    'reset': {'status':'not_checked'},
}
if len(sys.argv) != 2 or sys.argv[1] not in OPTIONS:
    raise SystemExit('Usage: python fraud_monitor/set_verification.py verified-callback|verified-bank-session|failed|reset')
token = os.getenv('VOICESHIELD_WORKER_TOKEN')
if not token: raise SystemExit('Set VOICESHIELD_WORKER_TOKEN in this Terminal first')
print('WARNING: This is a manual operator attestation, NOT automatic identity verification.')
if sys.argv[1].startswith('verified-'):
    check = input('Did you independently verify the caller through the stated trusted channel? Type YES: ')
    if check != 'YES': raise SystemExit('Cancelled')
body = json.dumps(OPTIONS[sys.argv[1]]).encode()
req = urllib.request.Request('http://127.0.0.1:3000/api/internal/verification', data=body, method='POST',
                             headers={'Content-Type':'application/json','X-Worker-Token':token})
with urllib.request.urlopen(req, timeout=3) as r:
    print(r.read().decode())
