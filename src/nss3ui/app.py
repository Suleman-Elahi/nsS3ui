"""Application bootstrap."""
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from nss3ui.ui.main_window import MainWindow


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("AWS S3 UI")
    app.setOrganizationName("nss3ui")
    app.setStyle("Fusion")

    # High-DPI support
    app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    window = MainWindow()
    window.show()
    return app.exec()
