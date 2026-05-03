from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6 import QtWidgets, QtCore, QtGui

from ..ble.ble_manager import BLEManager
from ..ble.ring_controller import RingController, RingProfile
from ..capture.session import ACTIONS, CAPTURE_DURATION_SECONDS, ActionCapture, CaptureSession
from ..core.event_bus import EventBus
from ..core.logging_setup import get_logger

logger = get_logger("wizpr_suite.ui")


class CaptureWindow(QtWidgets.QMainWindow):
    _status_signal = QtCore.Signal(str)
    _page_signal = QtCore.Signal(int)
    _payload_signal = QtCore.Signal(str, str)  # char_uuid, hex
    _done_signal = QtCore.Signal(str)           # saved file path

    def __init__(self, app_dir: Path) -> None:
        super().__init__()
        self.app_dir = app_dir
        self.setWindowTitle("WIZPR Ring Capture")
        self.resize(680, 520)

        self._ble = BLEManager()
        self._bus = EventBus()
        self._ring = RingController(self._ble, self._bus, RingProfile())
        self._session: CaptureSession | None = None
        self._action_index: int = 0
        self._capturing: bool = False
        self._current_action_id: str = ""
        self._countdown_timer = QtCore.QTimer(self)
        self._countdown_remaining: int = 0

        self._build_ui()
        self._connect_signals()

    # ── UI construction ────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._stack = QtWidgets.QStackedWidget()
        self.setCentralWidget(self._stack)
        self._stack.addWidget(self._make_connecting_page())   # 0
        self._stack.addWidget(self._make_discovering_page())  # 1
        self._stack.addWidget(self._make_capture_page())      # 2
        self._stack.addWidget(self._make_done_page())         # 3
        self._stack.addWidget(self._make_explorer_page())     # 4
        self._apply_style()

    def _make_connecting_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._connect_status = QtWidgets.QLabel("Scanning for WIZPR RING...")
        self._connect_status.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._connect_status.setStyleSheet("font-size: 18px;")
        self._connect_status.setWordWrap(True)
        layout.addWidget(self._connect_status)
        self._btn_rescan = QtWidgets.QPushButton("Scan Again")
        self._btn_rescan.setVisible(False)
        self._btn_rescan.clicked.connect(self._rescan)
        layout.addWidget(self._btn_rescan, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        return page

    def _make_discovering_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        lbl = QtWidgets.QLabel("Discovering ring capabilities...")
        lbl.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("font-size: 18px;")
        layout.addWidget(lbl)
        return page

    def _make_capture_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        self._progress_label = QtWidgets.QLabel("Action 1 of 15")
        self._progress_label.setStyleSheet("font-size: 12px; color: #888;")
        layout.addWidget(self._progress_label)

        self._action_label = QtWidgets.QLabel("")
        self._action_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        self._action_label.setWordWrap(True)
        layout.addWidget(self._action_label)

        self._prompt_label = QtWidgets.QLabel("")
        self._prompt_label.setStyleSheet("font-size: 15px; color: #ccc;")
        self._prompt_label.setWordWrap(True)
        layout.addWidget(self._prompt_label)

        self._countdown_bar = QtWidgets.QProgressBar()
        self._countdown_bar.setRange(0, CAPTURE_DURATION_SECONDS * 10)
        self._countdown_bar.setValue(0)
        self._countdown_bar.setTextVisible(False)
        self._countdown_bar.setFixedHeight(12)
        layout.addWidget(self._countdown_bar)

        self._countdown_label = QtWidgets.QLabel("")
        self._countdown_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._countdown_label)

        self._payload_list = QtWidgets.QListWidget()
        self._payload_list.setStyleSheet("font-family: monospace; font-size: 11px;")
        layout.addWidget(self._payload_list)

        btn_row = QtWidgets.QHBoxLayout()
        self._btn_capture = QtWidgets.QPushButton("▶  Start Capture")
        self._btn_skip    = QtWidgets.QPushButton("Skip")
        self._btn_repeat  = QtWidgets.QPushButton("Repeat")
        self._btn_next    = QtWidgets.QPushButton("Next →")
        self._btn_next.setEnabled(False)
        self._btn_repeat.setEnabled(False)
        for btn in (self._btn_capture, self._btn_skip, self._btn_repeat, self._btn_next):
            btn_row.addWidget(btn)
        layout.addLayout(btn_row)

        return page

    def _make_done_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._done_label = QtWidgets.QLabel("Session complete!")
        self._done_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._done_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        self._done_path = QtWidgets.QLabel("")
        self._done_path.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._done_path.setStyleSheet("font-size: 12px; color: #aaa;")
        self._done_path.setWordWrap(True)
        btn_explore = QtWidgets.QPushButton("Explore Commands →")
        btn_explore.clicked.connect(lambda: self._stack.setCurrentIndex(4))
        layout.addWidget(self._done_label)
        layout.addWidget(self._done_path)
        layout.addSpacing(20)
        layout.addWidget(btn_explore)
        return page

    def _make_explorer_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        lbl = QtWidgets.QLabel("Command Explorer")
        lbl.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(lbl)

        sub = QtWidgets.QLabel("Send ASCII commands to the ring and watch responses.\nChar 00000007 is the main command channel.")
        sub.setStyleSheet("font-size: 12px; color: #888;")
        sub.setWordWrap(True)
        layout.addWidget(sub)

        # Quick command buttons
        quick_label = QtWidgets.QLabel("Quick commands:")
        quick_label.setStyleSheet("font-size: 12px; color: #aaa;")
        layout.addWidget(quick_label)
        quick_row = QtWidgets.QHBoxLayout()
        for cmd in ["MIC_OFF", "MIC_ON", "STATUS", "PING", "RESET"]:
            btn = QtWidgets.QPushButton(cmd)
            btn.clicked.connect(lambda checked, c=cmd: self._send_command(c))
            quick_row.addWidget(btn)
        layout.addLayout(quick_row)

        # Custom command input
        input_row = QtWidgets.QHBoxLayout()
        self._cmd_input = QtWidgets.QLineEdit()
        self._cmd_input.setPlaceholderText("Type a command and press Send...")
        self._cmd_input.returnPressed.connect(self._send_custom_command)
        self._cmd_input.setStyleSheet("background: #181825; border: 1px solid #45475a; border-radius: 4px; padding: 6px; font-family: monospace;")
        self._btn_send = QtWidgets.QPushButton("Send")
        self._btn_send.clicked.connect(self._send_custom_command)
        input_row.addWidget(self._cmd_input)
        input_row.addWidget(self._btn_send)
        layout.addLayout(input_row)

        # Response log
        self._explorer_log = QtWidgets.QListWidget()
        self._explorer_log.setStyleSheet("font-family: monospace; font-size: 11px; background: #181825; border: 1px solid #313244;")
        layout.addWidget(self._explorer_log)

        btn_back = QtWidgets.QPushButton("← Back")
        btn_back.clicked.connect(lambda: self._stack.setCurrentIndex(3))
        layout.addWidget(btn_back)

        return page

    def _apply_style(self) -> None:
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #1e1e2e; color: #cdd6f4; }
            QPushButton {
                background: #313244; border: 1px solid #45475a;
                border-radius: 6px; padding: 8px 18px; font-size: 13px;
            }
            QPushButton:hover { background: #45475a; }
            QPushButton:disabled { color: #585b70; }
            QProgressBar { background: #313244; border-radius: 6px; }
            QProgressBar::chunk { background: #89b4fa; border-radius: 6px; }
            QListWidget { background: #181825; border: 1px solid #313244; border-radius: 6px; }
        """)

    # ── Signal wiring ──────────────────────────────────────────────────

    _explorer_signal = QtCore.Signal(str, str)  # direction (→/←), text

    def _connect_signals(self) -> None:
        self._status_signal.connect(self._connect_status.setText)
        self._page_signal.connect(self._stack.setCurrentIndex)
        self._payload_signal.connect(self._on_payload_received)
        self._done_signal.connect(self._on_session_done)
        self._explorer_signal.connect(self._on_explorer_event)

        self._btn_capture.clicked.connect(self._start_capture)
        self._btn_skip.clicked.connect(self._skip_action)
        self._btn_repeat.clicked.connect(self._repeat_action)
        self._btn_next.clicked.connect(self._next_action)
        self._countdown_timer.timeout.connect(self._tick_countdown)

    # ── Lifecycle ──────────────────────────────────────────────────────

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        asyncio.ensure_future(self._run_connect())

    def _rescan(self) -> None:
        self._btn_rescan.setVisible(False)
        asyncio.ensure_future(self._run_connect())

    async def _run_connect(self) -> None:
        try:
            self._status_signal.emit("Scanning for WIZPR RING...")
            devs = await self._ble.scan(seconds=8.0)
            if not devs:
                self._status_signal.emit(
                    "No WIZPR RING found.\n\nDisconnect it from your iPhone first,\nthen tap Scan Again."
                )
                self._btn_rescan.setVisible(True)
                return
            dev = devs[0]
            self._status_signal.emit(f"Found {dev.name}\nConnecting...")
            await self._ble.connect(dev.address)
            self._ring.profile.address = dev.address
            self._session = CaptureSession.new(dev.name, dev.address)
            self._page_signal.emit(1)
            await self._run_discover()
        except Exception as e:
            self._status_signal.emit(f"Error: {e}\n\nRestart the app to try again.")
            logger.exception("Connection failed")

    async def _run_discover(self) -> None:
        try:
            gatt = await self._ring.gatt_summary()
            device_info = await self._ring.read_device_info()
            if self._session:
                self._session.gatt_map = gatt
                self._session.device_info = device_info

            def _on_notify(char_uuid: str, data: bytearray) -> None:
                if self._capturing:
                    self._payload_signal.emit(char_uuid, data.hex())
                # always feed explorer
                try:
                    txt = data.decode("utf-8").strip()
                except Exception:
                    txt = data.hex()
                self._explorer_signal.emit("←", f"{char_uuid[-8:]}  {txt}")

            await self._ring.subscribe_all(_on_notify)
            self._page_signal.emit(2)
            self._load_action(0)
        except Exception as e:
            logger.exception("Discovery failed: %s", e)

    # ── Capture flow ───────────────────────────────────────────────────

    def _load_action(self, index: int) -> None:
        self._action_index = index
        self._capturing = False
        self._payload_list.clear()
        self._btn_capture.setEnabled(True)
        self._btn_skip.setEnabled(True)
        self._btn_next.setEnabled(False)
        self._btn_repeat.setEnabled(False)
        self._countdown_bar.setValue(0)
        self._countdown_label.setText("")

        action = ACTIONS[index]
        self._current_action_id = action["id"]
        self._progress_label.setText(f"Action {index + 1} of {len(ACTIONS)}")
        self._action_label.setText(action["label"])
        self._prompt_label.setText(action["prompt"])

        if self._session is not None:
            self._session.captures.append(ActionCapture(
                action_id=action["id"],
                action_label=action["label"],
                prompt=action["prompt"],
                captured_at=datetime.now().isoformat(),
                duration_seconds=CAPTURE_DURATION_SECONDS,
            ))

    def _start_capture(self) -> None:
        self._capturing = True
        self._btn_capture.setEnabled(False)
        self._btn_skip.setEnabled(False)
        self._countdown_remaining = CAPTURE_DURATION_SECONDS * 10
        self._countdown_bar.setValue(self._countdown_remaining)
        self._countdown_timer.start(100)

    def _tick_countdown(self) -> None:
        self._countdown_remaining -= 1
        self._countdown_bar.setValue(self._countdown_remaining)
        secs = self._countdown_remaining / 10
        self._countdown_label.setText(f"{secs:.1f}s remaining")
        if self._countdown_remaining <= 0:
            self._countdown_timer.stop()
            self._capturing = False
            self._btn_next.setEnabled(True)
            self._btn_repeat.setEnabled(True)
            self._btn_skip.setEnabled(True)
            self._countdown_label.setText("Done — press Next or Repeat")

    def _on_payload_received(self, char_uuid: str, hex_data: str) -> None:
        if self._session:
            self._session.add_payload(
                self._current_action_id, char_uuid, bytearray.fromhex(hex_data)
            )
        self._payload_list.addItem(f"{char_uuid[-8:]}  {hex_data}")
        self._payload_list.scrollToBottom()

    def _skip_action(self) -> None:
        if self._session and self._session.captures:
            self._session.captures[-1].skipped = True
        self._advance()

    def _repeat_action(self) -> None:
        if self._session and self._session.captures:
            self._session.captures.pop()
        self._load_action(self._action_index)

    def _next_action(self) -> None:
        self._advance()

    def _advance(self) -> None:
        next_index = self._action_index + 1
        if next_index >= len(ACTIONS):
            self._finish_session()
        else:
            self._load_action(next_index)

    def _finish_session(self) -> None:
        if self._session:
            path = self._session.save(self.app_dir)
            self._done_signal.emit(str(path))
        self._page_signal.emit(3)

    def _on_session_done(self, path: str) -> None:
        self._done_path.setText(f"Saved to:\n{path}")

    # ── Command explorer ───────────────────────────────────────────────

    COMMAND_CHAR = "00000007-dc2e-4362-93d3-df429eb3ad10"

    def _send_command(self, cmd: str) -> None:
        asyncio.ensure_future(self._do_send_command(cmd))

    def _send_custom_command(self) -> None:
        cmd = self._cmd_input.text().strip()
        if cmd:
            self._cmd_input.clear()
            self._send_command(cmd)

    async def _do_send_command(self, cmd: str) -> None:
        try:
            await self._ring.write_command(self.COMMAND_CHAR, cmd)
            self._explorer_signal.emit("→", f"SENT: {cmd}")
        except Exception as e:
            self._explorer_signal.emit("!", f"ERROR: {e}")

    def _on_explorer_event(self, direction: str, text: str) -> None:
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        color = "#89b4fa" if direction == "→" else "#a6e3a1" if direction == "←" else "#f38ba8"
        item = QtWidgets.QListWidgetItem(f"{ts}  {direction}  {text}")
        item.setForeground(QtGui.QColor(color))
        self._explorer_log.addItem(item)
        self._explorer_log.scrollToBottom()
