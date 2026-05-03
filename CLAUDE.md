# wizpr-tools

Protocol exploration and reverse-engineering toolkit for the WIZPR Ring.

@../../DOCUMENTARY_STYLE_DOCUMENTATION.md

---

## Project state

**What this is:** A workshop repo for mapping the WIZPR Ring's undocumented BLE protocol. Not an app — a set of tools for capturing, probing, and understanding ring behavior. Future iOS app, MCP tools, and AI integrations are separate repos.

**Protocol status:** Mapped. See `docs/protocol.md` for the full reference.

**Platform:** macOS (Bluetooth via CoreBluetooth / bleak). The ring discovery and capture tools require macOS.

---

## Stack

- Python 3.11 (via pyenv at `~/.pyenv/versions/3.11.9`)
- bleak 3.0.1 (BLE, CoreBluetooth backend on macOS)
- PySide6 6.11.0 (capture UI)
- qasync 0.27+ (asyncio ↔ Qt event loop bridge)
- fastapi / uvicorn (optional remote server, not used currently)

---

## Key files

| Path | Purpose |
|---|---|
| `wizpr-suite/ble/ble_manager.py` | BLE scan, connect, disconnect |
| `wizpr-suite/ble/ring_controller.py` | GATT summary, subscribe_all, write_command |
| `wizpr-suite/capture/session.py` | CaptureSession dataclass, action list, JSON serializer |
| `wizpr-suite/ui/capture_window.py` | PySide6 guided capture UI |
| `wizpr-suite/app/main.py` | Entry point (qasync event loop) |
| `scripts/ring_daemon.py` | Persistent ring connection shell (FIFO interface) |
| `docs/protocol.md` | Complete protocol reference |
| `docs/explorations/2026-05-ring-protocol-discovery.md` | Discovery journal |
| `CHANGES.md` | Decision log |

---

## Running the capture tool

```bash
# MacBook — ring must be disconnected from iPhone first
cd ~/wizpr_tools
source .venv/bin/activate
python -m wizpr-suite.app.main
```

---

## Running the ring daemon (interactive probing)

```bash
# MacBook — launch via GUI session for Bluetooth permission
python scripts/ring_daemon.py

# From any terminal (SSH or local):
echo "write 7 BATTERY" > /tmp/ring.cmd
tail -f /tmp/ring.log
```

---

## Capture output

Session JSON files land at `~/.wizprsuite/captures/YYYY-MM-DD-HH-MM-SS.json` on the machine running the app.

---

## What's still open

- Audio codec on char1 (binary stream, format unidentified — likely ADPCM or Silicon Labs proprietary)
- Write-only chars `00000002`, `00000003`, `00000004`, `00000006` — purpose unknown, not blocking
- `LOCK` command semantics — confirmed it's sent on session end, haven't verified what exactly it disables
