# Discovery Journal: Reverse-Engineering the WIZPR Ring

*A narrative account of mapping an undocumented BLE wearable protocol.*

---

## The starting point

The WIZPR Ring is a wearable input device — a ring worn on the finger that detects button presses, raise-to-speak gestures, and captures voice. It connects to a companion iOS app via Bluetooth Low Energy. The protocol is completely undocumented. The manufacturer has not published a GATT spec, an SDK, or any developer documentation. The ring simply works, and nobody outside the company knows exactly how.

The goal here was to change that.

The approach: connect to the ring, subscribe to everything it broadcasts, capture structured labeled data about what signals each physical interaction produces, and probe what commands it responds to. No decompilation, no iOS app reverse engineering — just patient BLE observation.

---

## Getting connected

The first obstacle was finding the ring in a BLE scan.

The initial scan picked up 88 devices — a dense suburban Bluetooth environment: AirPods, Apple Watches, Govee LED strips, smart TVs, a Nespresso machine, a smart bed, an LG television, two Xfinity cable boxes advertising as `xb7_ble`. The ring wasn't in the list.

The reason turned out to be simple: the ring was connected to an iPhone running the official Wizpr app. A BLE peripheral only advertises when it's not already connected. While the iPhone had it, no other device could see it.

Disconnecting the ring from the iPhone — Settings → Bluetooth → tap the `i` → Disconnect — immediately made it appear as `WIZPR RING-97:22`. The `-97:22` suffix is the last two bytes of the ring's Bluetooth MAC address, a common convention for BLE peripherals to make themselves identifiable without full pairing. The full MAC would turn out to be `28:76:81:FA:97:22`, where `28:76:81` is Silicon Labs' OUI — confirming the chip.

The first successful connection happened about two hours into the session.

---

## First data: the protocol is ASCII text

The first meaningful finding came from a single button press.

The ring was connected, all GATT characteristics subscribed. The button was pressed once. The BLE notification on characteristic `00000007` read:

```
CLICK\r\n
```

That was unexpected. Not a byte flag, not a bitmask, not a proprietary binary encoding — a plain ASCII string, terminated with `\r\n`. Human readable, trivially parseable, immediately obvious.

Press it twice: two CLICK events. Three times: three CLICK events. The button protocol was fully understood in under three minutes of testing.

The next press produced:

```
CLICK\r\n
MIC_ON\r\n
```

Followed immediately by a flood of binary data on characteristic `00000001`. The mic had activated. The audio stream started ~50ms after `MIC_ON`.

Holding the ring up and speaking produced the full sequence:

```
MIC_PRE_ON\r\n
MIC_ON\r\n
[binary audio packets]
MIC_OFF\r\n
```

`MIC_PRE_ON` was a new one — a pre-activation signal that fires before the mic turns on, presumably while the hardware is warming up. It arrives about 100ms before `MIC_ON` and appears whenever the ring's IMU detects the raise-to-speak motion threshold.

---

## What the ring talks on

Three notify characteristics carry all the data:

**Char `00000007` (ATT)** is the main command channel. It's bidirectional — the ring sends ASCII events as notifications, and the phone can write ASCII commands. This is where CLICK, MIC_ON, MIC_OFF, and MIC_PRE_ON come from. It also responds to queries: write `BATTERY\r\n` and it notifies `BATTERY 87(3.679147)` — 87% charge, 3.679 volts.

**Char `00000001` (SDP)** is the audio stream. Binary packets, ~200 bytes each, arriving at ~24 packets per second while the mic is active. The codec is not yet identified — the byte distribution doesn't match raw linear PCM.

**Char `00000005` (TCS-BIN)** is a single-byte mic state indicator. Sends `31` (ASCII `1`) on MIC_ON and `30` (ASCII `0`) on MIC_OFF. Redundant with the char7 notifications but useful for polling.

The GATT descriptions — "SDP", "ATT", "TCS-BIN", "RFCOMM" — are artifacts of the Bluetooth SIG's UUID registry. The ring's firmware uses those UUID numbers coincidentally. The characteristics don't implement those protocols. Char `00000007` is not ATT in any formal sense; it's just a command pipe.

---

## The command side

Four characteristics are write-only with no notify capability: `00000002`, `00000003`, `00000004`, `00000006`. They accept writes silently. No physical effect was observed, no notifications fired in response. Probed with ~40 ASCII strings (STATUS, INFO, PING, LED_ON, HAPTIC, VIBRATE, GYRO, ACC, etc.) and several binary patterns (0x00, 0x01, 0xff, 0xaa, 0x55, 0x0101, 0x0100).

Nothing.

The working hypothesis is that these characteristics use a binary framing protocol the iOS app knows but that isn't needed for basic ring functionality. They might be for audio codec configuration, stream control, or firmware-level settings. Since the ring streams audio fine without touching them, they're not blocking.

One accidental discovery: writing `RESET\r\n` to char7 rebooted the ring. Every other unknown command was silently absorbed. RESET caused an immediate disconnect. That's useful to know — and explains why it was never observed in normal use.

---

## The btsnoop capture

After mapping everything the ring sends, the remaining question was: what does the iOS app send?

Apple's PacketLogger tool, with a Bluetooth diagnostic profile installed on the iPhone, captures every HCI packet the device processes. After some setup friction — PacketLogger shows the connected iPhone but captures nothing without the diagnostic profile, which has to be installed separately from developer.apple.com — a full capture session was collected.

7,113 records. 202 ACL TX (phone → controller) packets. Of those, **2 were addressed to the ring's connection handle (0x403)**.

Both were ATT WRITE_REQ operations to handle `0x0029` (char7), value: **`LOCK\r\n`**.

That's the complete iOS app → ring command vocabulary. One command. `LOCK`. Sent when the session ends.

The ring is almost entirely autonomous. It sends events; the phone listens. The phone never initiates a mic activation, never sends audio configuration, never handshakes on connect. The only thing it says to the ring is "we're done" when closing out.

---

## What this means for building the iOS app

The protocol is simpler than almost any reasonable prior expectation.

**Connection:** scan for `WIZPR RING`, connect, subscribe to char7 and char1. No pairing, no auth, no session init.

**Input events:**
- Count CLICK notifications within a debounce window for single/double/triple press
- Watch for MIC_PRE_ON to prep the audio pipeline (buffer, allocate, show UI)
- Watch for MIC_ON to start recording char1 audio
- Watch for MIC_OFF to stop and process

**On session end:** write `LOCK\r\n` to char7.

**Battery check:** write `BATTERY\r\n` to char7, read the notification response.

The remaining open problem is audio decoding. The char1 stream is compressed binary — probably ADPCM or a Silicon Labs proprietary codec — and can't be played back or fed to a local transcription model without first identifying and implementing a decoder. Sending the raw bytes to a cloud STT API that accepts compressed audio (like OpenAI Whisper with format detection) may work as a short-term bypass.

---

## What's still unknown

1. **Audio codec.** The most important unknown for building a fully offline voice pipeline.
2. **Chars 00000002/3/4/6.** Write-only, silent. May be audio configuration. Not blocking.
3. **Char `f7bf3564`.** In a separate service. Not used by the iOS app. Probably OTA/factory.
4. **LOCK semantics.** Does it disable button input? Does it disable the motion sensor? Does it persist across power cycles? Not yet tested — would require sending LOCK and then verifying that button presses stop generating CLICK events.
5. **Firmware `A005` vs `9.0.0`.** The Device Information service reports `9.0.0` as the firmware revision, but `GET_VERSION` returns `VER A005`. These appear to be different layers — `9.0.0` is likely the Silicon Labs BLE stack version, `A005` is the application firmware. Whether `A005` is version 5 of some internal scheme or a different encoding is unknown.

---

## Timeline

| Date | Milestone |
|---|---|
| 2026-05-02 | Forked upstream, fixed dataclass bugs, first successful connection |
| 2026-05-02 | First button press captured: `CLICK\r\n` protocol confirmed |
| 2026-05-02 | Audio stream discovered on char1, MIC_PRE_ON/MIC_ON/MIC_OFF mapped |
| 2026-05-02 | Guided capture tool built and deployed to MacBook |
| 2026-05-02 | Three capture sessions completed (sessions 1-3) |
| 2026-05-02 | Device info read: Silicon Labs, firmware 9.0.0, MAC confirmed |
| 2026-05-02 | BATTERY and GET_VERSION commands confirmed |
| 2026-05-02 | ring_daemon built — persistent interactive ring shell |
| 2026-05-02 | ~40 commands probed via daemon, RESET confirmed, LOCK not yet known |
| 2026-05-03 | btsnoop capture from iOS app analyzed |
| 2026-05-03 | LOCK command discovered — iOS app's complete outbound vocabulary |
| 2026-05-03 | Protocol map finalized |
