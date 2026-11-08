#!/usr/bin/env python3
"""Clip-level evaluation on consented, labeled data; no network upload, no training.

Manifest format and licensing instructions: docs/VOICESHIELD_V3.md.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path
import numpy as np
try:
    from .v3_common import read_manifest, load_audio, window_starts, write_csv, SCORE_FIELDS, metrics, by_channel
    from .stream_utils import has_usable_speech
except ImportError:
    from v3_common import read_manifest, load_audio, window_starts, write_csv, SCORE_FIELDS, metrics, by_channel
    from stream_utils import has_usable_speech


def evaluate(rows, model, hop, max_windows):
    results = []
    skipped = 0
    for i,r in enumerate(rows,1):
        try:
            audio = load_audio(r['_resolved_path'])
            starts = window_starts(len(audio), hop_s=hop, max_windows=max_windows)
            scores, times, preps = [], [], []
            for start in starts:
                window = audio[start:start+64_000]
                if not has_usable_speech(window):
                    continue
                score, timing = model.analyze_timed(window)
                scores.append(float(score))
                times.append(float(timing['inference_ms']))
                preps.append(float(timing['preprocess_ms']))
            if not scores:
                print(f'SKIP {r["sample_id"]}: shorter than 4s or insufficient energy',flush=True)
                skipped += 1
                continue
            result = {k:r.get(k,'') for k in SCORE_FIELDS}
            result.update(score=round(float(np.mean(scores)),7), n_windows=len(scores),
                          duration_s=round(len(audio)/16000,2),
                          inference_ms=round(float(np.mean(times)),2),
                          preprocess_ms=round(float(np.mean(preps)),2))
            results.append(result)
            print(f'[{i}/{len(rows)}] {r["sample_id"]}: {result["score"]:.4f} ({len(scores)} windows)',flush=True)
        except Exception as exc:
            print(f'SKIP {r["sample_id"]}: {exc}',file=sys.stderr,flush=True)
            skipped += 1
    return results, skipped


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',required=True)
    p.add_argument('--split',choices=['train','val','test'],required=True)
    p.add_argument('--out',required=False,help='Output clip-score CSV; never overwritten')
    p.add_argument('--check-only',action='store_true',help='Validate labels/splits/paths without downloading model')
    p.add_argument('--hop',type=float,default=2)
    p.add_argument('--max-windows',type=int,default=12)
    p.add_argument('--device',choices=['cpu','mps','cuda'],default='cpu')
    args=p.parse_args()
    if args.hop <= 0 or args.max_windows < 1 or args.max_windows > 200: p.error('Invalid hop/max-windows')
    rows_all=read_manifest(args.manifest)
    rows=[r for r in rows_all if r['split']==args.split]
    if not rows: p.error(f'No {args.split} rows')
    print(f'Manifest OK: {len(rows_all)} clips, {len(rows)} in {args.split}; source/speaker splits checked.',flush=True)
    if args.check_only: return
    if not args.out: p.error('--out required except with --check-only')
    if Path(args.out).exists(): p.error(f'Output already exists: {args.out}')
    os.environ['VOICE_DETECT_DEVICE']=args.device
    try:
        from .pella_backend import PellaV2
    except ImportError:
        from pella_backend import PellaV2
    model=PellaV2()
    # warm-up outside scored runtime
    model.analyze_timed(np.full(64_000, 0.012, dtype=np.float32))
    result, skipped=evaluate(rows,model,args.hop,args.max_windows)
    if not result: raise SystemExit('No valid clips; score file not written')
    write_csv(args.out,result,SCORE_FIELDS)
    print(json.dumps({'split':args.split, 'saved':str(args.out),'skipped':skipped,
                      'threshold_0_5_diagnostic_only':metrics(result,0.5),
                      'channels':by_channel(result,0.5)},indent=2))
    print('Scores are RAW, not calibrated. Do not select thresholds from the test split.')

if __name__=='__main__': main()
