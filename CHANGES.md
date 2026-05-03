# Changes & Decisions

Newest entry on top. One entry per meaningful decision or discovery. Append as you go.

---

## 2026-05-03 — btsnoop analysis: iOS app sends only one command

Captured BLE traffic from the official iOS Wizpr app using Apple PacketLogger with a Bluetooth diagnostic profile on iPhone 16 Pro. 7,113 HCI records. Of 202 ACL TX packets (phone → controller), exactly **2 were addressed to the ring's connection handle (0x403)**: both ATT WRITE_REQ to handle `0x0029` (char7), value `LOCK\r\n`.

**The iOS app's complete outbound vocabulary is one command: LOCK.** Sent when the user closes a session.

**Why this matters:** The ring is almost entirely self-directing. The phone's job is to listen, not to orchestrate. No session handshake on connect, no mic activation command, no audio config writes. This dramatically simplifies the iOS app — connect, subscribe, handle events, write LOCK when done.

**Setup friction:** PacketLogger shows the connected iPhone but captures zero traffic without an Apple Bluetooth diagnostic profile installed from `developer.apple.com/bug-reporting/profiles-and-logs/`. The profile enables kernel-level HCI logging. Without it, the UI is connected but the capture hook is not active.

**File format:** PacketLogger's `.btsnoop` export is Apple's native format, not standard btsnoop. Magic bytes `1c0000002f6ff669` differ from `btsnoop\0`. Custom parser: records are `uint32_le length + uint64_le timestamp + uint8 type + payload`. Types: 0=HCI_CMD, 1=HCI_EVENT, 2=ACL_TX, 3=ACL_RX, 252=text metadata.

---

## 2026-05-03 — Live command probing via ring_daemon: BATTERY and GET_VERSION confirmed

Probed ~40 ASCII commands against char7 via the ring daemon. Results:

**Confirmed working (char7 notify response):**
- `BATTERY` → `BATTERY 87(3.679147)` — percentage and voltage. Consistent across multiple calls, voltage drops slightly between calls as expected.
- `GET_VERSION` → `VER A005` — application firmware version.
- `RESET` → ring disconnects immediately — confirmed live reboot command. Caused all subsequent probe attempts in that session to fail with "Service Discovery has not been performed yet".

**Silent but accepted (no response, no physical effect):**
MIC_ON, MIC_OFF, LED_ON, LED_OFF, HAPTIC, VIBRATE, BEEP, STATUS, INFO, WAKE, GYRO, ACC, TEMP, GET_STATE, and ~25 others. The ring processes writes but its vocabulary is small.

**Echo buffer behavior confirmed:** Reading char7 after a write returns the last written value zero-padded to 250 bytes. Not a response register. The contamination artifact (`STATUS\r\nERY` showing up after `STATUS`) is leftover bytes from `BATTERY` in the buffer — the null-padding doesn't fully zero the previous content.

---

## 2026-05-02 — ring_daemon: persistent FIFO-based ring shell

Built `scripts/ring_daemon.py` — a persistent connection daemon that holds the ring's BLE connection and processes commands from a named FIFO at `/tmp/ring.cmd`, logging everything to `/tmp/ring.log`.

**Why:** The original probe workflow required write script → push git → pull MacBook → launch via osascript → wait → read log. Each round trip was 2-3 minutes. With the daemon, sending a command and reading the response takes under 2 seconds from any SSH terminal.

**Why FIFO not HTTP:** Zero dependencies. No port to manage, no server lifecycle, no framework. `echo "write 7 BATTERY" > /tmp/ring.cmd` is the entire client interface.

**Bluetooth authorization constraint on macOS:** Processes launched via SSH don't have Bluetooth permission — macOS requires the process to run in a user's active GUI session. The daemon is launched via `osascript` (opens a Terminal window) so it runs with full permissions. SSH sessions can then write to the FIFO and read the log without touching Bluetooth directly.

---

## 2026-05-02 — Capture tool: audio freeze fixed

First run of the guided capture tool froze during voice captures. Countdown timer queued up, then fired all at once when the thread freed.

**Root cause:** The BLE audio stream fires ~24 notifications per second, each ~200 bytes. The payload list widget was calling `addItem()` with a 400-char hex string at 24fps and `scrollToBottom()` on every packet — killed the Qt main thread.

**Fix:** Audio packets (char `00000001`) are captured to the session JSON silently. The live display shows a single updating label (`🎙 Audio stream: N packets captured`) instead of one row per packet. ASCII events (CLICK, MIC_ON, etc.) still render normally — they arrive at most a few times per second.

**Rejected alternative:** Rate-limiting the display (show every Nth packet). Rejected because the count label is more useful than partial hex dumps anyway.

---

## 2026-05-02 — Three capture sessions: protocol initial mapping

Three guided capture sessions run (sessions saved to `~/.wizprsuite/captures/` on MacBook). Confirmed across sessions:

**Button:** `CLICK\r\n` on char7, one event per press. Count = press type (1/2/3). Zero ambiguity.

**Mic events:** `MIC_PRE_ON\r\n`, `MIC_ON\r\n`, `MIC_OFF\r\n` on char7. `MIC_PRE_ON` fires ~100ms before `MIC_ON`. The ring's IMU triggers this sequence — any significant motion above threshold activates it, not just deliberate raise-to-speak. Rotate and tap-body both triggered the same MIC sequence.

**Audio:** char1 (`00000001`) streams binary at ~24 packets/second while mic is active. Codec unknown.

**Baseline:** idle action captured zero events across all three sessions. Clean floor.

**Actions removed after first session:**
- `button_long` — turns the device off. Discovered on first test.
- `tilt_down`, `wear`, `remove`, `shake` — zero payloads across all sessions.

**Device info read:** Silicon Labs manufacturer, firmware `9.0.0` (BLE stack), system ID `287681fffefa9722`. System ID decodes as MAC `28:76:81:FA:97:22` — OUI `28:76:81` = Silicon Labs, last 2 bytes `97:22` match advertised name suffix.

---

## 2026-05-02 — Built guided capture tool (replaced original UI)

Replaced the upstream tabbed LLM control plane with a linear guided capture flow. Original UI had Devices, Models, Chat, Commands, and Logs tabs — none relevant for protocol discovery.

**New flow:** auto-scan for WIZPR RING → connect → enumerate GATT + read device info → subscribe all notify characteristics → guided action prompts one at a time (5-second countdown) → JSON output at `~/.wizprsuite/captures/YYYY-MM-DD-HH-MM-SS.json`.

**`qasync` for event loop:** PySide6 and asyncio don't share a loop by default. `qasync` bridges them so BLE async callbacks fire while Qt stays responsive. Bleak requires asyncio; PySide6 requires Qt. Both are needed concurrently.

**Guided vs manual labeling:** Chose guided (app instructs the action) over manual (user types a label). Reason: consistent labels across sessions, no transcription error, JSON directly comparable across captures.

**Action list rationale:** 15 initial actions reduced to 10 after first session. Removed long press (off switch), tilt down (no signal), wear/remove (no proximity sensor exposed), shake (no distinct IMU event). Kept single/double/triple button, voice short/long, tilt up, rotate cw/ccw, tap body, idle.

---

## 2026-05-02 — BLE scan filter: WIZPR RING prefix only

Original scan returned 88+ devices. Filtered to name prefix `WIZPR RING` once the advertised name was confirmed.

**How the name was found:** First several scans returned nothing because the ring was connected to an iPhone and not advertising. Disconnecting it from the iPhone (Settings → Bluetooth → Disconnect) made it appear immediately as `WIZPR RING-97:22`. The `-97:22` suffix is the last two bytes of the MAC address, a common BLE convention.

---

## 2026-05-02 — Initial fork: R-D-BioTech-Alaska/Wizpr-Suite → niclydon/wizpr-tools

Forked rather than built from scratch. The upstream had solved the hard parts: BLE scan/connect via bleak, GATT inspector, PySide6 patterns, and the framing that the ring's protocol is undocumented and requires user-controlled reverse engineering.

Fixed four missing `@dataclass` decorators on `RingProfile`, `DiscoveredDevice`, `OpenAIConfig`, `OllamaConfig`, `OpenAICompatConfig`, `AppConfig` — all used dataclass features without the decorator, causing `TypeError: X() takes no arguments` on first launch. Also fixed `self.ble.client` called as property when defined as method in three places.

Renamed `Wizpr-Suite` → `wizpr-tools` to signal different purpose: this is a workshop for protocol exploration, not a finished LLM assistant app. Future apps (iOS, MCP tools) are separate repos.
