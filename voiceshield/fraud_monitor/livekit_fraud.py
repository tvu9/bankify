#!/usr/bin/env python3
"""Optional read-only LiveKit caller speech analyzer.

Does not alter VoiceShield V3.2 PellaV2; never saves audio or transcripts.
Debug mode prints transcript snippets ONLY with explicit VOICE_ASR_DEBUG_TEXT=1.
"""
import asyncio
import json
import math
import os
import re
import time
import urllib.request

import numpy as np
from livekit import api, rtc
from risk_engine import CallRisk
from semantic_risk import SemanticCallRisk
from asr_backend import VoiceTranscriber

SR = 16000
URL = os.getenv('LIVEKIT_URL', 'ws://127.0.0.1:7880')
KEY = os.getenv('LIVEKIT_API_KEY', 'devkey')
SECRET = os.getenv('LIVEKIT_API_SECRET', 'secret')
ROOM = os.getenv('LIVEKIT_ROOM', 'fraud-test')
CALLER = os.getenv('VOICE_CALLER_ID', 'caller')
TOKEN = os.getenv('VOICESHIELD_WORKER_TOKEN', '')
ENDPOINT = os.getenv('VOICE_FRAUD_EVENT_URL', 'http://127.0.0.1:3000/api/internal/fraud')
DEBUG_TEXT = os.getenv('VOICE_ASR_DEBUG_TEXT', '0') == '1'
DEBUG_REASON = os.getenv('VOICE_FRAUD_DEBUG_REASON', '1') == '1'
from transcript_delta import TranscriptDelta
from risk_logging import format_risk_log


def send(event):
    body = json.dumps(event, separators=(',', ':')).encode()
    req = urllib.request.Request(ENDPOINT, method='POST', data=body,
        headers={'Content-Type': 'application/json', 'X-Worker-Token': TOKEN})
    with urllib.request.urlopen(req, timeout=3) as resp:
        if resp.status != 200:
            raise RuntimeError(f'Fraud API returned {resp.status}')


def rms_dbfs(audio):
    if not len(audio):
        return -90.0
    return max(-90.0, 20 * math.log10(max(1e-9, float(np.sqrt(np.mean(audio ** 2))))))


async def main():
    if not TOKEN:
        raise SystemExit('VOICESHIELD_WORKER_TOKEN required')
    model = await asyncio.to_thread(VoiceTranscriber)
    # Semantic mode is opt-in; no silent fallback to hardcoded phrases.
    mode = os.getenv('VOICE_FRAUD_MODE', 'semantic').lower()
    if mode not in ('semantic', 'rules'):
        raise SystemExit('VOICE_FRAUD_MODE must be semantic or rules')
    risk = SemanticCallRisk() if mode == 'semantic' else CallRisk()
    deduper = TranscriptDelta()
    room = rtc.Room()
    generation = 0
    jobs = set()
    pending = asyncio.Queue(maxsize=1)
    events = asyncio.Queue(maxsize=8)

    def emit(data):
        if events.full():
            try:
                events.get_nowait()
                events.task_done()
            except asyncio.QueueEmpty:
                pass
        events.put_nowait(data)

    async def publish_loop():
        while True:
            item = await events.get()
            try:
                await asyncio.to_thread(send, item)
            except Exception as e:
                print('[ASR] Status publish failed:', repr(e)[:160], flush=True)
            finally:
                events.task_done()

    async def inference_loop():
        while True:
            gen, pcm, level = await pending.get()
            try:
                if gen != generation:
                    continue
                transcript, latency_ms = await asyncio.to_thread(model.transcribe, pcm)
                if gen != generation:
                    continue
                # Whisper decodes overlapping 8-second windows. Process only words
                # that were not already included in the previous window.
                novel = deduper.consume(transcript)
                if not novel:
                    continue  # No new spoken words: no terminal line or scam event.
                if DEBUG_TEXT:
                    print(f'[ASR TEXT] [{novel[:400]}]', flush=True)
                # Analyze only the new words plus a small preceding context for
                # requests split across ASR window boundaries.
                context_text = deduper.context_text(novel)
                # The semantic model receives true NEW speech separately from prior
                # text, avoiding a stale high-risk phrase being called 'current'.
                result = await asyncio.to_thread(risk.add, novel if mode == 'semantic' else context_text)
                if gen != generation:
                    continue
                result.update(status='active', asr_status='active',
                              transcript_available=True, asr_latency_ms=round(latency_ms),
                              audio_level_dbfs=round(level, 1),
                              reason=result['reason'])
                emit(result)
                print(f'[ASR] new_words={len(novel.split())} '
                      f'signal={level:.1f}dBFS elapsed={latency_ms:.0f}ms', flush=True)
                # Exactly one risk line per NEW transcript; never treat retained
                # call-history HIGH as a HIGH label for harmless current speech.
                print(format_risk_log(result), flush=True)
                if mode == 'semantic' and DEBUG_REASON:
                    print(f"[SCAM EXPLAIN] [{result.get('reason', '')[:180]}]", flush=True)
                if result.get('analysis_status') == 'unavailable':
                    print(f"[SCAM ERROR] [{result.get('model_error') or 'Unknown model error'}]", flush=True)
            except Exception as e:
                print('[ASR] Inference error:', repr(e)[:180], flush=True)
                emit({'status':'error', 'asr_status':'error', 'reason':'Transcription failed; no fraud conclusion'})
            finally:
                pending.task_done()

    def clear_pending():
        while not pending.empty():
            try:
                pending.get_nowait()
                pending.task_done()
            except asyncio.QueueEmpty:
                break

    async def consume(track, gen):
        stream = rtc.AudioStream(track, capacity=8, sample_rate=SR, num_channels=1)
        buf = np.zeros(0, dtype=np.float32)
        total = 0
        next_at = 5 * SR
        print('[ASR] Caller audio subscribed; accumulating first 5 seconds', flush=True)
        try:
            async for event in stream:
                if gen != generation:
                    break
                frame = np.frombuffer(event.frame.data, dtype=np.int16).astype(np.float32) / 32768.0
                if not frame.size:
                    continue
                buf = np.concatenate((buf, frame))[-8*SR:]
                total += len(frame)
                if total >= next_at:
                    next_at += 4*SR
                    level = rms_dbfs(buf)
                    if len(buf) < 3*SR:
                        continue
                    if level < -55:
                        deduper.mark_silence()
                        emit({'status':'listening', 'asr_status':'listening',
                              'audio_level_dbfs':round(level, 1),
                              'transcript_available':False,
                              'reason':'Caller audio is too quiet; check source/microphone.'})
                        continue
                    if pending.full():
                        clear_pending()
                    pending.put_nowait((gen, buf.copy(), level))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print('[ASR] Audio stream error:', repr(e)[:180], flush=True)
            emit({'status':'error','asr_status':'error','reason':'Caller audio stream interrupted'})
        finally:
            await stream.aclose()

    def subscribe(pub, participant):
        if participant.identity == CALLER and pub.kind == rtc.TrackKind.KIND_AUDIO:
            pub.set_subscribed(True)

    def begin(track):
        nonlocal generation
        generation += 1
        clear_pending()
        risk.reset()
        deduper.reset()
        gen = generation
        emit({'reset':True,'status':'listening','asr_status':'listening'})
        job = asyncio.create_task(consume(track,gen))
        jobs.add(job)
        job.add_done_callback(jobs.discard)

    @room.on('track_published')
    def on_publish(pub, participant):
        subscribe(pub,participant)

    @room.on('track_subscribed')
    def on_subscribed(track,pub,participant):
        if participant.identity == CALLER and track.kind == rtc.TrackKind.KIND_AUDIO:
            begin(track)

    @room.on('track_unsubscribed')
    def on_unsubscribed(track,pub,participant):
        if participant.identity == CALLER:
            disconnect_caller()

    def disconnect_caller():
        nonlocal generation
        generation += 1
        clear_pending()
        risk.reset()
        deduper.reset()
        for job in tuple(jobs):
            job.cancel()
        emit({'reset':True,'status':'waiting','asr_status':'waiting'})

    @room.on('participant_disconnected')
    def on_disconnected(participant):
        if participant.identity == CALLER:
            disconnect_caller()

    jwt = (api.AccessToken(KEY, SECRET).with_identity('voiceshield-fraud-monitor')
           .with_name('VoiceShield Speech Monitor')
           .with_grants(api.VideoGrants(room_join=True, room=ROOM, can_publish=False,
                                       can_subscribe=True, can_publish_data=False)).to_jwt())
    publisher = asyncio.create_task(publish_loop())
    analyzer = asyncio.create_task(inference_loop())
    try:
        await room.connect(URL, jwt, options=rtc.RoomOptions(auto_subscribe=False))
        print('[ASR] Joined LiveKit room; waiting for caller audio', flush=True)
        for participant in room.remote_participants.values():
            if participant.identity == CALLER:
                for pub in participant.track_publications.values():
                    subscribe(pub, participant)
        await asyncio.Future()
    finally:
        await room.disconnect()
        for job in tuple(jobs):
            job.cancel()
        publisher.cancel()
        analyzer.cancel()
        await asyncio.gather(publisher, analyzer, *jobs, return_exceptions=True)

if __name__ == '__main__':
    asyncio.run(main())
