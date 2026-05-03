# Quickstart: Talk to the WIZPR Ring from your own code

The minimum viable Python: connect to the ring, listen for events, decode audio to a WAV file.

If you just want to capture sessions through a UI, run the wizpr-suite app instead (`python -m wizpr-suite.app.main`). This doc is for people building something on top of the ring.

---

## Prerequisites

- macOS (CoreBluetooth backend; Linux/Windows BLE stacks are untested with this device)
- Python 3.11+
- Ring disconnected from your iPhone (the ring only advertises when no client is connected)
- Bluetooth enabled, your terminal has Bluetooth permission (System Settings > Privacy & Security > Bluetooth)

```bash
pip install bleak
```

---

## Minimum viable client (~50 lines)

```python
import asyncio
import audioop
import wave
from bleak import BleakScanner, BleakClient

CMD_CHAR  = "00000007-dc2e-4362-93d3-df429eb3ad10"   # ASCII events / commands
AUDIO_CHAR = "00000001-dc2e-4362-93d3-df429eb3ad10"  # IMA ADPCM 16kHz mono

async def main():
    print("scanning for WIZPR RING...")
    device = await BleakScanner.find_device_by_filter(
        lambda d, _adv: (d.name or "").startswith("WIZPR RING"),
        timeout=10.0,
    )
    if not device:
        raise SystemExit("WIZPR RING not found. Is it disconnected from your iPhone?")

    print(f"connecting to {device.name} ({device.address})")
    async with BleakClient(device) as client:
        adpcm_state = (0, 0)   # ADPCM predictor + step index, continuous across packets
        pcm_chunks: list[bytes] = []
        recording = False

        def on_event(_handle, data: bytearray):
            nonlocal recording, adpcm_state, pcm_chunks
            text = bytes(data).decode("utf-8", errors="replace").strip()
            print(f"event: {text}")
            if text == "MIC_ON":
                adpcm_state = (0, 0)
                pcm_chunks = []
                recording = True
            elif text == "MIC_OFF" and recording:
                recording = False
                pcm = b"".join(pcm_chunks)
                with wave.open("out.wav", "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
                    w.writeframes(pcm)
                print(f"saved out.wav ({len(pcm)} bytes PCM)")

        def on_audio(_handle, data: bytearray):
            nonlocal adpcm_state, pcm_chunks
            if not recording:
                return
            pcm, adpcm_state = audioop.adpcm2lin(bytes(data), 2, adpcm_state)
            pcm_chunks.append(pcm)

        await client.start_notify(CMD_CHAR, on_event)
        await client.start_notify(AUDIO_CHAR, on_audio)

        # Optional: query battery and firmware version
        await client.write_gatt_char(CMD_CHAR, b"BATTERY\r\n", response=False)

        print("connected. raise the ring and speak, or press the button. Ctrl-C to exit.")
        try:
            await asyncio.Event().wait()
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
        finally:
            await client.write_gatt_char(CMD_CHAR, b"LOCK\r\n", response=False)
            print("sent LOCK on the way out")

if __name__ == "__main__":
    asyncio.run(main())
```

Save as `quickstart.py` and run. Raise the ring to your face and speak; on `MIC_OFF` it writes the captured audio to `out.wav` in your current directory.

---

## What to do next

- **Stream to STT.** Replace the WAV-write block with a streaming transcription client (Whisper, OpenAI realtime, Deepgram). The PCM you have is exactly what those APIs want: 16-bit signed LE, 16 kHz, mono.
- **Hand off via MQTT/WebSocket/MCP.** The decoded PCM (or the original ADPCM if you want to keep bandwidth low) can be pushed to whatever inference layer you're running. The ring side is a 60-line Python program; everything interesting happens downstream.
- **Persistent connection.** Use `scripts/ring_daemon.py` as a starting point if you need a long-lived process holding the ring's connection while other code talks to it via FIFO/HTTP/whatever.

---

## Common gotchas

- **Ring not advertising.** If you have an iPhone with the official Wizpr app open in the background, the ring is connected to it and won't advertise. Quit the app or turn off Bluetooth on the phone.
- **macOS Bluetooth permission denied.** Processes launched over SSH don't inherit Bluetooth permission on macOS. Run from a Terminal window inside an active GUI session.
- **No audio output.** If your WAV file is silent or noise, you almost certainly reset the ADPCM state per-packet. State must carry across all packets in the session.

For a deeper dive on the codec, see [`audio_protocol.md`](audio_protocol.md). For the full protocol reference, see [`protocol.md`](protocol.md). For the things that took us hours to figure out and you shouldn't have to, see [`hardware-notes.md`](hardware-notes.md).
