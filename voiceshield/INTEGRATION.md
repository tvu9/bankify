# VoiceShield + Bankify integration (macOS local lab)

This package is an **upgrade** to your working `~/telephony/livekit-audio-phone` app. It keeps the two-way audio interface and adds a Python LiveKit subscription worker and a receiver-side risk panel. No live-call recordings or transcripts are stored by the new bridge. The displayed probabilities are **unverified experimental model outputs**, not proof that a person is synthetic or fraudulent.

## 1. Install this upgrade, preserving your original files

Before copying, back up your working app:

```bash
cd ~/telephony
cp -R livekit-audio-phone livekit-audio-phone.backup
unzip -o ~/Downloads/voiceshield-bankify-integration.zip
```

The archive contains `livekit-audio-phone/...`; do **not** delete your current `Caddyfile` or `livekit.yaml`. It contains no Bankify weights or original Bankify source (clone them separately).

## 2. Fetch Bankify and verify checkpoint

```bash
cd ~/telephony
git clone https://github.com/JuanCruzSalinas-be/bankify.git
ls -lh ~/telephony/bankify/models/detector.joblib
```

**If `detector.joblib` does not exist, stop here.** The published Bankify code expects a trained `models/detector.joblib`. The bridge intentionally refuses to invent model results. Follow Bankify's own `prepare_data.py` + `python detector.py` training process if its required dataset is available, or obtain the trained classifier from the authors. The Hugging Face `facebook/wav2vec2-base-960h` model downloads on first startup and is distinct from the separately trained classifier.

## 3. Install Python dependencies in an isolated environment

Use Python 3.11 or 3.12 if available:

```bash
cd ~/telephony/livekit-audio-phone
python3 -m venv .venv-bankify
source .venv-bankify/bin/activate
python -m pip install --upgrade pip
python -m pip install -r bankify_bridge/requirements.txt
python -m pip install torch transformers scikit-learn joblib librosa soundfile
```

Ensure your versions of `transformers` and `torch` load the Bankify code; if its dependencies have changed, install compatible releases. Bankify does not publish a pinned requirements file in the repository inspected for this integration.

## 4. Set a shared secret for worker-to-website status updates

Choose one random secret and use **the same value** for both terminals:

```bash
export VOICESHIELD_WORKER_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
echo "$VOICESHIELD_WORKER_TOKEN"
```

Copy that secret into the worker terminal using `export VOICESHIELD_WORKER_TOKEN='YOUR_VALUE'`. Do not share it publicly or paste it into the phones. The site server binds only to localhost on port 3000; Caddy exposes the read-only `/api/detection` endpoint to the test LAN. This is not hardened for Internet exposure.

## 5. Build and run website

In the website terminal, stop the old `python3 server.py` with Control+C and run:

```bash
cd ~/telephony/livekit-audio-phone
npm install
npm run build
export VOICESHIELD_WORKER_TOKEN='YOUR_VALUE'
python3 server.py
```

Keep your existing LiveKit (`7880`) and Caddy (`8443`, `8444`) services running as before; their configuration **does not change**.

## 6. Run detection worker in a new terminal

```bash
cd ~/telephony/livekit-audio-phone
source .venv-bankify/bin/activate
export VOICESHIELD_WORKER_TOKEN='YOUR_VALUE'
export BANKIFY_DIR="$HOME/telephony/bankify"
python bankify_bridge/livekit_bankify.py
```

Expected: `Bankify loaded` and `Joined LiveKit as read-only bankify-detector`. When the caller speaks, Terminal prints classification windows. The worker uses the caller track only, 16-kHz mono decoding, three-second windows and a one-second hop. Queue maxsize is two (old windows are dropped if inference lags).

## 7. Test the receiver UI

- Caller: `https://10.255.104.249:8444/?role=caller&v=bankify1`
- Receiver: `https://10.255.104.249:8444/?role=receiver&v=bankify1`

The receiver panel should show **Monitoring**, then current risk estimates after enough speech. It will show Offline when the worker is stopped or its updates become stale (>12 sec). This release does not change the microphone-permission fix.

Check locally:

```bash
curl -k https://10.255.104.249:8444/api/detection
```

## Constraints / caveats

- The repository currently uses `facebook/wav2vec2-base-960h` with a separate logistic-regression classifier, **not XLS-R**.
- Its training checkpoint must exist and must be trusted; `joblib.load` can execute arbitrary Python objects. Never load untrusted checkpoints.
- Scores and cutoffs (`<0.3`, `>0.7`) originate as prototype heuristics; calibrate and evaluate on realistic audio before treating them as trustworthy alerts. No actual fraud conclusion follows from a voice result.
- The status endpoint has no caller authorization and the token endpoint still permits LAN clients to impersonate caller/receiver. Never expose this development version publicly.
- Safari may stop the webpage while backgrounded or locked. This is a VoIP website, not a cellular phone interception tool.
- Require consent from participants before live audio analysis.
