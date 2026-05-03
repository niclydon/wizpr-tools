from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from PySide6 import QtWidgets
from qasync import QEventLoop

from ..core.config import get_default_app_dir
from ..core.logging_setup import setup_logging, get_logger
from ..ui.capture_window import CaptureWindow

logger = get_logger("wizpr_suite")


def main() -> int:
    app_dir = get_default_app_dir()
    setup_logging(app_dir)

    app = QtWidgets.QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    win = CaptureWindow(app_dir=app_dir)
    win.show()

    with loop:
        return loop.run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
