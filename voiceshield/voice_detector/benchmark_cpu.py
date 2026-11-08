#!/usr/bin/env python3
"""Offline PellaV2 inference timing (no recordings; no LiveKit connection)."""
import argparse
import os
import statistics
import time

import numpy as np

try:
    from .pella_backend import PellaV2, SR, CROP
except ImportError:
    from pella_backend import PellaV2, SR, CROP


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runs', type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.runs <= 20:
        parser.error('runs must be 1 to 20')
    # Hard-disable MPS due to the reported native crash.
    os.environ['VOICE_DETECT_DEVICE'] = 'cpu'
    print('Loading PellaV2 for CPU benchmarking...', flush=True)
    before = time.perf_counter()
    model = PellaV2()
    print(f'load_seconds={time.perf_counter() - before:.2f}', flush=True)

    # Synthetic waveform has no semantic value: benchmarks runtime only.
    t = np.arange(CROP, dtype=np.float32) / SR
    x = 0.035 * np.sin(2 * np.pi * 230 * t) + 0.01 * np.sin(2 * np.pi * 442 * t)
    x = x.astype(np.float32)
    timings = []
    for i in range(args.runs + 1):
        _, ms = model.analyze_timed(x)
        if i == 0:
            print(f'warmup_ms={ms["inference_ms"]:.0f}', flush=True)
            continue
        timings.append(ms)
        print(f'run={i} preprocess_ms={ms["preprocess_ms"]:.0f} '
              f'model_ms={ms["model_ms"]:.0f} total_ms={ms["inference_ms"]:.0f}', flush=True)
    print(f'avg_inference_ms={statistics.mean(x["inference_ms"] for x in timings):.0f}', flush=True)
    print('If avg inference exceeds the audio hop, your CPU cannot analyze every window.')
    print('If avg inference approaches/exceeds 10000ms, live warnings cannot stay current.')


if __name__ == '__main__':
    main()
