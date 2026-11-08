#!/usr/bin/env python3
"""Evaluate trained PellaV2 on YOUR labeled audio: no file uploads, no training.

Usage:
 python voice_detector/evaluate_clips.py --real-dir ~/tests/human --fake-dir ~/tests/ai
Optional --phone-emulation applies band limiting + 8k mu-law to approximate a
narrowband phone channel, not a substitute for a true phone-call recording.
"""
import argparse
import math
from pathlib import Path
import numpy as np

try:
    from .pella_backend import PellaV2
except ImportError:
    from pella_backend import PellaV2


def read_audio(path, emulate_phone=False):
    import soundfile as sf
    from scipy.signal import resample_poly, butter, sosfiltfilt
    x, rate = sf.read(path, dtype='float32', always_2d=True)
    x = x.mean(axis=1)
    if rate != 16000:
        gcd = math.gcd(rate, 16000)
        x = resample_poly(x, 16000 // gcd, rate // gcd).astype(np.float32)
    if emulate_phone and len(x) > 128:
        sos = butter(4, [300, 3400], btype='bandpass', fs=16000, output='sos')
        x = sosfiltfilt(sos, x).astype(np.float32)
        x = resample_poly(x, 1, 2).astype(np.float32)
        # G.711-like mu-law companding in the normalized domain, then expand.
        mu = 255.0
        companded = np.sign(x) * np.log1p(mu * np.abs(np.clip(x, -1, 1))) / np.log1p(mu)
        levels = np.round((companded + 1) * 127.5) / 127.5 - 1
        x = np.sign(levels) * (np.expm1(np.abs(levels) * np.log1p(mu)) / mu)
        x = resample_poly(x, 2, 1).astype(np.float32)
    return x


def four_second_windows(x):
    width = 4 * 16000
    hop = 2 * 16000
    if len(x) <= width:
        yield x
    else:
        starts = list(range(0, len(x) - width + 1, hop))
        final = len(x) - width
        if starts[-1] != final:
            starts.append(final)
        for start in starts:
            yield x[start:start + width]


def main():
    ap = argparse.ArgumentParser(description='Evaluate PellaV2 on labeled real/fake WAV/FLAC files')
    ap.add_argument('--real-dir', required=True)
    ap.add_argument('--fake-dir', required=True)
    ap.add_argument('--phone-emulation', action='store_true')
    args = ap.parse_args()
    groups = []
    for name, label in [(args.real_dir, 0), (args.fake_dir, 1)]:
        files = [p for p in Path(name).rglob('*') if p.suffix.lower() in ('.wav', '.flac', '.ogg')]
        if not files:
            raise SystemExit(f'No WAV/FLAC/OGG test files in {name}')
        groups.append((label, sorted(files)))
    model = PellaV2()
    rows = []
    for label, paths in groups:
        for path in paths:
            try:
                x = read_audio(path, args.phone_emulation)
                scores = [model.analyze(y) for y in four_second_windows(x)]
                # Mean is deliberately conservative about single-segment spikes.
                score = float(np.mean(scores))
                rows.append((label, score))
                print(f'{path.name:<34} known={"FAKE" if label else "REAL":4} score={score:.3f}', flush=True)
            except Exception as e:
                print(f'SKIPPED {path}: {e}', flush=True)
    if not rows:
        raise SystemExit('No valid evaluations.')
    y = np.array([r[0] for r in rows], dtype=np.int32)
    p = np.array([r[1] for r in rows])
    print('\nThreshold sweep (on these samples only — NOT a production calibration):')
    print('Threshold    fake recall    real false alarms')
    for threshold in (0.35, 0.45, 0.50, 0.60, 0.70, 0.80):
        pred = p >= threshold
        recall = float(np.mean(pred[y == 1])) if (y == 1).any() else float('nan')
        false_alarms = float(np.mean(pred[y == 0])) if (y == 0).any() else float('nan')
        print(f'{threshold:.2f}          {recall:6.1%}         {false_alarms:6.1%}')
    print('\nThis tests 4-second segments. The live alert also requires repeated elevated windows.')

if __name__ == '__main__':
    main()
