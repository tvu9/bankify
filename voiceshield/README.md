**Current detector upgrade:** see [PELLA_UPGRADE.md](PELLA_UPGRADE.md) for PellaV2 setup and testing. The older Bankify bridge remains in the repository for reference but should not run concurrently.

# VoiceShield — local audio-only phone interface

A custom mobile-first, audio-only WebRTC call interface for your **already working** local LiveKit server and Caddy HTTPS proxy. No camera API is called. This is an internet/LAN call, **not** a native cellular call. No AI model is included yet.

## Requirements
- macOS, Node.js 20.19+ or 22.12+ (`node -v`), npm, Python 3
- Your LiveKit server running on 127.0.0.1:7880 with `devkey/secret`, WebRTC reachable over LAN
- Caddy and its local CA already installed/trusted on the two test phones
- Mac address remains **10.255.104.249** (change configs if it changes)

## Setup
From this downloaded project directory:

```bash
npm install
npm run build
python3 server.py
```

Leave the Python server running. `server.py` binds only to 127.0.0.1:3000.

### Update Caddy (without stopping LiveKit)
Open `~/telephony/Caddyfile` and add a **second** site block (while retaining your existing 8443 block):

```caddyfile
https://10.255.104.249:8444 {
    tls internal
    reverse_proxy 127.0.0.1:3000
}
```

Or use `Caddyfile.example` as your complete Caddyfile if your existing setup is exactly the same. Validate and reload the **already running** Caddy:

```bash
cd ~/telephony
caddy validate --config Caddyfile
caddy reload --config Caddyfile
```

If reload fails because Caddy was launched with a different config, use `Control+C` in the Caddy terminal and `caddy run --config ~/telephony/Caddyfile` again.

### Test

```bash
curl -k -i https://10.255.104.249:8444/health
```

On Phone 1 open: `https://10.255.104.249:8444/?role=caller`

On Phone 2 open: `https://10.255.104.249:8444/?role=receiver`

Tap **Start audio call** on each. Allow microphone permission. Both phones must reach your Mac over local Wi-Fi. Use headphones if the devices are close to each other.

**Mute** toggles microphone publishing. **Speaker on/off** mutes or unmutes remote audio playback *inside the web page*; it does **not** switch iPhone earpiece vs loudspeaker routing (that requires native APIs and isn't generally available to web apps). **Hang up** disconnects only the phone that tapped it.

## Troubleshooting
- `502` on 8444: `python3 server.py` is not running.
- Browser certificate/privacy error: trust your local Caddy `root.crt` on that device. Never distribute `root.key`.
- Can't connect to room: check LiveKit 7880, Caddy 8443, server IP, token endpoint and Wi-Fi. Check browser developer console.
- Connected but silent: check microphone permission, iOS silent mode/output route, network UDP 7882 and tap Speaker to enable browser playback.
- Duplicate identity: only one device per role can join at a time. Close previous caller/receiver sessions.
- IP changed: update Caddyfile, `LIVEKIT_PUBLIC_URL` and LiveKit `rtc.node_ip` and get new Caddy certificates if needed.

## Security and scope
- **Developer proof of concept only.** Anyone who can access port 8444 can retrieve a signed token for either role; do not expose this on the Internet or use with strangers. Add authentication, rate limits, and short-lived single-use role invitations before production.
- The `devkey/secret` keys are development credentials. `server.py` issues short-lived tokens; it does not send signing secrets to browsers.
- The token is limited to publishing microphone tracks, subscribing to room media, and joining the `fraud-test` room.
- HTTPS protects signaling; LiveKit uses WebRTC encrypted transport for media.
- Safari may pause/disconnect a webpage during phone lock or backgrounding. Reliable always-on background calls and iOS output routing usually need a native app.
- Call monitoring/detection isn't implemented yet. Obtain participant consent before analyzing or retaining call audio.


## iPhone microphone fix (v1.0.1)

This revision acquires the microphone directly from the Start Audio Call click event before fetching tokens or connecting to LiveKit. It also reports the failing phase (microphone, token, connection, publish microphone).

Replace the project files, run `npm install && npm run build`, restart `python3 server.py`, and force-refresh Safari (or add `?role=caller&v=2` to the URL). Your existing LiveKit and Caddy configurations do not need changes.
