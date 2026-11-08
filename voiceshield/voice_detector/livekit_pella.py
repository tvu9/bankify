#!/usr/bin/env python3
"""Read-only LiveKit PellaV2 detector with latency/age telemetry.

The CPU worker uses a newest-only inference queue. It never stores recordings,
never subscribes to receiver audio, and never publishes stale results as alerts.
"""
import asyncio
import json
import os
import time
import urllib.request

import numpy as np
from livekit import api, rtc

try:
    from .pella_backend import PellaV2
    from .stream_utils import AudioRing, RiskSmoother, has_usable_speech, SAMPLE_RATE
    from .audio_quality_v32 import AudioQuality
except ImportError:
    from pella_backend import PellaV2
    from stream_utils import AudioRing, RiskSmoother, has_usable_speech, SAMPLE_RATE
    from audio_quality_v32 import AudioQuality

LIVEKIT_URL = os.environ.get('LIVEKIT_URL', 'ws://127.0.0.1:7880')
LIVEKIT_KEY = os.environ.get('LIVEKIT_API_KEY', 'devkey')
LIVEKIT_SECRET = os.environ.get('LIVEKIT_API_SECRET', 'secret')
ROOM_NAME = os.environ.get('LIVEKIT_ROOM', 'fraud-test')
CALLER_ID = os.environ.get('VOICE_CALLER_ID', 'caller')
WORKER_TOKEN = os.environ.get('VOICESHIELD_WORKER_TOKEN', '')
EVENT_URL = os.environ.get('VOICESHIELD_EVENT_URL', 'http://127.0.0.1:3000/api/internal/detection')


def send_event(event):
    body = json.dumps(event, separators=(',', ':')).encode('utf-8')
    request = urllib.request.Request(EVENT_URL, data=body, method='POST', headers={
        'Content-Type': 'application/json', 'X-Worker-Token': WORKER_TOKEN})
    with urllib.request.urlopen(request, timeout=3) as response:
        if response.status != 200:
            raise RuntimeError(f'Event endpoint returned {response.status}')


async def main():
    if not WORKER_TOKEN:
        raise SystemExit('VOICESHIELD_WORKER_TOKEN missing. Use same secret as server.py.')
    print('Loading PellaV2. First run downloads large weights; no audio stored.', flush=True)
    model = await asyncio.to_thread(PellaV2)
    # First CPU inference can be several seconds slower than subsequent ones.
    # Complete it BEFORE joining the call, so the first caller window has hot
    # kernels/model paths. The synthetic input is never stored or scored as speech.
    if os.environ.get('VOICE_PREWARM', '1') != '0':
        print('Prewarming PellaV2 before joining LiveKit…', flush=True)
        t0 = time.perf_counter()
        warm_x = (0.025 * np.sin(2 * np.pi * 210 *
                  np.arange(4 * SAMPLE_RATE, dtype=np.float32) / SAMPLE_RATE)).astype(np.float32)
        _, warm_timing = await asyncio.to_thread(model.analyze_timed, warm_x)
        print(f'Prewarm complete in {time.perf_counter()-t0:.2f}s '
              f'(forward {warm_timing["model_ms"]:.0f}ms); ready for live calls.', flush=True)

    room = rtc.Room()
    # The most recent completed window wins while inference is busy.
    # Newest-only bounded queue: inference never blocks the audio producer.
    from continuous_queue import NewestWindowQueue
    queue = NewestWindowQueue()
    stream_tasks = {}
    current_generation = 0
    window_count = 0
    # Legacy decisions reproduce the earlier VoiceShield behavior. V3.1 is an
    # optional, conservative evidence-hold policy; neither changes raw scores.
    decision_mode = os.environ.get('VOICE_DECISION_MODE', 'v31').lower()
    if decision_mode == 'legacy':
        smoother = RiskSmoother()
    elif decision_mode == 'v31':
        try:
            from .decision_v31 import EvidenceDecision
        except ImportError:
            from decision_v31 import EvidenceDecision
        smoother = EvidenceDecision()
    else:
        raise ValueError('VOICE_DECISION_MODE must be v31 or legacy')
    print(f'Decision policy: {decision_mode} (experimental, not calibrated)', flush=True)
    event_failures = 0
    audio_debug = os.environ.get('VOICE_DEBUG_AUDIO', '0') == '1'
    status_queue = asyncio.Queue(maxsize=4)
    hop_seconds = float(os.environ.get('VOICE_HOP_SECONDS', '1'))
    stale_after_ms = 1_000 * float(os.environ.get('VOICE_STALE_AFTER_S', '10'))
    if not 0.5 <= hop_seconds <= 4:
        raise ValueError('VOICE_HOP_SECONDS must be between 0.5 and 4')
    if not 1_000 <= stale_after_ms <= 120_000:
        raise ValueError('VOICE_STALE_AFTER_S must be between 1 and 120')
    inference_running = False
    print(f'Live stream: continuous capture; 4s Pella windows / {hop_seconds:g}s hop; '
          f'newest-only inference; stale after {stale_after_ms/1000:g}s.', flush=True)

    async def publish(event):
        nonlocal event_failures
        try:
            await asyncio.to_thread(send_event, event)
            event_failures = 0
        except Exception as exc:
            event_failures += 1
            if event_failures <= 2 or event_failures % 10 == 0:
                print(f'[status endpoint error] {exc} (check matching worker secret)', flush=True)

    def publish_later(event):
        # A single sender preserves event order and prevents network-induced
        # unbounded growth when the website status endpoint is unavailable.
        if status_queue.full():
            try:
                status_queue.get_nowait()
                status_queue.task_done()
            except asyncio.QueueEmpty:
                pass
        status_queue.put_nowait(event)

    async def status_loop():
        while True:
            event = await status_queue.get()
            try:
                await publish(event)
            finally:
                status_queue.task_done()

    def clear_pending():
        queue.clear()

    def reset_evidence():
        # Both decision policies expose a score history; reset also clears
        # V3.1 warning holds between speakers/calls or silence.
        if hasattr(smoother, 'reset'):
            smoother.reset()
        else:
            smoother.scores.clear()

    async def infer_loop():
        nonlocal window_count, inference_running
        while True:
            generation, pcm, window_finished_at = await queue.get()
            try:
                if generation != current_generation:
                    continue
                if not has_usable_speech(pcm):
                    reset_evidence()
                    publish_later({'status':'monitoring', 'windows':window_count,
                                   'message':'Waiting for sufficiently clear caller audio'})
                    continue
                if window_count == 0:
                    print('[AI] First 4-second window ready; analyzing while audio capture continues.', flush=True)
                inference_running = True
                queue_wait_ms = (time.monotonic() - window_finished_at) * 1000
                publish_later({'status':'analyzing', 'windows':window_count,
                               'message':'Analyzing caller audio on CPU…'})
                score, timing = await asyncio.to_thread(model.analyze_timed, pcm)
                if generation != current_generation:
                    continue
                sample_age_ms = (time.monotonic() - window_finished_at) * 1000
                stale = sample_age_ms > stale_after_ms
                if stale:
                    # Do not feed delayed evidence into current-call decisions.
                    reset_evidence()
                    verdict, smoothed = 'UNSURE', score
                else:
                    verdict, smoothed = smoother.add(score)
                window_count += 1
                event = {
                    'status':'result', 'windows':window_count,
                    'p_fake':round(score, 5),
                    'verdict':verdict,
                    'latency_ms':round(timing['inference_ms'], 1),
                    'preprocess_ms':round(timing['preprocess_ms'], 1),
                    'model_ms':round(timing['model_ms'], 1),
                    'queue_wait_ms':round(queue_wait_ms, 1),
                    'sample_age_ms':round(sample_age_ms, 1),
                    'stale':stale,
                    'dropped':queue.dropped,
                    'alert':not stale and verdict == 'FAKE',
                    'message': ('Delayed audio: not used for active risk assessment' if stale
                                else 'PellaV2 screening signal; no identity verification'),
                }
                publish_later(event)
                print(f'[{window_count:04d}] {"STALE" if stale else verdict:6} '
                      f'raw={score:.3f} mean={smoothed:.3f} '
                      f'infer={timing["inference_ms"]:.0f}ms '
                      f'(prep={timing["preprocess_ms"]:.0f}ms '
                      f'model={timing["model_ms"]:.0f}ms) '
                      f'queue_wait={queue_wait_ms:.0f}ms '
                      f'age={sample_age_ms:.0f}ms '
                      f'pending={queue.qsize()} dropped={queue.dropped}', flush=True)
            except Exception as exc:
                print(f'Inference error: {exc!r}', flush=True)
                publish_later({'status':'error', 'message':str(exc)[:140],
                               'windows':window_count})
            finally:
                inference_running = False
                queue.task_done()

    async def heartbeat_loop():
        # While the CPU is busy, keep the UI marked as "analyzing" rather than
        # falsely showing "offline" due to server.py's stale status timeout.
        while True:
            await asyncio.sleep(3)
            if inference_running:
                publish_later({'status':'analyzing', 'windows':window_count,
                               'message':'Analyzing caller audio on CPU…'})

    async def consume(track, generation):
        segmenter = AudioRing(hop=int(hop_seconds * SAMPLE_RATE))
        quality_meter = AudioQuality(sample_rate=SAMPLE_RATE, publish_every=0.5)
        first_frame = True
        activity_seen = False
        next_debug = time.monotonic() + 10
        stream = None
        try:
            stream = rtc.AudioStream(track, capacity=8, sample_rate=SAMPLE_RATE, num_channels=1)
            print('Caller-only PCM stream active', flush=True)
            publish_later({'status':'monitoring','message':'Receiving caller speech',
                           'windows':window_count})
            async for event in stream:
                if generation != current_generation:
                    break
                x = np.frombuffer(event.frame.data, dtype=np.int16).astype(np.float32) / 32768.0
                # This producer never awaits model inference; the LiveKit audio
                # stream keeps receiving frames while the CPU analyzes earlier
                # four-second windows on a separate thread.
                if first_frame:
                    first_frame = False
                    print('[AUDIO] Live caller audio connected; capture is continuous.', flush=True)
                    publish_later({'status':'monitoring',
                                   'message':'Listening to caller · AI analyzes in parallel',
                                   'windows':window_count})
                if not activity_seen and x.size and float(np.sqrt(np.mean(x*x))) >= 0.004:
                    activity_seen = True
                    publish_later({'status':'monitoring',
                                   'message':'Caller audio activity detected · analyzing when ready',
                                   'windows':window_count})
                metrics = quality_meter.add(x)
                if metrics is not None:
                    publish_later({'status': 'quality', 'windows': window_count,
                                   'message': 'Audio monitoring active', **metrics})
                for window in segmenter.add(x):
                    # Keep only the newest pending window. Never sacrifice audio
                    # capture or build up a backlog if inference slows down.
                    queue.submit((generation, window, time.monotonic()))
                if audio_debug and time.monotonic() >= next_debug:
                    print(f'[AUDIO-DEBUG] captured={segmenter.total / SAMPLE_RATE:.1f}s '
                          f'AI_running={inference_running} pending={queue.qsize()} '
                          f'dropped={queue.dropped}', flush=True)
                    next_debug = time.monotonic() + 10
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f'Caller stream error: {exc!r}', flush=True)
        finally:
            if stream is not None:
                try:
                    await stream.aclose()
                except Exception:
                    pass
            print('Caller stream ended', flush=True)
            if generation == current_generation:
                publish_later({'status':'monitoring','windows':window_count,
                               'message':'Waiting for caller to reconnect'})

    def begin_stream(track):
        nonlocal current_generation
        if track in stream_tasks:
            return
        current_generation += 1
        reset_evidence()
        clear_pending()
        publish_later({'status': 'monitoring', 'reset': True, 'windows': 0,
                       'message': 'Caller connected · monitoring audio now'})
        generation = current_generation
        task = asyncio.create_task(consume(track, generation))
        stream_tasks[track] = task
        def remove(done):
            stream_tasks.pop(track, None)
        task.add_done_callback(remove)

    def subscribe(pub, participant):
        if participant.identity == CALLER_ID and pub.kind == rtc.TrackKind.KIND_AUDIO:
            pub.set_subscribed(True)

    @room.on('track_published')
    def on_published(pub, participant):
        subscribe(pub, participant)

    @room.on('track_subscribed')
    def on_subscribed(track, pub, participant):
        if participant.identity == CALLER_ID and track.kind == rtc.TrackKind.KIND_AUDIO:
            begin_stream(track)

    @room.on('participant_connected')
    def on_participant_connected(participant):
        if participant.identity == CALLER_ID:
            publish_later({'status': 'monitoring', 'reset': True, 'windows': 0,
                           'message': 'Caller joined · waiting for microphone audio'})

    @room.on('participant_disconnected')
    def on_participant_disconnected(participant):
        nonlocal current_generation
        if participant.identity == CALLER_ID:
            current_generation += 1
            clear_pending()
            reset_evidence()
            for task in tuple(stream_tasks.values()):
                task.cancel()
            publish_later({'status':'monitoring','reset': True,
                           'message':'Caller disconnected; waiting for a new call', 'windows':0})

    @room.on('track_unsubscribed')
    def on_unsubscribed(track, pub, participant):
        nonlocal current_generation
        task = stream_tasks.get(track)
        if task:
            current_generation += 1
            clear_pending()
            reset_evidence()
            task.cancel()
            publish_later({'status':'monitoring', 'reset': True, 'windows':0,
                           'message':'Caller microphone stopped; waiting for audio'})

    token = (api.AccessToken(LIVEKIT_KEY, LIVEKIT_SECRET)
             .with_identity('voiceshield-ai-detector')
             .with_name('VoiceShield PellaV2 monitoring')
             .with_grants(api.VideoGrants(
                 room_join=True, room=ROOM_NAME,
                 can_publish=False, can_subscribe=True, can_publish_data=False))
             .to_jwt())

    worker = asyncio.create_task(infer_loop())
    status_worker = asyncio.create_task(status_loop())
    heartbeat_worker = asyncio.create_task(heartbeat_loop())
    try:
        await room.connect(LIVEKIT_URL, token, options=rtc.RoomOptions(auto_subscribe=False))
        print(f'Connected to {ROOM_NAME!r} as silent read-only detector', flush=True)
        publish_later({'status':'monitoring', 'windows':0, 'message':'AI worker ready; waiting for caller'})
        for participant in room.remote_participants.values():
            if participant.identity == CALLER_ID:
                for pub in participant.track_publications.values():
                    subscribe(pub, participant)
        await asyncio.Event().wait()
    finally:
        for task in tuple(stream_tasks.values()):
            task.cancel()
        if stream_tasks:
            await asyncio.gather(*tuple(stream_tasks.values()), return_exceptions=True)
        await room.disconnect()
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        heartbeat_worker.cancel()
        await asyncio.gather(heartbeat_worker, return_exceptions=True)
        status_worker.cancel()
        await asyncio.gather(status_worker, return_exceptions=True)
        await publish({'status':'offline', 'message':'Detector stopped', 'windows':window_count})


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('PellaV2 worker stopped.', flush=True)
