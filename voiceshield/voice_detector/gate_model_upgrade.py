#!/usr/bin/env python3
"""Evidence gate for replacing PellaV2 (never publishes or switches models).

Requires PAIRED held-out test clips and separate CPU benchmark reports.
Conservative gate; a passed gate still requires live call-level review.
"""
import argparse
import json
from pathlib import Path
try: from .v3_common import read_scores, metrics
except ImportError: from v3_common import read_scores, metrics


def evaluate_candidate(baseline,candidate,base_p95,cand_p95,min_clips=100):
    base={r['sample_id']:r for r in baseline}; alt={r['sample_id']:r for r in candidate}
    if len(base)!=len(baseline) or len(alt)!=len(candidate) or set(base)!=set(alt):
        raise ValueError('Need identical, unique held-out test sample IDs for baseline/candidate')
    for sid in base:
        if base[sid]['label']!=alt[sid]['label'] or base[sid].get('source_id')!=alt[sid].get('source_id'):
            raise ValueError(f'Label/source mismatch: {sid}')
    if len(base)<min_clips: raise ValueError(f'Need >= {min_clips} paired test clips, found {len(base)}')
    b=metrics(baseline,.5); c=metrics(candidate,.5)
    if not (b['real']>0 and b['fake']>0): raise ValueError('Both classes required')
    checks={
      'auc_improved_by_at_least_0_005':c['roc_auc']>=b['roc_auc']+.005,
      'false_positive_rate_not_higher':c['real_false_positive_rate']<=b['real_false_positive_rate'],
      'fake_recall_not_lower':c['fake_recall']>=b['fake_recall'],
      'cpu_p95_at_least_5pct_faster':cand_p95<=base_p95*.95,
    }
    return {'release_candidate_passes_screen':all(checks.values()),'checks':checks,
            'baseline':b,'candidate':c,'p95_ms':{'baseline':base_p95,'candidate':cand_p95},
            'note':'Threshold=0.5 is a fixed diagnostic comparison, not an optimized deployment rule. This gate does not approve banking use; test live call-level false alerts separately.'}


def get_p95(path):
    r=json.loads(Path(path).read_text())
    data=r.get('summary',r)
    if data.get('mode')!='pella' or not data.get('realtime'):
        raise ValueError('Need an actual pella mode, realtime streaming report; no mock/accelerated results')
    ms=data.get('inference_ms_p95')
    if not isinstance(ms,(int,float)) or ms<=0: raise ValueError('Missing p95 benchmark')
    if data.get('analyzed_windows',0)<10: raise ValueError('Benchmark must contain at least 10 analyzed windows')
    return float(ms)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline-scores',required=True)
    ap.add_argument('--candidate-scores',required=True)
    ap.add_argument('--baseline-benchmark',required=True)
    ap.add_argument('--candidate-benchmark',required=True)
    ap.add_argument('--min-clips',type=int,default=100)
    args=ap.parse_args()
    if args.min_clips<2: ap.error('--min-clips must be at least 2')
    result=evaluate_candidate(read_scores(args.baseline_scores,'test'),
                              read_scores(args.candidate_scores,'test'),
                              get_p95(args.baseline_benchmark),get_p95(args.candidate_benchmark),args.min_clips)
    print(json.dumps(result,indent=2))
    if not result['release_candidate_passes_screen']: raise SystemExit(2)

if __name__=='__main__':main()
