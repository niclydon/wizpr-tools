# WIZPR Ring Protocol Reference

Reverse-engineered from BLE captures and live probing. Last updated 2026-05-03.

---

## Hardware

| Field | Value |
|---|---|
| Device name (advertised) | `WIZPR RING-97:22` |
| BLE MAC | `28:76:81:FA:97:22` |
| OUI | Silicon Labs (`28:76:81`) |
| BLE stack firmware | `9.0.0` |
| Application firmware | `VER A005` |
| iPhone platform | iPhone 16 Pro (iOS) |

The suffix `-97:22` in the device name is the last two bytes of the MAC address. This is consistent across reboots and appears to be the ring's persistent identifier.

---

## GATT Map

### Service: `0000180a` — Device Information (standard)

Read-only metadata. Not used at runtime.

| UUID | Description | Value |
|---|---|---|
| `00002a29` | Manufacturer Name | `Silicon Labs` |
| `00002a24` | Model Number | *(null)* |
| `00002a27` | Hardware Revision | *(null)* |
| `00002a26` | Firmware Revision | `9.0.0` |
| `00002a23` | System ID | `287681fffefa9722` |

---

### Service: `00000000-dc2e-4362-93d3-df429eb3ad10` — Ring Control Service

The main service. All runtime communication happens here.

#### Characteristic `00000007` — Command Channel

**Properties:** read, write, write-without-response, notify

This is the primary bidirectional channel. The ring sends ASCII events as notifications. The phone sends ASCII commands as writes.

**Ring → Phone (notifications):**

| Event | Trigger | Notes |
|---|---|---|
| `CLICK\r\n` | Button pressed | One event per press. Count = press count (1/2/3) |
| `MIC_PRE_ON\r\n` | Motion detected | Pre-activation warning before mic turns on |
| `MIC_ON\r\n` | Mic activated | Audio stream starts on char `00000001` |
| `MIC_OFF\r\n` | Mic deactivated | Audio stream stops |
| `BATTERY N(V.VVV)\r\n` | Response to BATTERY command | e.g. `BATTERY 87(3.679147)` |
| `VER XXXX\r\n` | Response to GET_VERSION command | e.g. `VER A005` |

**Phone → Ring (writes):**

| Command | Effect |
|---|---|
| `LOCK\r\n` | Disables ring input. Sent by iOS app on session end. |
| `BATTERY\r\n` | Ring responds with `BATTERY N(V.VVV)` notification |
| `GET_VERSION\r\n` | Ring responds with `VER XXXX` notification |
| `RESET\r\n` | Ring reboots and disconnects |

**Read behavior:** Reading char7 returns the last written value zero-padded to 250 bytes. This is a write buffer, not a response register. Do not rely on reads for command responses — subscribe to notifications instead.

---

#### Characteristic `00000001` - Audio Stream

**Properties:** indicate, notify

Streams encoded audio packets while the microphone is active (between `MIC_ON` and `MIC_OFF` events).

**Observed behavior:**
- ~35.4 packets per second while mic is on
- Each packet: 224 bytes (fixed - this was the diagnostic that ruled out variable-bitrate codecs)
- Stream starts within ~50ms of `MIC_ON`
- Stream stops immediately on `MIC_OFF`

**Codec:** IMA ADPCM (Intel/DVI ADPCM), 4-bit, 16 kHz mono.

- 224 bytes per packet x 2 nibbles/byte = 448 samples
- 448 samples / 16 kHz = 28 ms of audio per packet
- 35.4 packets/second x 28 ms/packet = 0.99 seconds of audio per real second (1% packet-boundary loss)
- Encoded bitrate: ~64 kbps; decoded PCM bitrate: 256 kbps (16-bit, 16 kHz, mono)

**Critical:** ADPCM predictor state and step index are continuous across BLE packets. Do NOT reset state between notifications. Each packet continues the running predictor from the previous one. Resetting state per packet produces noise.

Full decoder snippet, real-time decoder class, and integration sequence: see [`audio_protocol.md`](audio_protocol.md).

---

#### Characteristic `00000005` — Mic State Bit

**Properties:** notify

Single-byte state indicator that mirrors mic state.

| Value (hex) | Value (ASCII) | Meaning |
|---|---|---|
| `31` | `1` | Mic on |
| `30` | `0` | Mic off |

Fires simultaneously with `MIC_ON` / `MIC_OFF` on char7. Redundant — char7 notifications are sufficient. May be for hardware-level state polling.

---

#### Characteristics `00000002`, `00000003`, `00000004`, `00000006`

**Properties:** write only

Purpose unknown. All write attempts (ASCII commands, binary byte patterns) were silently accepted with no observable effect. Not used by the iOS app in captured sessions. Not needed for basic iOS app functionality.

---

### Service: `1d14d6ee-fd63-4fa1-bfa4-8f47b42119f0` — Unknown

One write-only characteristic (`f7bf3564`). Not used by the iOS app in captures. Likely OTA update or factory configuration. Not probed.

---

## Event Sequences

### Button press (single/double/triple)

```
Ring → CLICK\r\n          (one per press, arrives ~50ms after physical press)
Ring → CLICK\r\n          (second press, if double)
Ring → CLICK\r\n          (third press, if triple)
```

Count the CLICK events within a debounce window (~300ms) to distinguish single/double/triple.

---

### Raise-to-speak (motion-triggered mic)

```
Ring → MIC_PRE_ON\r\n     (motion threshold crossed, mic warming up)
Ring → MIC_ON\r\n         (mic active)
char5: 31                 (state bit = 1)
char1: [audio packets]    (streaming at ~24 pkt/sec)
...
Ring → MIC_OFF\r\n        (mic deactivated, motion stopped or timeout)
char5: 30                 (state bit = 0)
```

`MIC_PRE_ON` fires ~100ms before `MIC_ON`. The ring has a motion sensor (IMU) that detects the raise-to-speak gesture. Any significant motion above a threshold triggers this sequence — it's not exclusive to tilt-up. Rotation and tapping the ring body also trigger it.

---

### Button press → auto-mic (observed in first session)

Single button press triggers both CLICK and immediate mic activation:

```
Ring → CLICK\r\n
Ring → MIC_ON\r\n
char1: [audio packets]
Ring → MIC_OFF\r\n
```

This behavior was inconsistent across sessions — sometimes single press only sent CLICK without mic activation. The ring may have a user-configurable setting for whether button press activates the mic.

---

### Battery query

```
Phone → BATTERY\r\n       (write to char7)
Ring  → BATTERY N(V.VVV)  (notification on char7)
```

Example: `BATTERY 87(3.679147)` — 87% charge, 3.679V. The voltage reading is consistent and appears accurate (drops slightly between queries as expected).

---

### Session end

```
Phone → LOCK\r\n          (write to char7)
```

The iOS app sends this once when the user closes the app or the session ends. Presumably disables ring input until reconnection.

---

## iOS App Integration Notes

**Minimum required subscriptions:**
- char7 (`00000007`) for events (CLICK, MIC_ON/OFF, command responses)
- char1 (`00000001`) for audio stream

**Optional:**
- char5 (`00000005`) for mic state bit (redundant with char7 events)

**Connection sequence:**
1. Scan for BLE devices with name prefix `WIZPR RING`
2. Connect
3. Subscribe to char7 notifications
4. Subscribe to char1 notifications
5. Subscribe to char5 notifications (optional)
6. On session end: write `LOCK\r\n` to char7
7. Disconnect

**No pairing required.** The ring does not require bonding. Connect and subscribe without any authentication handshake.

**One connection at a time.** The ring only accepts one active BLE connection. If connected to an iPhone via the official app, it will not advertise and cannot be connected to from another device. The user must disconnect from the iOS app before connecting from a new client.

---

## Audio Format

Identified 2026-05-03. See [`audio_protocol.md`](audio_protocol.md) for full decoder details.

| Property | Value |
|---|---|
| Codec | IMA ADPCM (Intel/DVI ADPCM), 4-bit |
| Sample rate | 16,000 Hz |
| Channels | mono |
| Frame size | 224 bytes per BLE packet |
| Samples per packet | 448 (224 bytes x 2 nibbles) |
| Frame duration | 28 ms |
| Packet rate | ~35.4 pkt/s |
| Encoded bitrate | ~64 kbps |
| State | continuous across packets |

### Identification method

All 243 audio packets across two voice captures were exactly 224 bytes - fixed size. This single observation ruled out Opus and every other variable-bitrate codec before any decode was attempted, since VBR codecs produce variable-length frames per packet. Two codec hypotheses fit the math (ADPCM at 16 kHz, or mu-law/A-law at 8 kHz - both produce ~28 ms per 224-byte packet at the observed rate). Tested all candidates by decoding 243 packets to WAV with `scripts/analyze_audio.py`. Only `adpcm_cont_16000` produced intelligible audio.

The lesson: when reverse-engineering an unknown audio stream, measure invariants first (packet size constancy, packet rate, payload size distribution) before reaching for a decoder library. The invariants narrow the search space dramatically.
