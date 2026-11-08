"""Whisper ASR for telephone audio. CPU-only, bounded inference, no files written."""
import os
import time
import numpy as np


class VoiceTranscriber:
    def __init__(self):
        from faster_whisper import WhisperModel
        name = os.environ.get('VOICE_ASR_MODEL', 'tiny.en')
        if name not in ('tiny.en', 'base.en', 'small.en'):
            raise ValueError('VOICE_ASR_MODEL must be tiny.en, base.en or small.en')
        self.name = name
        self.model = WhisperModel(name, device='cpu', compute_type='int8',
                                  cpu_threads=max(1, min(4, int(os.environ.get('VOICE_ASR_THREADS', '1')))),
                                  num_workers=1)
        print(f'VoiceShield ASR ready: {name} CPU int8; short-clip VAD filter disabled', flush=True)

    def transcribe(self, audio):
        audio = np.ascontiguousarray(audio, dtype=np.float32)
        if audio.ndim != 1 or not len(audio) or not np.all(np.isfinite(audio)):
            raise ValueError('ASR expects finite mono float32 PCM')
        t0 = time.monotonic()
        # Whisper's VAD filtering can reject short/quiet telephone clips.
        # Keep an external energy gate and disable its *additional* VAD pass.
        segments, _ = self.model.transcribe(audio, beam_size=1, best_of=1,
                                            vad_filter=False,
                                            condition_on_previous_text=False,
                                            language='en')
        words = ' '.join(seg.text.strip() for seg in segments).strip()
        return words, (time.monotonic() - t0) * 1000
