# VoiceShield + PellaV2: local audio-deepfake detector upgrade

PellaV2 replaces the **inference worker**, not the phone calls. Keep your LiveKit, Caddy, HTTPS certificates, and VoiceShield caller/receiver links unchanged. This package also updates the **receiver's detection status panel**. No audio is stored, and the detector subscribes only to `caller` audio. This is an experimental tool, not a verified caller-authentication system.

## Model selection and limitations

- Model: [PellaV2](https://huggingface.co/Sadanie/pellav2-audio-deepfake-detector) (MIT weights; ~1.26 GB checkpoint). Weights are **not** bundled.
- Why: An independent Podonos benchmark ranked the downloadable PellaV2 model at 95.82% accuracy on 4,524 clips from modern synthetic-speech systems. The figure **is not a phone-call accuracy estimate**, and 57ms model latency was measured on a T4 GPU, not a Mac.
- Source implementation: Pella's `pellav2_infer.py` uses **Wav2Vec2BertModel** (`facebook/w2v-bert-2.0`), regardless of inconsistent model-card references to XLS-R. This adapter initializes the same backbone from its configuration, loads **every tensor strictly** from Pella's full checkpoint, and computes Kaldi filterbanks on CPU for Mac compatibility.
- The pretrained model is intended primarily for clean English speech. WebRTC, AGC, noise, phone compression, speakers, unseen TTS systems, and other languages can defeat it. The raw `p_fake` score is **not a calibrated phone-call probability**. Don't assume a low score proves someone is human.

## A. Install the patch — keep your working app safe

Download `voiceshield-pellav2-upgrade.zip`, then:

```bash
cd ~/telephony
cp -R livekit-audio-phone livekit-audio-phone.before-pella
unzip -o ~/Downloads/voiceshield-pellav2-upgrade.zip
cd livekit-audio-phone
```

The zip contains `livekit-audio-phone/...`. It **does not** change `~/telephony/Caddyfile` or `~/telephony/livekit.yaml`.

## B. Python environment on macOS

Use Python 3.11 as an independent environment; leave `.venv-bankify` untouched:

```bash
conda create -n voiceshield-pella python=3.11 -y
conda activate voiceshield-pella
cd ~/telephony/livekit-audio-phone
python -m pip install --upgrade pip
python -m pip install -r voice_detector/requirements.txt
python -m pip check
python -m unittest discover -s voice_detector -p 'test_*.py'
```

First startup downloads **1.26 GB** of Pella weights plus a small W2V-BERT model configuration from Hugging Face. This model also requires significant RAM and inference compute; on an older Intel Mac, it might not keep up with realtime, even though dropping old windows prevents queue growth. `VOICE_DETECT_DEVICE=auto` chooses Apple Metal (MPS) when supported, otherwise CPU. If MPS errors, set `export VOICE_DETECT_DEVICE=cpu` before launching.

## C. Shared token — avoid previous HTTP 403

If you already created `~/telephony/.voiceshield-worker-token`, reuse it **only if it is still secret**. Otherwise generate a fresh secret and restart BOTH processes with it:

```bash
cd ~/telephony
umask 077
python3 -c 'import secrets;print(secrets.token_urlsafe(32))' > .voiceshield-worker-token
```

Never paste the token into chat or expose the file through a directory listing.

## D. Build and restart the VoiceShield website

Stop your old `python3 server.py` process with Control+C, **not** LiveKit or Caddy. In its Terminal:

```bash
cd ~/telephony/livekit-audio-phone
npm install
npm run build
export VOICESHIELD_WORKER_TOKEN="$(cat ~/telephony/.voiceshield-worker-token)"
python3 server.py
```

## E. Start the PellaV2 detector worker

Stop your old **Bankify detection worker** with Control+C. In a new Terminal:

```bash
cd ~/telephony/livekit-audio-phone
conda activate voiceshield-pella
export VOICESHIELD_WORKER_TOKEN="$(cat ~/telephony/.voiceshield-worker-token)"
export VOICE_DETECT_DEVICE=auto
python -u voice_detector/livekit_pella.py
```

Expected (illustrative, not guaranteed):

```
Downloading/verifying PellaV2 checkpoint (~1.26 GB on first use)...
Building PellaV2 model from W2V-BERT config...
Loading trained checkpoint (strict parameter validation)...
PellaV2 ready on mps (16kHz, 4-second windows).
Connected to 'fraud-test' as silent read-only detector
Caller-only PCM stream active
[0001] UNSURE ...
[0002] FAKE ...
```

The first result needs about four seconds of caller audio. Subsequent results are intended once per second, **if your Mac infers fast enough**. Status expires after 12 seconds without new messages.

## F. Open VoiceShield on two phones

- Caller: `https://10.255.104.249:8444/?role=caller&v=pella2`
- Receiver: `https://10.255.104.249:8444/?role=receiver&v=pella2`

The receiver panel shows `No strong synthetic indicators`, `Inconclusive`, or `Repeated synthetic-voice indicators`. It never asserts certain human/AI identity. The raw score is **not a calibrated confidence percentage**. The high-risk state requires **two elevated observations** across the latest three windows. Silence or unreadable audio resets that running assessment. There is no transcript and no call recording.

Check detection status locally:

```bash
curl -s http://127.0.0.1:3000/api/detection
```

To reproduce a problem, send **only the non-sensitive console error**, no secret tokens or private audio.

## G. Test against your own real and synthetic audio

Put labeled `.wav`, `.flac`, or `.ogg` clips in separate folders, then:

```bash
python voice_detector/evaluate_clips.py --real-dir ~/telephony/testclips/human --fake-dir ~/telephony/testclips/ai
```

For an approximate **narrowband codec stress test** (not a replacement for actual phone-call audio):

```bash
python voice_detector/evaluate_clips.py --real-dir ~/telephony/testclips/human --fake-dir ~/telephony/testclips/ai --phone-emulation
```

The script reports detection/false-alarm rates at various thresholds. Evaluate separate recordings from **both phones** in VoiceShield before adjusting any threshold. Do not claim a safety improvement without measuring how many AI clips you still miss. Obtain everyone's consent for any recordings or monitoring.

## Troubleshooting

| Symptom | Action |
|---|---|
| `403 Forbidden` posting status | Restart website and worker with **the same private** `VOICESHIELD_WORKER_TOKEN`; stop older workers. |
| `strict load_state_dict` mismatch | The checkpoint or package architecture differs; **do not** silently ignore missing layers or randomly initialize weights. Share the error. |
| MPS/Metal runtime error | Stop worker; use `export VOICE_DETECT_DEVICE=cpu`. |
| Inference takes longer than 1 second | Logs display `dropped=`; machine may not keep up. Use a stronger Mac or slower window hop. |
| `Offline` despite a call | Worker not running or results older than 12 seconds; check token and worker terminal. |
| Human speech marked fake / AI speech marked human | Collect labeled **over-the-call** tests and calibrate by phone/channel; no static pretrained detector is perfect. |

### Privacy/security limits

This is a **local prototype only**. The website's token endpoint does not authenticate callers/receivers, and the server exposes recent scores to anyone on the LAN who knows its URL. The root CA you installed on test phones must be handled carefully. Never expose the development API key `devkey` / secret `secret`, website, or status endpoints to the public internet. Do not use a deepfake score alone for a bank access decision.
