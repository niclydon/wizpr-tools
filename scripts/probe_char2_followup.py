#!/usr/bin/env python3
"""
probe_char2_followup.py — focused follow-up on the char 00000002 finding.

The initial probe campaign found that writing 200 bytes of 0xFF to char
00000002 produces a synthetic mic burst (MIC_ON, mic state on, one 224-byte
ADPCM frame on char1, MIC_OFF, mic state off) in 1.6ms wall-clock. This
script narrows that down with four phases:

  Phase A: length sweep at 0xFF — is 200 the magic length, or any sufficient size?
  Phase B: content variation at length 200 — is 0xFF special, or just length?
  Phase C: real-audio injection — does the ring loop our bytes back as audio?
  Phase D: streaming — can we trigger frames in rapid succession?

Most phases run in batch mode (response window is ~300ms, much faster than
the original 2s wait, since the response we found arrived in 1.6ms). Phase D
pauses for user observation since rapid writes might produce something
audible or tactile we want to catch.

At the end, prints an analysis comparing response audio frames across hits.
If all returned frames are IDENTICAL the ring is emitting a canned buffer.
If every frame is DIFFERENT the ring is processing our input — the bigger
finding, because that means char 00000002 is a phone-to-ring audio path.

Outputs ./probe_results/followup-YYYY-MM-DD-HH-MM-SS.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from bleak import BleakClient, BleakScanner

SVC = "00000000-dc2e-4362-93d3-df429eb3ad10"


def _char(short: str) -> str:
    return f"{short}-dc2e-4362-93d3-df429eb3ad10"


CMD_CHAR        = _char("00000007")
AUDIO_CHAR      = _char("00000001")
MIC_STATE_CHAR  = _char("00000005")
TARGET_CHAR     = _char("00000002")

CAPTURE_DIR = Path.home() / ".wizprsuite" / "captures"


def find_recent_audio_payload(min_bytes: int = 200) -> tuple[bytes, str] | None:
    """Pull the first sufficiently-long ADPCM payload from the most recent capture session."""
    if not CAPTURE_DIR.exists():
        return None
    sessions = sorted(CAPTURE_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for session_path in sessions:
        try:
            data = json.loads(session_path.read_text())
        except Exception:
            continue
        for cap in data.get("captures", []):
            for p in cap.get("payloads", []):
                uuid = (p.get("characteristic_uuid") or "").lower()
                if "00000001" in uuid:
                    raw = p.get("bytes")
                    if raw is None and p.get("hex"):
                        raw = list(bytes.fromhex(p["hex"]))
                    if not raw:
                        continue
                    payload = bytes(raw)
                    if len(payload) >= min_bytes:
                        return payload[:min_bytes], str(session_path.name)
    return None


def build_phases(audio_payload: bytes | None) -> list[tuple[str, list[tuple[str, bytes]]]]:
    phases: list[tuple[str, list[tuple[str, bytes]]]] = []

    # Phase A: length sweep at 0xFF
    lengths = [1, 50, 100, 150, 180, 190, 195, 199, 200, 201, 205, 210, 224, 250, 300]
    phases.append(("A length-sweep-0xFF",
                   [(f"len-{n}-0xFF", b"\xff" * n) for n in lengths]))

    # Phase B: content variation at length 200
    phases.append(("B content-variants-len-200", [
        ("len-200-0x00",          b"\x00" * 200),
        ("len-200-0x55",          b"\x55" * 200),
        ("len-200-0xAA",          b"\xaa" * 200),
        ("len-200-0x88",          b"\x88" * 200),
        ("len-200-incrementing",  bytes(i % 256 for i in range(200))),
        ("len-200-prng",          bytes((37 + i * 73) % 256 for i in range(200))),
    ]))

    # Phase C: real audio injection
    if audio_payload:
        phases.append(("C real-audio-injection", [
            ("len-200-real-adpcm", audio_payload),
        ]))

    return phases


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inter-probe-wait", type=float, default=0.4,
                    help="Seconds between probes (default 0.4)")
    ap.add_argument("--response-window", type=float, default=0.3,
                    help="Seconds to wait for response after each write (default 0.3)")
    ap.add_argument("--stream-count", type=int, default=10,
                    help="Number of rapid writes in streaming phase (default 10)")
    ap.add_argument("--stream-interval", type=float, default=0.05,
                    help="Seconds between streaming writes (default 0.05 = 20Hz)")
    ap.add_argument("--skip-streaming", action="store_true",
                    help="Skip Phase D (the rapid streaming test)")
    args = ap.parse_args()

    out_dir = Path("./probe_results")
    out_dir.mkdir(exist_ok=True)
    log_path = out_dir / f"followup-{datetime.now():%Y-%m-%d-%H-%M-%S}.jsonl"

    # Find a real ADPCM payload from a previous session for Phase C
    found = find_recent_audio_payload(200)
    audio_payload = None
    if found:
        audio_payload, source_name = found
        print(f"Phase C audio source: {source_name} — first 16 bytes: {audio_payload[:16].hex()}")
    else:
        print("Phase C: no captured session audio found in ~/.wizprsuite/captures/, skipping.")

    phases = build_phases(audio_payload)
    total_batch = sum(len(p) for _, p in phases)

    print(f"\nLogging to: {log_path}")
    print(f"Batch probes: {total_batch}")
    if not args.skip_streaming:
        print(f"Streaming:    {args.stream_count} writes at {1/args.stream_interval:.0f} Hz (Phase D)")
    print("")
    print("Wear the ring. Make sure it's disconnected from the iPhone.")
    input("Press Enter to scan and connect...")

    device = await BleakScanner.find_device_by_filter(
        lambda d, _adv: (d.name or "").startswith("WIZPR RING"),
        timeout=10.0,
    )
    if not device:
        print("WIZPR RING not found.")
        sys.exit(1)

    log_f = log_path.open("w")

    def log(record: dict):
        log_f.write(json.dumps(record) + "\n")
        log_f.flush()

    captured: list[dict] = []

    def make_handler(name: str):
        def handler(_h, data: bytearray):
            evt = {
                "ts": datetime.now().isoformat(),
                "char": name,
                "hex": bytes(data).hex(),
                "len": len(data),
            }
            try:
                ascii_value = bytes(data).decode("utf-8", errors="replace").strip("\x00\r\n ")
                if ascii_value and ascii_value.isprintable():
                    evt["ascii"] = ascii_value
            except Exception:
                pass
            captured.append(evt)
        return handler

    print(f"Connecting to {device.name} ({device.address})...")
    all_results: list[dict] = []
    streaming_record: dict | None = None

    async with BleakClient(device) as client:
        await client.start_notify(CMD_CHAR, make_handler("char7"))
        await client.start_notify(AUDIO_CHAR, make_handler("char1"))
        await client.start_notify(MIC_STATE_CHAR, make_handler("char5"))
        log({"event": "connected", "device": device.address, "ts": datetime.now().isoformat()})

        # Phases A, B, C: batch
        for phase_name, probes in phases:
            print(f"\n=== Phase {phase_name} ({len(probes)} probes) ===")
            for label, payload in probes:
                captured.clear()
                t0 = datetime.now()
                err = None
                try:
                    await client.write_gatt_char(TARGET_CHAR, payload, response=False)
                    await asyncio.sleep(args.response_window)
                except Exception as e:
                    err = repr(e)

                events = list(captured)
                record = {
                    "phase": phase_name,
                    "ts": t0.isoformat(),
                    "char": "00000002",
                    "probe": label,
                    "payload_hex": payload.hex(),
                    "payload_len": len(payload),
                    "events": events,
                    "write_error": err,
                }
                log(record)
                all_results.append(record)

                marker = "  [HIT]" if events else ""
                err_marker = f"  ERR: {err}" if err else ""
                print(f"  {label:30s} ({len(payload):3d}b) -> {len(events)} events{marker}{err_marker}")

                if not client.is_connected:
                    print("  Disconnected. Stopping batch phases.")
                    log({"event": "disconnected", "after": label, "ts": datetime.now().isoformat()})
                    break

                await asyncio.sleep(args.inter_probe_wait)
            else:
                continue
            break

        # Phase D: streaming
        if client.is_connected and not args.skip_streaming:
            print(f"\n=== Phase D streaming ({args.stream_count} writes of len-200-0xFF at {1/args.stream_interval:.0f}Hz) ===")
            print("This is the one phase where you might feel/hear something.")
            input("Press Enter to start the burst...")

            captured.clear()
            t0 = datetime.now()
            payload = b"\xff" * 200
            sent = 0
            for i in range(args.stream_count):
                try:
                    await client.write_gatt_char(TARGET_CHAR, payload, response=False)
                    sent += 1
                except Exception as e:
                    print(f"  write {i+1}/{args.stream_count} failed: {e!r}")
                    break
                await asyncio.sleep(args.stream_interval)

            # Catch trailing events
            await asyncio.sleep(1.0)
            stream_events = list(captured)

            user = input("  Felt/heard/saw anything during streaming? (n / y / notes): ").strip()

            streaming_record = {
                "phase": "D streaming",
                "ts": t0.isoformat(),
                "writes_sent": sent,
                "stream_interval": args.stream_interval,
                "events": stream_events,
                "user_feedback": user,
            }
            log(streaming_record)
            print(f"  Sent {sent} writes; received {len(stream_events)} events back.")

        if client.is_connected:
            try:
                await client.write_gatt_char(CMD_CHAR, b"LOCK\r\n", response=False)
            except Exception:
                pass

    log_f.close()

    # Analysis
    print(f"\n{'=' * 60}")
    print(f"Done. Results: {log_path}")
    print(f"{'=' * 60}\n")

    hits = [r for r in all_results if r["events"]]
    print(f"Batch hits: {len(hits)} of {len(all_results)} probes")
    if not hits:
        print("\nNothing in Phases A/B/C triggered events. The original 200-byte 0xFF finding")
        print("may not be reproducible, or this run hit a different ring state.")
    else:
        print("")
        for r in hits:
            audio_frames = [e for e in r["events"] if e["char"] == "char1"]
            print(f"  {r['phase']:32s} | {r['probe']:28s} | {len(r['events'])} events | {len(audio_frames)} audio frame(s)")

        # Compare audio frames across batch hits
        print(f"\n{'-' * 60}\nAudio frame comparison\n{'-' * 60}")
        frame_to_probes: dict[str, list[str]] = {}
        for r in hits:
            for e in r["events"]:
                if e["char"] == "char1":
                    frame_to_probes.setdefault(e["hex"], []).append(f"{r['probe']}")

        unique_frames = len(frame_to_probes)
        total_audio = sum(len(probes) for probes in frame_to_probes.values())

        if unique_frames == 0:
            print("No audio frames captured.")
        elif unique_frames == 1:
            print("All audio frames are IDENTICAL across hits.")
            print("-> The ring is emitting a CANNED frame, not processing our input.")
            print("-> char 00000002 is a trigger channel, not an audio injection path.")
        elif unique_frames == total_audio:
            print("Every audio frame is DIFFERENT across hits.")
            print("-> The ring is PROCESSING our input bytes through the audio pipeline.")
            print("-> char 00000002 looks like a phone-to-ring audio injection channel.")
            print("   (Whether anything plays through hardware is a separate question.)")
        else:
            print(f"{unique_frames} unique audio frames across {total_audio} responses.")
            print("-> Mixed result. Some inputs produce the same frame, some don't.")
            for h, probes in list(frame_to_probes.items())[:5]:
                print(f"  {h[:40]}... <- {len(probes)} probe(s): {probes}")

    if streaming_record:
        sr = streaming_record
        audio_frames = [e for e in sr["events"] if e["char"] == "char1"]
        print(f"\n{'-' * 60}\nStreaming\n{'-' * 60}")
        print(f"Sent: {sr['writes_sent']} writes  |  Received: {len(sr['events'])} events  |  Audio frames: {len(audio_frames)}")
        if sr.get("user_feedback") and sr["user_feedback"].lower() not in ("n", "no", ""):
            print(f"User reported: {sr['user_feedback']!r}")
        if audio_frames:
            unique_stream_frames = len({e["hex"] for e in audio_frames})
            if unique_stream_frames == 1 and len(audio_frames) > 1:
                print("All streaming frames identical -> ring throttles or emits canned frame regardless.")
            elif unique_stream_frames == len(audio_frames):
                print("All streaming frames distinct -> each write produces a fresh frame. Possibly streamable.")
            else:
                print(f"{unique_stream_frames} unique frames out of {len(audio_frames)} responses.")

    print(f"\nFor deeper review: jq -c 'select(.events | length > 0)' {log_path}")


if __name__ == "__main__":
    asyncio.run(main())
