# wizpr-tools

**A reverse-engineering and protocol exploration toolkit for the WIZPR Ring.**

This repo is a workshop for mapping what the WIZPR Ring does over BLE: capturing its signals, decoding its protocol, and writing down what we found so it's reproducible. The actual apps (iOS client, MCP integrations, AI tooling) live in their own separate repos.

The protocol is fully mapped, including the audio codec. See [`docs/protocol.md`](docs/protocol.md) for the GATT reference, [`docs/audio_protocol.md`](docs/audio_protocol.md) for the audio decoder, and [`docs/quickstart.md`](docs/quickstart.md) if you just want to talk to the ring from your own code.

---

## TL;DR

The ring speaks plain ASCII text on characteristic `00000007`:

```
Ring -> Phone
CLICK           button pressed (one event per press)
MIC_PRE_ON      raise-to-speak motion detected
MIC_ON          mic active, audio streaming on char 00000001
MIC_OFF         mic deactivated
BATTERY N(V)    response to BATTERY query
VER XXXX        response to GET_VERSION query

Phone -> Ring
LOCK            disable ring input (hard mute, overrides gesture state)
BATTERY         query battery level
GET_VERSION     query firmware version
RESET           reboot ring (kills connection)
```

Audio streams on characteristic `00000001` while the mic is on:

```
Codec       IMA ADPCM 4-bit, 16 kHz mono
Frame       224 bytes per BLE packet = 28 ms = 448 samples
Rate        ~35.4 packets/second while MIC_ON
State       continuous across packets (do not reset between notifications)
```

No pairing required. No session handshake. Connect, subscribe, listen.

---

## What's in this repo

### Guided Capture Tool (`wizpr-suite/`)

A macOS desktop app (PySide6 + qasync) that:

- Scans and auto-connects to WIZPR RING
- Subscribes to all notify characteristics simultaneously
- Walks through labeled capture actions one at a time (button presses, voice, gestures)
- Saves a structured JSON session file with every BLE payload, timestamped and labeled
- Includes a live Command Explorer for writing commands back to the ring

**Run it:**

```bash
git clone https://github.com/niclydon/wizpr-tools.git
cd wizpr-tools
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m wizpr-suite.app.main
```

Disconnect the ring from your iPhone before scanning. The ring only advertises when not already connected to another device. See [`docs/hardware-notes.md`](docs/hardware-notes.md) for other gotchas.

### Ring Daemon (`scripts/ring_daemon.py`)

A persistent connection daemon for interactive ring probing. Connects once, subscribes to everything, reads commands from a named pipe at `/tmp/ring.cmd`, writes all output to `/tmp/ring.log`.

```bash
# Terminal 1 - run the daemon (needs GUI session for macOS BT permissions)
python scripts/ring_daemon.py

# Terminal 2 - send commands
echo "write 7 BATTERY" > /tmp/ring.cmd

# Terminal 3 - watch responses
tail -f /tmp/ring.log
```

### Audio Analyzer (`scripts/analyze_audio.py`)

Decodes captured session JSON files into WAV under each codec hypothesis (Opus, IMA ADPCM at multiple rates, mu-law, A-law, raw PCM). Used to identify the codec; kept in the repo as a reproducible artifact of the identification process.

```bash
python scripts/analyze_audio.py ~/.wizprsuite/captures/<session>.json
```

---

## Documentation

- [`docs/quickstart.md`](docs/quickstart.md) - 40-line minimum-viable Python: connect, subscribe, capture audio to WAV
- [`docs/protocol.md`](docs/protocol.md) - Complete GATT reference, command vocabulary, iOS integration notes
- [`docs/audio_protocol.md`](docs/audio_protocol.md) - Audio codec, decoder snippet, real-time decoder class
- [`docs/hardware-notes.md`](docs/hardware-notes.md) - Things you only learn by using it: battery, gestures, BT permissions, PacketLogger setup
- [`docs/explorations/2026-05-ring-protocol-discovery.md`](docs/explorations/2026-05-ring-protocol-discovery.md) - Narrative account of the reverse-engineering process
- [`CHANGES.md`](CHANGES.md) - Decision log: what changed, why, what was rejected

---

## What's still open

- **Write-only chars** (`00000002`, `00000003`, `00000004`, `00000006`) - silently accept writes, observable effect unknown. The official iOS app does not use them in captured sessions; not needed for basic functionality. One of these may control haptic feedback if the ring has a vibration motor; worth probing.
- **`LOCK` semantics** - confirmed it's used as a hard mute that overrides the ring's gesture state machine. Whether it does anything else (deep sleep, connection lock, power management) has not been fully characterized.
- **OTA / firmware update channel** - one write-only characteristic on a separate service (`1d14d6ee-fd63-4fa1-bfa4-8f47b42119f0`) is unprobed. Likely OTA but not confirmed.

---

## Built on the shoulders of

Forked from [R-D-BioTech-Alaska/Wizpr-Suite](https://github.com/R-D-BioTech-Alaska/Wizpr-Suite). None of this work would have been possible without it.

The original project did the genuinely hard parts: figuring out how to connect to the ring over BLE at all, building the GATT inspector, wiring up bleak on macOS, and recognizing that the ring's protocol is undocumented and that the path forward is user-controlled reverse engineering. That framing and tooling is what made it possible to go from zero to a complete protocol map in a single weekend.

Go star [their repo](https://github.com/R-D-BioTech-Alaska/Wizpr-Suite).

Licensed MIT. See [LICENSE](LICENSE).
