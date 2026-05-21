"""Icon helpers — uses Qt standard icons + emoji fallbacks."""
from PySide6.QtWidgets import QApplication, QStyle
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtCore import Qt, QSize


def _std(name: str) -> QIcon:
    style = QApplication.style()
    return style.standardIcon(getattr(QStyle.StandardPixmap, name))


def icon_bucket() -> QIcon:
    return _make_text_icon("🪣", "#f0a500")


def icon_folder() -> QIcon:
    return _make_text_icon("📁", "#dcb67a")


def icon_file() -> QIcon:
    return _make_text_icon("📄", "#9d9d9d")


def icon_image() -> QIcon:
    return _make_text_icon("🖼", "#89d185")


def icon_upload() -> QIcon:
    return _make_text_icon("⬆", "#4ec9b0")


def icon_download() -> QIcon:
    return _make_text_icon("⬇", "#4ec9b0")


def icon_delete() -> QIcon:
    return _make_text_icon("🗑", "#f48771")


def icon_refresh() -> QIcon:
    return _make_text_icon("↻", "#9cdcfe")


def icon_new_folder() -> QIcon:
    return _make_text_icon("📂+", "#dcb67a")


def icon_copy_link() -> QIcon:
    return _make_text_icon("🔗", "#9cdcfe")


def icon_account() -> QIcon:
    return _make_text_icon("👤", "#c586c0")


def _make_text_icon(text: str, color: str = "#d4d4d4", size: int = 20) -> QIcon:
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    painter = QPainter(px)
    font = QFont()
    font.setPixelSize(size - 2)
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return QIcon(px)


def file_icon(key: str) -> QIcon:
    """Return an icon based on file extension."""
    ext = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    image_exts = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "svg", "tiff", "ico"}
    text_exts = {"txt", "md", "rst", "log", "csv", "json", "yaml", "yml", "xml", "toml", "ini", "cfg"}
    if ext in image_exts:
        return icon_image()
    if ext in text_exts:
        return icon_file()
    return icon_file()
