#!/usr/bin/env python3
"""Stress the newest-only 4-second streaming inference queue, outside LiveKit.

Mode pella benchmarks real model; mode mock validates architecture only.
No actual phone/media/network latency is measured: use live worker telemetry too.
"""
import argparse
import asyncio
import json
import os
import statistics
import time
import resource
import sys
import numpy as np
try:
    from .continuous_queue import NewestWindowQueue
    from .v3_common import SR, WINDOW
except ImportError:
    from continuous_queue import NewestWindowQueue
    from v3_common import SR, WINDOW


def percentile(values,p):
    return round(float(np.percentile(values,p)),2) if values else None


async def run_benchmark(args):
    # CPU configuration must happen before model weights are instantiated.
    os.environ['VOICE_DETECT_DEVICE']='cpu'
    t=np.arange(WINDOW,dtype=np.float32)/SR
    wave=(.03*np.sin(2*np.pi*240*t)+.005*np.sin(2*np.pi*430*t)).astype(np.float32)
    if args.mode=='pella':
        try: from .pella_backend import PellaV2
        except ImportError: from pella_backend import PellaV2
        model=await asyncio.to_thread(PellaV2)
        if args.threads:
            model.torch.set_num_threads(args.threads)
        print('Prewarming model before streaming benchmark...',flush=True)
        await asyncio.to_thread(model.analyze_timed,wave)
        def evaluate(x):
            _,timing=model.analyze_timed(x)
            return timing['inference_ms']/1000
    else:
        def evaluate(x):
            time.sleep(args.mock_delay)
            return args.mock_delay
    q=NewestWindowQueue()
    timeline=[]; times=[]; ages=[]; seen=[]
    start=time.monotonic()
    total_samples=0
    stop=object()

    async def producer():
        nonlocal total_samples
        # The first full 4s window becomes eligible when 4s have arrived.
        # The call audio is conceptual here; benchmark measures inference scheduling.
        sample_count=0
        duration=args.duration
        next_submit=4.
        tick=0.05
        n=int(np.ceil(duration/tick))
        for index in range(n):
            target=(index+1)*tick
            await asyncio.sleep(max(0,start+target/args.speed-time.monotonic()))
            sample_count=int(min(duration,target)*SR)
            total_samples=sample_count
            if target + 1e-8 >= next_submit:
                window=(wave.copy(),time.monotonic(),target)
                q.submit(window)
                next_submit+=args.hop
        # Let the consumer finish in-progress work and the newest pending window.
        await q._queue.join()  # all queued windows handled, including newest
        q.submit(stop)

    async def consumer():
        while True:
            item=await q.get()
            try:
                if item is stop: break
                pcm,arrival,audio_time=item
                waited=time.monotonic()-arrival
                infer_start=time.monotonic()
                reported=await asyncio.to_thread(evaluate,pcm)
                inference=time.monotonic()-infer_start
                age=time.monotonic()-arrival
                times.append(inference*1000)
                ages.append(age*1000)
                seen.append(audio_time)
                timeline.append({'audio_time_s':round(audio_time,3),'queue_wait_ms':round(waited*1000,2),
                                 'inference_ms':round(inference*1000,2),'sample_age_ms':round(age*1000,2),
                                 'reported_model_ms':round(reported*1000,2),
                                 'completed_at_s':round(time.monotonic()-start,3)})
            finally: q.task_done()
    task=asyncio.create_task(consumer())
    await producer()
    await task
    result={'mode':args.mode,'realtime':args.speed==1,'speed_factor':args.speed,
            'duration_s':args.duration,'hop_s':args.hop,'threads':args.threads,'audio_samples_received':total_samples,
            'analyzed_windows':len(times),'dropped_pending_windows':q.dropped,
            'inference_ms_p50':percentile(times,50),'inference_ms_p95':percentile(times,95),
            'age_ms_p50':percentile(ages,50),'age_ms_p95':percentile(ages,95),
            'rss_peak_mb':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/(1024*1024 if sys.platform=='darwin' else 1024),1),
            'first_result_at_s':timeline[0]['completed_at_s'] if timeline else None,
            'notes':['Synthetic audio tests throughput, not detection accuracy.',
                     'First result measured from synthetic call start, not LiveKit network.',
                     'Use speed_factor=1 for real-time scheduling comparisons.']}
    return result,timeline


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mode',choices=['mock','pella'],default='pella')
    ap.add_argument('--duration',type=float,default=30.)
    ap.add_argument('--hop',type=float,default=1.)
    ap.add_argument('--speed',type=float,default=1.,help='Use 1 for realistic elapsed-time test; >1 accelerates simulation only')
    ap.add_argument('--mock-delay',type=float,default=.05)
    ap.add_argument('--threads',type=int,default=4)
    ap.add_argument('--out',help='Optional JSON report; not overwritten')
    args=ap.parse_args()
    if args.duration<4 or args.duration>600 or args.hop<.5 or args.hop>4 or args.speed<=0 or args.speed>100 or args.mock_delay<0 or not 1<=args.threads<=32:
        ap.error('Invalid timing/settings')
    if args.out and os.path.exists(args.out): ap.error('Output exists; will not overwrite')
    result,timeline=asyncio.run(run_benchmark(args))
    print(json.dumps(result,indent=2))
    if args.out:
        from pathlib import Path
        p=Path(args.out); p.parent.mkdir(parents=True,exist_ok=True)
        p.write_text(json.dumps({'summary':result,'windows':timeline},indent=2)+'\n')
        print(f'Saved {p}')

if __name__=='__main__':main()
