#!/usr/bin/env python3
"""Compare externally scored candidate models on the same held-out clip IDs.

No second neural network is installed; plug other detectors in via their score CSV.
"""
import argparse
import json
from pathlib import Path
try: from .v3_common import read_scores, metrics, by_channel
except ImportError: from v3_common import read_scores, metrics, by_channel


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',required=True,help='PellaV2 test scores CSV')
    p.add_argument('--candidate',required=True,help='Other detector test scores CSV, same clip IDs')
    p.add_argument('--threshold',type=float,default=.5,help='Predefined comparison threshold (not optimized on test)')
    args=p.parse_args()
    if not 0<=args.threshold<=1: p.error('Bad threshold')
    base=read_scores(args.baseline,'test'); alt=read_scores(args.candidate,'test')
    key=lambda rows:{r['sample_id']:r for r in rows}
    a,b=key(base),key(alt)
    if len(a)!=len(base) or len(b)!=len(alt) or set(a)!=set(b): p.error('Paired sample IDs must match exactly, no duplicates')
    for sid in a:
        if a[sid]['label']!=b[sid]['label']: p.error(f'Label mismatch: {sid}')
        if a[sid].get('source_id')!=b[sid].get('source_id'): p.error(f'Source mismatch: {sid}')
    out={'test_only':True,'comparison_threshold':args.threshold,
         'baseline':{'metrics':metrics(base,args.threshold),'channels':by_channel(base,args.threshold)},
         'candidate':{'metrics':metrics(alt,args.threshold),'channels':by_channel(alt,args.threshold)},
         'note':'Use the same test audio with no threshold selection. Benchmark latency separately; this comparison cannot establish speed.'}
    print(json.dumps(out,indent=2))

if __name__=='__main__': main()
