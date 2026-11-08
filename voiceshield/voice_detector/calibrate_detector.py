#!/usr/bin/env python3
"""Offline calibration of PellaV2 clip scores using ONLY a held-out validation split.

No live-worker changes. Requires enough genuine/fake examples; test data is
optional for final, one-time evaluation and never influences fitting/thresholds.
"""
import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, logit
from scipy.stats import norm
try:
    from .v3_common import read_scores, label_to_int, metrics, by_channel, file_sha256
except ImportError:
    from v3_common import read_scores, label_to_int, metrics, by_channel, file_sha256


def platt_fit(scores, labels):
    x=logit(np.clip(np.array(scores,dtype=float),1e-6,1-1e-6))
    y=np.asarray(labels,dtype=float)
    if np.unique(y).size!=2: raise ValueError('Both classes required for calibration')
    # Non-negative slope enforces monotonicity: higher raw score never reduces risk.
    def objective(p):
        z=p[0]*x+p[1]
        return float(np.mean(np.logaddexp(0,z)-y*z)+0.001*(p[0]**2+p[1]**2))
    base_bias=float(logit(np.clip(y.mean(),0.01,0.99)))
    fit=minimize(objective,[1.,base_bias],method='L-BFGS-B',bounds=[(0.,15.),(-15.,15.)])
    if not fit.success: raise RuntimeError(f'Calibration optimizer failed: {fit.message}')
    return {'slope':float(fit.x[0]),'intercept':float(fit.x[1])}


def apply_calibration(scores,params):
    x=np.asarray(scores,dtype=float)
    return expit(params['slope']*logit(np.clip(x,1e-6,1-1e-6))+params['intercept'])


def wilson_upper(k,n,confidence=0.95):
    if n<=0: raise ValueError('n must be positive')
    z=float(norm.ppf(confidence))
    phat=k/n
    center=phat+z*z/(2*n)
    half=z*math.sqrt(phat*(1-phat)/n+z*z/(4*n*n))
    return float(min(1.,(center+half)/(1+z*z/n)))


def pick_threshold(calibrated,labels,target_fpr=0.05,confidence=0.95):
    scores=np.asarray(calibrated,float); y=np.asarray(labels,int)
    genuine=scores[y==0]; fake=scores[y==1]
    if not len(genuine) or not len(fake): raise ValueError('Both classes required')
    # Consider genuine and fake score boundaries. Exclude trivial no-alert thresholds.
    candidates=np.unique(scores)
    options=[]
    for threshold in candidates:
        fp=int((genuine>=threshold).sum())
        recall=float((fake>=threshold).mean())
        bound=wilson_upper(fp,len(genuine),confidence)
        if bound<=target_fpr and recall>0:
            options.append((recall,-threshold,float(threshold),bound,fp))
    if not options: return None
    best=max(options)
    return {'threshold':best[2],'validation_recall':best[0],
            'validation_false_positives':best[4], 'fpr_wilson_upper':best[3],
            'target_fpr':target_fpr,'confidence':confidence,
            'note':'Exploratory validation screening bound only; post-selection and dependent speakers can invalidate the nominal coverage.'}


def evaluate_rows(rows,params,threshold):
    copy=[]
    calibrated=apply_calibration([r['score'] for r in rows],params)
    for r,p in zip(rows,calibrated): copy.append({**r,'score':float(p)})
    return {'metrics':metrics(copy,threshold),'by_channel':by_channel(copy,threshold)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validation-scores',required=True)
    parser.add_argument('--test-scores',help='Independent test scores (never used for fitting or threshold choice)')
    parser.add_argument('--out',required=True)
    parser.add_argument('--max-fpr',type=float,default=0.05)
    parser.add_argument('--confidence',type=float,default=0.95)
    parser.add_argument('--min-per-class',type=int,default=100)
    args=parser.parse_args()
    if not 0 < args.max_fpr < 1: parser.error('--max-fpr must be between 0 and 1')
    if not 0.5 < args.confidence < 1: parser.error('--confidence must be between 0.5 and 1')
    if args.min_per_class<2: parser.error('--min-per-class must be >= 2')
    if Path(args.out).exists(): parser.error('Output exists; refuse overwrite')
    val=read_scores(args.validation_scores,'val')
    labels=np.array([label_to_int(r['label']) for r in val],dtype=int)
    real_n=int((labels==0).sum()); fake_n=int((labels==1).sum())
    if min(real_n,fake_n)<args.min_per_class:
        parser.error(f'Need >= {args.min_per_class} of EACH class in validation: got real={real_n}, fake={fake_n}. No calibration written.')
    source_ids=[r.get('source_id','').strip() for r in val]
    if any(not sid for sid in source_ids) or len(set(source_ids))!=len(source_ids):
        parser.error('Validation calibration requires one clip per independently sourced source_id; no codec duplicates allowed. Use a source-disjoint base validation set.')
    params=platt_fit([r['score'] for r in val],labels)
    cal=apply_calibration([r['score'] for r in val],params)
    picked=pick_threshold(cal,labels,args.max_fpr,args.confidence)
    result={'schema_version':1,'model':'PellaV2','unit':'clip_mean_over_4s_windows',
            'created_utc':datetime.now(timezone.utc).isoformat(),
            'validation_score_csv_sha256':file_sha256(args.validation_scores),
            'validation_counts':{'real':real_n,'fake':fake_n},
            'platt':params,'operating_point':picked,
            'validation':evaluate_rows(val,params,picked['threshold'] if picked else .5),
            'warnings':['Clip-level calibration does not automatically calibrate streaming window scores.',
                        'This artifact is OFFLINE ONLY and is not loaded by the live worker.',
                        'Threshold was selected on validation: Wilson upper value is a screening statistic, NOT a certified false-positive guarantee.',
                        'Correlated, overlapping windows and channel changes may alter false-alarm rates.',
                        'No risk score proves identity; require independent identity verification.']}
    if args.test_scores:
        test=read_scores(args.test_scores,'test')
        v_sources={r.get('source_id') for r in val if r.get('source_id')}
        t_sources={r.get('source_id') for r in test if r.get('source_id')}
        v_speakers={r.get('speaker_id') for r in val if r.get('speaker_id')}
        t_speakers={r.get('speaker_id') for r in test if r.get('speaker_id')}
        if v_sources & t_sources or v_speakers & t_speakers:
            parser.error('Validation/test source or speaker leakage detected')
        result['test_score_csv_sha256']=file_sha256(args.test_scores)
        result['test']=evaluate_rows(test,params,picked['threshold'] if picked else .5)
    Path(args.out).parent.mkdir(parents=True,exist_ok=True)
    Path(args.out).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'saved':args.out, 'validation_counts':result['validation_counts'],
                      'operating_point':picked,'test_metrics':result.get('test',{}).get('metrics')},indent=2))
    if picked is None:
        print('NO defensible operating threshold at requested false-positive bound; collect more representative data.',file=sys.stderr)
    print('NOT DEPLOYED: a separate controlled, call-level validation is needed before any runtime threshold change.')

if __name__=='__main__':main()
