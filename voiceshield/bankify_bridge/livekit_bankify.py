#!/usr/bin/env python3
"""Receive caller audio from LiveKit and run Bankify VoiceDetector on 3s windows.

No recording. Receiver media is never subscribed. Inference is off the audio loop;
latest-window queue has maximum length 2 so slow inference drops stale segments.
"""
import asyncio
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from collections import deque

import numpy as np
from livekit import rtc, api

HERE = Path(__file__).resolve().parent
BANKIFY = Path(os.environ.get('BANKIFY_DIR', HERE.parent.parent / 'bankify')).resolve()
if not (BANKIFY / 'detector.py').is_file():
    raise SystemExit(f'Missing Bankify repo at {BANKIFY}; clone it or set BANKIFY_DIR')
if not (BANKIFY / 'models' / 'detector.joblib').is_file():
    raise SystemExit('Missing trained Bankify models/detector.joblib. Train the model or provide the trained checkpoint; never use random predictions.')
sys.path.insert(0, str(BANKIFY))
from detector import VoiceDetector, SR  # noqa: E402

LK_URL = os.environ.get('LIVEKIT_URL', 'ws://127.0.0.1:7880')
LK_KEY = os.environ.get('LIVEKIT_API_KEY', 'devkey')
LK_SECRET = os.environ.get('LIVEKIT_API_SECRET', 'secret')
ROOM = os.environ.get('LIVEKIT_ROOM', 'fraud-test')
WORKER_TOKEN = os.environ.get('VOICESHIELD_WORKER_TOKEN', '')
EVENT_URL = os.environ.get('VOICESHIELD_EVENT_URL', 'http://127.0.0.1:3000/api/internal/detection')
WINDOW = 3 * SR
HOP = SR


def post_status(event):
    if not WORKER_TOKEN:
        raise RuntimeError('Set VOICESHIELD_WORKER_TOKEN to same value as website backend')
    body = json.dumps(event, separators=(',', ':')).encode()
    req = urllib.request.Request(EVENT_URL, data=body, method='POST', headers={
        'Content-Type': 'application/json', 'X-Worker-Token': WORKER_TOKEN})
    with urllib.request.urlopen(req, timeout=3) as response:
        if response.status != 200:
            raise RuntimeError('Status publish failed')


def notify(event):
    try:
        post_status(event)
    except Exception as e:
        print(f'[status send failed] {e}', flush=True)


class Segmenter:
    """Rolling 3s windows, 1s hop, bounded memory independent of call length."""
    def __init__(self):
        self.buffer = np.empty(0, dtype=np.float32)
        self.next_window = WINDOW

    def add(self, pcm):
        self.buffer = np.concatenate((self.buffer, pcm))
        result = []
        while len(self.buffer) >= self.next_window:
            end = self.next_window
            result.append(self.buffer[end-WINDOW:end].copy())
            self.next_window += HOP
        # Keep at most window+hop data; preserve next_window offset.
        if self.next_window > WINDOW + HOP:
            consumed = self.next_window - WINDOW
            self.buffer = self.buffer[consumed:]
            self.next_window -= consumed
        return result


async def main():
    if not WORKER_TOKEN:
        raise SystemExit('Set VOICESHIELD_WORKER_TOKEN (same secret used by server.py).')
    print('Loading Bankify detector… (first run may download Hugging Face weights)')
    detector = await asyncio.to_thread(VoiceDetector)
    print(f'Bankify loaded. Listening for caller in room {ROOM!r}.')
    notify({'status': 'monitoring', 'message': 'Detector ready; waiting for caller', 'windows': 0})

    queue = asyncio.Queue(maxsize=2)
    room = rtc.Room()
    active_tracks = set()
    analysis_task = None
    windows = 0
    ema = None
    streak = 0

    async def process_windows():
        nonlocal windows, ema, streak
        while True:
            pcm = await queue.get()
            try:
                rms = float(np.sqrt(np.mean(pcm * pcm)))
                if rms < 0.008:
                    # No confident speech segment; don't classify silence.
                    notify({'status': 'monitoring', 'message':'Waiting for caller speech', 'windows': windows})
                    ema, streak = None, 0
                    continue
                start = time.monotonic()
                fake_prob, _transcript = await asyncio.to_thread(detector.analyze, pcm)
                latency = (time.monotonic() - start) * 1000
                fake_prob = float(fake_prob)
                if not np.isfinite(fake_prob) or not (0 <= fake_prob <= 1):
                    raise ValueError('Invalid detector output')
                windows += 1
                ema = fake_prob if ema is None else 0.5 * fake_prob + 0.5 * ema
                verdict = 'FAKE' if ema > .7 else 'REAL' if ema < .3 else 'UNSURE'
                streak = streak + 1 if verdict == 'FAKE' else 0
                result = {'status':'result', 'verdict': verdict, 'p_fake': round(ema,4),
                          'latency_ms': round(latency,1), 'windows': windows,
                          'alert': streak >= 2 and verdict == 'FAKE',
                          'message': 'Experimental synthetic voice risk score'}
                notify(result)
                print(f"[{windows:04d}] {verdict:<6} synthetic={ema:.1%} inference={latency:.0f}ms dropped backlog={queue.qsize()}", flush=True)
            except Exception as exc:
                notify({'status':'error','message':str(exc)[:140], 'windows':windows})
                print('Inference error:', repr(exc), flush=True)
            finally:
                queue.task_done()

    async def consume_track(track, participant_id):
        segmenter = Segmenter()
        try:
            # AudioStream handles resampling from WebRTC track to 16k mono PCM16.
            stream = rtc.AudioStream(track, sample_rate=SR, num_channels=1)
            print('Caller audio subscription active', flush=True)
            notify({'status':'monitoring','message':'Receiving caller audio', 'windows':windows})
            async for event in stream:
                frame = event.frame
                data = np.frombuffer(frame.data, dtype=np.int16).astype(np.float32) / 32768.0
                for window in segmenter.add(data):
                    if queue.full():
                        try:
                            queue.get_nowait()  # drop oldest outdated detection window
                            queue.task_done()
                        except asyncio.QueueEmpty:
                            pass
                    queue.put_nowait(window)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print('Audio stream error:', repr(exc), flush=True)
        finally:
            active_tracks.discard(track)
            notify({'status':'monitoring','message':'Caller audio ended; waiting', 'windows':windows})

    def subscribe_caller(pub, participant):
        if participant.identity == 'caller' and pub.kind == rtc.TrackKind.KIND_AUDIO:
            pub.set_subscribed(True)

    @room.on('track_published')
    def on_track_published(pub, participant):
        subscribe_caller(pub, participant)

    @room.on('track_subscribed')
    def on_track_subscribed(track, pub, participant):
        if participant.identity != 'caller' or track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        if track in active_tracks:
            return
        active_tracks.add(track)
        asyncio.create_task(consume_track(track, participant.identity))

    token = (api.AccessToken(LK_KEY, LK_SECRET)
             .with_identity('bankify-detector')
             .with_name('Bankify AI Detector')
             .with_grants(api.VideoGrants(room_join=True, room=ROOM,
                                          can_publish=False, can_subscribe=True,
                                          can_publish_data=False)).to_jwt())
    analysis_task = asyncio.create_task(process_windows())
    try:
        await room.connect(LK_URL, token, options=rtc.RoomOptions(auto_subscribe=False))
        print('Joined LiveKit as read-only bankify-detector', flush=True)
        for participant in room.remote_participants.values():
            if participant.identity == 'caller':
                for publication in participant.track_publications.values():
                    subscribe_caller(publication, participant)
        await asyncio.Event().wait()
    finally:
        await room.disconnect()
        if analysis_task:
            analysis_task.cancel()
            try:
                await analysis_task
            except asyncio.CancelledError:
                pass
        notify({'status':'offline','message':'Detector stopped', 'windows':windows})


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('Stopped.')
