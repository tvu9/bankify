"""VoiceShield V3 evaluation utilities: no model import until explicitly requested.

All scores are initially uncalibrated PellaV2 sigmoid scores, not probabilities.
"""
from __future__ import annotations
import csv
import hashlib
import math
from pathlib import Path
from collections import defaultdict
import numpy as np

SR = 16_000
WINDOW = 4 * SR
FIELDS = ['sample_id','path','label','split','source_id','speaker_id','generator_id','channel','license']
SCORE_FIELDS = [*FIELDS, 'score', 'n_windows', 'duration_s', 'inference_ms', 'preprocess_ms']


def label_to_int(v):
    v = str(v).strip().lower()
    if v in ('real','human','0'):
        return 0
    if v in ('fake','synthetic','ai','1'):
        return 1
    raise ValueError(f'Unknown label {v!r}; use real/fake (or 0/1)')


def read_manifest(path):
    path = Path(path).expanduser().resolve()
    with path.open(newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        missing = set(['sample_id','path','label','split','source_id']) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f'Manifest missing required columns: {sorted(missing)}')
        rows = list(reader)
    if not rows:
        raise ValueError('Manifest is empty')
    seen, group_splits = set(), defaultdict(set)
    for i, row in enumerate(rows, start=2):
        sid = row['sample_id'].strip()
        if not sid or sid in seen:
            raise ValueError(f'Duplicate/missing sample_id at row {i}: {sid!r}')
        seen.add(sid)
        split = row['split'].strip().lower()
        if split not in ('train','val','test'):
            raise ValueError(f'Invalid split at row {i}: {split!r}')
        row['split'] = split
        row['label'] = 'fake' if label_to_int(row['label']) else 'real'
        row['path'] = row['path'].strip()
        if not row['path']:
            raise ValueError(f'Empty path at row {i}')
        for group in ('source_id','speaker_id'):
            value = (row.get(group) or '').strip()
            if group == 'source_id' and not value:
                raise ValueError(f'Empty source_id at row {i}')
            if value:
                group_splits[(group,value)].add(split)
        resolved = (path.parent / row['path']).resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f'Missing audio for sample {sid}: {resolved}')
        row['_resolved_path'] = str(resolved)
    leakage = [(name,val,sorted(splits)) for (name,val), splits in group_splits.items() if len(splits) > 1]
    if leakage:
        raise ValueError(f'Train/validation/test source or speaker leakage: {leakage[:8]}')
    return rows


def load_audio(path, max_seconds=180):
    import soundfile as sf
    from scipy.signal import resample_poly
    p = Path(path)
    with sf.SoundFile(p) as f:
        rate = f.samplerate
        if rate < 4_000 or rate > 192_000:
            raise ValueError(f'Unexpected sample rate {rate} Hz: {p}')
        if f.frames / rate > max_seconds:
            raise ValueError(f'Clip exceeds maximum {max_seconds}s: {p}')
        arr = f.read(dtype='float32', always_2d=True)
    if arr.shape[1] > 2:
        raise ValueError('Expected mono/stereo audio, not multichannel')
    x = arr.mean(axis=1)
    if rate != SR:
        gcd = math.gcd(rate, SR)
        x = resample_poly(x, SR//gcd, rate//gcd)
    x = np.asarray(x, dtype=np.float32)
    if not np.all(np.isfinite(x)):
        raise ValueError(f'Nonfinite audio in {p}')
    return np.ascontiguousarray(x)


def window_starts(length, hop_s=2., max_windows=16):
    if length < WINDOW:
        return []
    hop = max(1, round(hop_s * SR))
    seq = list(range(0, length - WINDOW + 1, hop))
    if seq[-1] != length - WINDOW:
        seq.append(length - WINDOW)
    if len(seq) > max_windows:
        seq = [seq[int(round(i * (len(seq) - 1) / (max_windows - 1)))]
               for i in range(max_windows)] if max_windows > 1 else [seq[0]]
    return sorted(set(seq))


def write_csv(path, rows, fields):
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f'Will not overwrite existing file: {path}')
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def read_scores(path, split=None):
    with Path(path).expanduser().open(newline='', encoding='utf-8-sig') as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise ValueError('Score file is empty')
    for r in rows:
        r['score'] = float(r['score'])
        if not np.isfinite(r['score']) or not 0 <= r['score'] <= 1:
            raise ValueError('Nonfinite/out-of-range score')
        r['label'] = 'fake' if label_to_int(r['label']) else 'real'
        if split and r['split'] != split:
            raise ValueError(f'Score file contains split {r["split"]!r} not {split!r}')
    return rows


def metrics(rows, threshold=0.5, bins=10):
    labels = np.array([label_to_int(r['label']) for r in rows], dtype=int)
    scores = np.array([float(r['score']) for r in rows], dtype=float)
    if not len(scores) or not np.all(np.isfinite(scores)):
        raise ValueError('No finite scores')
    pred = scores >= threshold
    real, fake = labels == 0, labels == 1
    tp = int((pred & fake).sum()); fp = int((pred & real).sum())
    tn = int((~pred & real).sum()); fn = int((~pred & fake).sum())
    result = {'n':len(rows),'real':int(real.sum()),'fake':int(fake.sum()),'threshold':float(threshold),
              'TP':tp,'FP':fp,'TN':tn,'FN':fn,
              'fake_recall':tp/(tp+fn) if tp+fn else None,
              'real_false_positive_rate':fp/(fp+tn) if fp+tn else None,
              'accuracy':(tp+tn)/len(rows), 'brier':float(np.mean((scores-labels)**2))}
    if real.any() and fake.any():
        # Pairwise AUC using tie-aware average ranks, no sklearn dependency.
        order = np.argsort(scores, kind='mergesort')
        ranks = np.empty(len(scores), dtype=float)
        sorted_scores = scores[order]; i = 0
        while i < len(scores):
            j = i+1
            while j < len(scores) and sorted_scores[j] == sorted_scores[i]: j += 1
            ranks[order[i:j]] = ((i+1)+j)/2
            i = j
        result['roc_auc'] = float((ranks[fake].sum() - fake.sum()*(fake.sum()+1)/2)/(fake.sum()*real.sum()))
    else:
        result['roc_auc'] = None
    index = np.minimum((scores*bins).astype(int), bins-1)
    result['ece'] = float(sum((index==b).mean()*abs(float(scores[index==b].mean())-float(labels[index==b].mean()))
                              for b in range(bins) if (index==b).any()))
    return result


def by_channel(rows, threshold):
    channels = sorted(set((r.get('channel') or 'unspecified') for r in rows))
    return {ch:metrics([r for r in rows if (r.get('channel') or 'unspecified')==ch],threshold)
            for ch in channels}


def file_sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''): h.update(chunk)
    return h.hexdigest()
