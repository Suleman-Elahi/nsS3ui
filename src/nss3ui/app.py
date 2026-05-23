"""Application bootstrap."""

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from nss3ui.ui.main_window import MainWindow


def run() -> int:
    # Ensure Windows taskbar groups under this app identity.
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "nss3ui.desktop.app"
            )
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("nss3ui")
    app.setOrganizationName("nss3ui")
    app.setStyle("Fusion")

    # High-DPI support
    app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    icon_path = Path(__file__).resolve().parents[2] / "src" / "nssui.png"
    if icon_path.exists():
        app_icon = QIcon(str(icon_path))
        app.setWindowIcon(app_icon)

    window = MainWindow()
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()
    return app.exec()
