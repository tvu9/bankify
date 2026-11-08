#!/usr/bin/env python3
"""Crash-isolated PellaV2 MPS benchmark. Does not join LiveKit or store audio.

Parent process invokes the actual PyTorch/MPS model in a child process, because
certain MPS failures are Objective-C SIGABRTs which Python cannot catch.
"""
import argparse
import json
import os
import platform
import statistics
import subprocess
import sys
import time


def child_run(device: str, runs: int):
    import numpy as np
    import torch
    from pella_backend import PellaV2, SR, CROP

    print(f"macOS={platform.mac_ver()[0]} arch={platform.machine()} python={sys.version.split()[0]} torch={torch.__version__}", flush=True)
    print(f"MPS built={torch.backends.mps.is_built()} available={torch.backends.mps.is_available()}", flush=True)
    if device == 'mps':
        if not torch.backends.mps.is_available():
            raise RuntimeError('MPS unavailable; verify Apple Silicon, OS, and PyTorch installation')
        # Exercise the MPS linear kernel independently, before loading PellaV2.
        with torch.inference_mode():
            x = torch.randn((64, 768), device='mps')
            layer = torch.nn.Linear(768, 768).to('mps').eval()
            layer(x)
            torch.mps.synchronize()
        print('MPS linear smoke test: PASSED', flush=True)

    os.environ['VOICE_DETECT_DEVICE'] = device
    start = time.perf_counter()
    model = PellaV2(device=device)
    print(f'load_seconds={time.perf_counter()-start:.2f}', flush=True)

    # Non-speech signal is for measuring speed ONLY, not detector accuracy.
    t = np.arange(CROP, dtype=np.float32) / SR
    audio = (0.05 * np.sin(2 * np.pi * 233 * t) + 0.02 * np.sin(2 * np.pi * 417 * t)).astype(np.float32)
    model_ms = []
    total_ms = []
    for i in range(runs+1):
        _score, timing = model.analyze_timed(audio)
        if device == 'mps':
            torch.mps.synchronize()
        label = 'warmup' if i == 0 else f'run_{i}'
        print(f'{label}: model_ms={timing["model_ms"]:.0f} total_ms={timing["inference_ms"]:.0f}', flush=True)
        if i:
            model_ms.append(timing['model_ms'])
            total_ms.append(timing['inference_ms'])
    report = {'device': device, 'runs': runs,
              'median_model_ms': round(statistics.median(model_ms)),
              'median_total_ms': round(statistics.median(total_ms))}
    print('RESULT_JSON=' + json.dumps(report, sort_keys=True), flush=True)


def parent_run(devices, runs, timeout):
    print('The model will run in a separate process; a native MPS abort will not crash this launcher.', flush=True)
    print('No LiveKit connection and no recording files will be created.', flush=True)
    reports = []
    for device in devices:
        print(f'\n=== Testing {device.upper()} ===', flush=True)
        env = os.environ.copy()
        env['VOICE_DETECT_DEVICE'] = device
        argv = [sys.executable, '-u', os.path.abspath(__file__), '--child',
                '--device', device, '--runs', str(runs)]
        try:
            child = subprocess.run(argv, env=env, text=True, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            output = exc.stdout or b''
            if isinstance(output, bytes):
                output = output.decode('utf-8', errors='replace')
            print('\n'.join(output.splitlines()[-25:]), flush=True)
            print(f'{device.upper()} TEST TIMED OUT after {timeout}s. Keep CPU mode.', flush=True)
            continue
        print('\n'.join(child.stdout.splitlines()[-45:]), flush=True)
        if child.returncode != 0:
            print(f'{device.upper()} TEST FAILED (process exit code {child.returncode}).', flush=True)
            if device == 'mps':
                print('Do not enable MPS in the live VoiceShield worker.', flush=True)
            continue
        for line in child.stdout.splitlines():
            if line.startswith('RESULT_JSON='):
                report = json.loads(line.split('=', 1)[1]); reports.append(report)
                print(f'{device.upper()} TEST PASSED: median model time {report["median_model_ms"]}ms', flush=True)
                break
    results = {d['device']: d for d in reports}
    if 'mps' in results and 'cpu' in results:
        cpu = results['cpu']['median_model_ms']; gpu = results['mps']['median_model_ms']
        print(f'\nMeasured relative speed: CPU/MPS = {cpu/max(gpu,1):.2f}x (higher means GPU faster)', flush=True)
        if gpu > cpu:
            print('MPS is slower for this model/configuration; keep CPU for now.', flush=True)
    elif 'mps' in results:
        print('\nMPS completed successfully. Compare CPU using --compare-cpu before choosing a live backend.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=int, default=2)
    parser.add_argument('--timeout', type=int, default=240,
                        help='max seconds allowed per isolated backend test')
    parser.add_argument('--compare-cpu', action='store_true')
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--device', choices=['cpu', 'mps'], default='mps', help=argparse.SUPPRESS)
    a = parser.parse_args()
    if not 1 <= a.runs <= 10:
        parser.error('--runs must be 1..10')
    if not 30 <= a.timeout <= 1200:
        parser.error('--timeout must be 30..1200 seconds')
    if a.child:
        child_run(a.device, a.runs)
    else:
        parent_run(['mps', 'cpu'] if a.compare_cpu else ['mps'], a.runs, a.timeout)


if __name__ == '__main__':
    main()
