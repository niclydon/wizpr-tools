from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


ACTIONS: list[dict[str, str]] = [
    {"id": "button_single", "label": "Single Button Press",       "prompt": "Press the ring button once"},
    {"id": "button_double", "label": "Double Button Press",       "prompt": "Press the ring button twice quickly"},
    {"id": "button_triple", "label": "Triple Button Press",       "prompt": "Press the ring button three times quickly"},
    {"id": "voice_short",   "label": "Short Voice Input",         "prompt": 'Speak a short word into the ring (say "Hello")'},
    {"id": "voice_long",    "label": "Long Voice Input",          "prompt": "Speak a full sentence into the ring"},
    {"id": "tilt_up",       "label": "Tilt Up (raise to speak)",  "prompt": "Raise your hand/ring up as if lifting to speak"},
    {"id": "rotate_cw",     "label": "Rotate Clockwise",          "prompt": "Rotate the ring clockwise on your finger"},
    {"id": "rotate_ccw",    "label": "Rotate Counter-Clockwise",  "prompt": "Rotate the ring counter-clockwise on your finger"},
    {"id": "tap_body",      "label": "Tap Ring Body",             "prompt": "Tap the ring body with your other finger"},
    {"id": "idle",          "label": "Idle Baseline",             "prompt": "Hold still — do nothing for 5 seconds"},
]

CAPTURE_DURATION_SECONDS = 5


@dataclass
class Payload:
    timestamp: str
    characteristic_uuid: str
    hex: str
    bytes_list: list[int]
    ascii: str


@dataclass
class ActionCapture:
    action_id: str
    action_label: str
    prompt: str
    captured_at: str
    duration_seconds: int
    payloads: list[Payload] = field(default_factory=list)
    skipped: bool = False


@dataclass
class CaptureSession:
    session_id: str
    device_name: str
    device_address: str
    gatt_map: list[dict[str, Any]] = field(default_factory=list)
    captures: list[ActionCapture] = field(default_factory=list)

    @staticmethod
    def new(device_name: str, device_address: str) -> "CaptureSession":
        now = datetime.now()
        return CaptureSession(
            session_id=now.strftime("%Y-%m-%dT%H:%M:%S"),
            device_name=device_name,
            device_address=device_address,
        )

    def add_payload(self, action_id: str, char_uuid: str, data: bytearray) -> None:
        capture = next((c for c in self.captures if c.action_id == action_id), None)
        if capture is None:
            return
        capture.payloads.append(Payload(
            timestamp=datetime.now().isoformat(),
            characteristic_uuid=char_uuid,
            hex=data.hex(),
            bytes_list=list(data),
            ascii=bytes(data).decode("utf-8", errors="replace"),
        ))

    def save(self, app_dir: Path) -> Path:
        out_dir = app_dir / "captures"
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = self.session_id.replace(":", "-").replace("T", "-") + ".json"
        path = out_dir / filename
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        # post-process bytes_list → bytes key for cleaner JSON
        raw = json.loads(path.read_text())
        for cap in raw.get("captures", []):
            for p in cap.get("payloads", []):
                p["bytes"] = p.pop("bytes_list", [])
        path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        return path
