"""PellaV2 inference adapter for LiveKit 16 kHz mono PCM.

Architecture and preprocessing adapted from the MIT-licensed reference:
https://huggingface.co/Sadanie/pellav2-audio-deepfake-detector/blob/main/pellav2_infer.py
Model weights are downloaded separately, not redistributed in this package.
No assumptions that the raw sigmoid is calibrated for phone/WebRTC audio.
"""
import os
import time
from pathlib import Path

import numpy as np

SR = 16_000
CROP = 4 * SR
HUB_REPO = 'Sadanie/pellav2-audio-deepfake-detector'


def preprocess(x):
    """Match published PellaV2 input normalization on a four-second PCM window."""
    import pyloudnorm as pyln
    from scipy.signal import butter, sosfiltfilt

    x = np.asarray(x, dtype=np.float32).ravel()
    if not len(x) or not np.all(np.isfinite(x)):
        raise ValueError('Empty or invalid audio')
    x = x - x.mean()
    if len(x) > 3 * SR // 100:
        x = sosfiltfilt(butter(2, 20.0, btype='highpass', fs=SR, output='sos'), x)
    x = x.astype(np.float32)
    if len(x) > CROP:
        offset = (len(x) - CROP) // 2
        x = x[offset:offset + CROP]
    try:
        loud = pyln.Meter(SR).integrated_loudness(x.astype(np.float64))
        if not np.isfinite(loud):
            raise ValueError('non-finite loudness')
    except Exception:
        loud = float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9) - 0.691)
    gain = float(np.clip(-23.0 - loud, -40.0, 40.0))
    x = np.clip(x * (10 ** (gain / 20)), -1, 1).astype(np.float32)
    if len(x) < CROP:
        x = np.pad(x, (0, CROP - len(x)))
    return np.ascontiguousarray(x)


class PellaV2:
    def __init__(self, device=None):
        import torch
        import torch.nn as nn
        from transformers import Wav2Vec2BertConfig, Wav2Vec2BertModel
        from huggingface_hub import hf_hub_download

        # Set CPU intra-op parallelism before model initialization/inference.
        # Benchmark values of 2/4/6 on your own Mac rather than assuming more is faster.
        cpu_threads = int(os.environ.get('VOICE_CPU_THREADS', '4'))
        if cpu_threads < 1 or cpu_threads > 64:
            raise ValueError('VOICE_CPU_THREADS must be between 1 and 64')
        torch.set_num_threads(cpu_threads)
        print(f'PyTorch CPU intra-op threads: {torch.get_num_threads()}', flush=True)

        # The official reference uses Wav2Vec2BertModel (not XLS-R) under the hood.
        # Initialize from its config (not duplicate pretrained backbone weights),
        # then strictly load every parameter from the PellaV2 full checkpoint.
        config = Wav2Vec2BertConfig.from_pretrained('facebook/w2v-bert-2.0')

        class Detector(nn.Module):
            def __init__(self):
                super().__init__()
                self.backbone = Wav2Vec2BertModel(config)
                self.layer_weights = nn.Parameter(torch.zeros(config.num_hidden_layers + 1))
                self.head = nn.Linear(config.hidden_size, 1)

            def forward(self, x):
                import torchaudio.compliance.kaldi as K
                # Kaldi fbank on CPU for compatibility with Mac MPS.
                # The original script may place this operation on MPS, where
                # torchaudio kernels aren't guaranteed to be supported.
                x_cpu = x.detach().float().cpu()
                feats, lens = [], []
                for sample in x_cpu:
                    nz = torch.nonzero(sample).flatten()
                    n_s = int(nz[-1]) + 1 if len(nz) else len(sample)
                    f = K.fbank(sample[None, :max(n_s, 400)] * 32768.0,
                                num_mel_bins=80, sample_frequency=SR,
                                dither=0.0, window_type='povey')
                    f = (f - f.mean(0, keepdim=True)) / torch.sqrt(f.var(0, keepdim=True) + 1e-7)
                    n = f.shape[0] // 2 * 2
                    feats.append(f[:n].reshape(n // 2, 160))
                    lens.append(n // 2)
                size = max(lens)
                target = next(self.parameters()).device
                data = torch.zeros(len(feats), size, 160, device=target)
                mask = torch.zeros(len(feats), size, dtype=torch.long, device=target)
                for i, (f, n) in enumerate(zip(feats, lens)):
                    data[i, :n] = f.to(target)
                    mask[i, :n] = 1
                hs = self.backbone(input_features=data, attention_mask=mask,
                                   output_hidden_states=True).hidden_states
                weights = torch.softmax(self.layer_weights, dim=0)
                h = torch.stack(hs).mul(weights[:, None, None, None]).sum(0)
                m = mask[:, :, None].float()
                h = (h * m).sum(1) / m.sum(1).clamp(min=1)
                return self.head(h).squeeze(-1)

        requested = (device or os.environ.get('VOICE_DETECT_DEVICE', 'auto')).lower()
        if requested == 'auto':
            requested = 'mps' if torch.backends.mps.is_available() else 'cpu'
        if requested not in ('cpu', 'mps', 'cuda'):
            raise ValueError('VOICE_DETECT_DEVICE must be auto, cpu, mps or cuda')
        if requested == 'mps' and not torch.backends.mps.is_available():
            raise RuntimeError('Apple Metal (MPS) not available; use VOICE_DETECT_DEVICE=cpu')
        if requested == 'cuda' and not torch.cuda.is_available():
            raise RuntimeError('CUDA not available')
        self.device = requested

        path = os.environ.get('PELLA_WEIGHTS')
        if not path:
            print('Downloading/verifying PellaV2 checkpoint (~2.32 GB on first use)...', flush=True)
            path = hf_hub_download(HUB_REPO, filename='pellav2_detector.pt')
        if not Path(path).is_file():
            raise FileNotFoundError(path)
        print('Building PellaV2 model from W2V-BERT config...', flush=True)
        model = Detector()
        print('Loading trained checkpoint (strict parameter validation)...', flush=True)
        state = torch.load(path, map_location='cpu', weights_only=True)
        model.load_state_dict(state, strict=True)
        del state
        self.model = model.to(requested).eval()
        self.torch = torch
        print(f'PellaV2 ready on {requested} (16kHz, 4-second windows).', flush=True)

    def analyze_timed(self, pcm):
        """Return (raw score, timings). Model time includes fbank and transformer."""
        t0 = time.perf_counter()
        x = self.torch.from_numpy(preprocess(pcm))[None, :]
        t1 = time.perf_counter()
        with self.torch.inference_mode():
            result = float(self.torch.sigmoid(self.model(x)).item())
        t2 = time.perf_counter()
        if not np.isfinite(result) or not 0 <= result <= 1:
            raise ValueError('Model returned an invalid score')
        return result, {
            'preprocess_ms': (t1 - t0) * 1_000,
            'model_ms': (t2 - t1) * 1_000,
            'inference_ms': (t2 - t0) * 1_000,
        }

    def analyze(self, pcm):
        """Backwards-compatible raw score interface."""
        score, _ = self.analyze_timed(pcm)
        return score
