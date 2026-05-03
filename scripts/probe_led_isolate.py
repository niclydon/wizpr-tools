#!/usr/bin/env python3
"""
probe_led_isolate.py — figure out which BLE action triggers the LED flash.

A purple LED flash was observed during the early phase of probe_char2_followup.py,
before any probes ran. The flash happened somewhere in this chain:

    BleakClient.connect -> subscribe char7 -> subscribe char1 -> subscribe char5

This script walks each step one at a time with pauses and prompts, so the user
can watch the ring and tell us exactly which step lights it up.

The script also runs a second iteration without subscribing to char1, to verify
whether char1 (audio) subscription is what triggers the LED — which would mean
the LED is a hardware-driven "audio path armed" privacy indicator.

Usage:
    python scripts/probe_led_isolate.py
"""
from __future__ import annotations

import asyncio
import sys
from bleak import BleakClient, BleakScanner

CMD_CHAR        = "00000007-dc2e-4362-93d3-df429eb3ad10"
AUDIO_CHAR      = "00000001-dc2e-4362-93d3-df429eb3ad10"
MIC_STATE_CHAR  = "00000005-dc2e-4362-93d3-df429eb3ad10"

NOOP = lambda _h, _d: None


async def find_ring():
    print("Scanning for WIZPR RING...")
    device = await BleakScanner.find_device_by_filter(
        lambda d, _adv: (d.name or "").startswith("WIZPR RING"),
        timeout=10.0,
    )
    if not device:
        print("Not found. Make sure it's disconnected from the iPhone.")
        sys.exit(1)
    return device


async def run_iteration(device, label: str, subscribe_char1: bool):
    print(f"\n{'=' * 60}")
    print(f"Iteration: {label}")
    print(f"{'=' * 60}")
    print("Watch the ring carefully. You will be asked after each step")
    print("whether you saw the purple LED flash.")
    input("\nWatching? Press Enter to start the iteration...")

    results = {}

    print("\n[step 1] Opening BLE connection (no subscribes yet).")
    print("         Watch the ring NOW.")
    async with BleakClient(device) as client:
        await asyncio.sleep(1.5)
        results["1-connect"] = input("  LED flash during connect? (y/n): ").strip().lower()

        await asyncio.sleep(1.0)
        print("\n[step 2] Subscribing to char7 (command channel).")
        print("         Watch the ring NOW.")
        await client.start_notify(CMD_CHAR, NOOP)
        await asyncio.sleep(1.5)
        results["2-subscribe-char7"] = input("  LED flash during char7 subscribe? (y/n): ").strip().lower()

        if subscribe_char1:
            await asyncio.sleep(1.0)
            print("\n[step 3] Subscribing to char1 (audio stream).")
            print("         Watch the ring NOW.")
            await client.start_notify(AUDIO_CHAR, NOOP)
            await asyncio.sleep(1.5)
            results["3-subscribe-char1"] = input("  LED flash during char1 subscribe? (y/n): ").strip().lower()
        else:
            results["3-subscribe-char1"] = "skipped"

        await asyncio.sleep(1.0)
        print("\n[step 4] Subscribing to char5 (mic state bit).")
        print("         Watch the ring NOW.")
        await client.start_notify(MIC_STATE_CHAR, NOOP)
        await asyncio.sleep(1.5)
        results["4-subscribe-char5"] = input("  LED flash during char5 subscribe? (y/n): ").strip().lower()

        await asyncio.sleep(1.0)
        print("\n[step 5] Sending LOCK and disconnecting.")
        print("         Watch the ring NOW.")
        try:
            await client.write_gatt_char(CMD_CHAR, b"LOCK\r\n", response=False)
        except Exception:
            pass
        await asyncio.sleep(1.5)
        results["5-lock-and-disconnect"] = input("  LED flash during LOCK / disconnect? (y/n): ").strip().lower()

    return results


async def main():
    device = await find_ring()
    print(f"Found {device.name} ({device.address})")

    # Iteration 1: full normal flow (matches what the other probe scripts do)
    full = await run_iteration(device, "FULL (subscribe to all three notify chars)", subscribe_char1=True)

    print("\n\nGiving the ring a few seconds to settle before the next iteration...")
    await asyncio.sleep(3)

    # Iteration 2: skip char1
    no_audio = await run_iteration(device, "NO-CHAR1 (skip the audio subscription)", subscribe_char1=False)

    # Summary
    print(f"\n{'=' * 60}\nResults\n{'=' * 60}\n")
    rows = [
        ("Step", "Iteration 1 (full)", "Iteration 2 (no char1)"),
        ("-" * 32, "-" * 18, "-" * 22),
        ("1. Connect",                full["1-connect"],            no_audio["1-connect"]),
        ("2. Subscribe char7",        full["2-subscribe-char7"],    no_audio["2-subscribe-char7"]),
        ("3. Subscribe char1 (audio)", full["3-subscribe-char1"],   no_audio["3-subscribe-char1"]),
        ("4. Subscribe char5",        full["4-subscribe-char5"],    no_audio["4-subscribe-char5"]),
        ("5. LOCK + disconnect",      full["5-lock-and-disconnect"], no_audio["5-lock-and-disconnect"]),
    ]
    for row in rows:
        print(f"  {row[0]:<32}  {row[1]:<18}  {row[2]:<22}")

    # Interpretation
    print(f"\n{'-' * 60}\nInterpretation\n{'-' * 60}")
    flash_steps_full = [k for k, v in full.items() if v.startswith("y")]
    flash_steps_no_audio = [k for k, v in no_audio.items() if v.startswith("y")]

    if not flash_steps_full and not flash_steps_no_audio:
        print("No LED flashes observed in either iteration.")
        print("-> The earlier flash may have been a one-time event (e.g., post-LOCK reconnect).")
    elif flash_steps_full == ["3-subscribe-char1"] and not flash_steps_no_audio:
        print("LED fires ONLY when char1 (audio) is subscribed.")
        print("-> This is a privacy/recording indicator. Hardware-driven, probably not controllable.")
    elif flash_steps_full == ["1-connect"] and flash_steps_no_audio == ["1-connect"]:
        print("LED fires on every BLE connect, regardless of subscriptions.")
        print("-> Connection acknowledgment indicator. Hardware-driven, probably not controllable.")
    elif "5-lock-and-disconnect" in flash_steps_full or "5-lock-and-disconnect" in flash_steps_no_audio:
        print("LED fires on LOCK or disconnect.")
        print("-> Possibly a state-change indicator. Worth investigating which exact action causes it.")
    else:
        print("Mixed results. Compare the two columns above to narrow it down.")
        print(f"  Iteration 1 flashes: {flash_steps_full}")
        print(f"  Iteration 2 flashes: {flash_steps_no_audio}")


if __name__ == "__main__":
    asyncio.run(main())
