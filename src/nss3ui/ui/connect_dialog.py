"""Connection / profile dialog — auto-loads last saved connection."""
from __future__ import annotations
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QPushButton,
    QTabWidget, QWidget, QDialogButtonBox
)
from PySide6.QtCore import Qt
from nss3ui.credentials import list_profiles
from nss3ui.config import load_credentials, save_credentials


class ConnectDialog(QDialog):
    """Dialog to configure S3 connection. Remembers last-used settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Connect to S3")
        self.setMinimumWidth(440)
        self.setModal(True)
        self._setup_ui()
        self._load_saved()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        tabs = QTabWidget()

        # --- Profile tab ---
        profile_tab = QWidget()
        pf_layout = QFormLayout(profile_tab)
        pf_layout.setSpacing(10)

        self._profile_combo = QComboBox()
        profiles = list_profiles()
        if not profiles:
            profiles = ["default"]
        self._profile_combo.addItems(profiles)
        pf_layout.addRow("AWS Profile:", self._profile_combo)

        self._region_edit = QLineEdit("us-east-1")
        pf_layout.addRow("Region:", self._region_edit)

        self._endpoint_edit = QLineEdit()
        self._endpoint_edit.setPlaceholderText("https://… (leave blank for AWS)")
        pf_layout.addRow("Endpoint URL:", self._endpoint_edit)

        tabs.addTab(profile_tab, "AWS Profile")

        # --- Keys tab ---
        keys_tab = QWidget()
        k_layout = QFormLayout(keys_tab)
        k_layout.setSpacing(10)

        self._access_key_edit = QLineEdit()
        self._access_key_edit.setPlaceholderText("AKIA…")
        k_layout.addRow("Access Key ID:", self._access_key_edit)

        self._secret_key_edit = QLineEdit()
        self._secret_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        k_layout.addRow("Secret Access Key:", self._secret_key_edit)

        self._session_token_edit = QLineEdit()
        self._session_token_edit.setPlaceholderText("Optional")
        k_layout.addRow("Session Token:", self._session_token_edit)

        self._keys_region_edit = QLineEdit("us-east-1")
        k_layout.addRow("Region:", self._keys_region_edit)

        self._keys_endpoint_edit = QLineEdit()
        self._keys_endpoint_edit.setPlaceholderText("https://… (leave blank for AWS)")
        k_layout.addRow("Endpoint URL:", self._keys_endpoint_edit)

        tabs.addTab(keys_tab, "Access Keys")

        layout.addWidget(tabs)
        self._tabs = tabs

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_saved(self) -> None:
        """Pre-fill fields from last saved connection."""
        saved = load_credentials()
        if not saved:
            return
        mode = saved.get("mode", "profile")
        if mode == "profile":
            self._tabs.setCurrentIndex(0)
            profile = saved.get("profile", "")
            idx = self._profile_combo.findText(profile)
            if idx >= 0:
                self._profile_combo.setCurrentIndex(idx)
            self._region_edit.setText(saved.get("region", "us-east-1"))
            self._endpoint_edit.setText(saved.get("endpoint_url") or "")
        else:
            self._tabs.setCurrentIndex(1)
            self._access_key_edit.setText(saved.get("access_key", ""))
            self._secret_key_edit.setText(saved.get("secret_key", ""))
            self._session_token_edit.setText(saved.get("session_token") or "")
            self._keys_region_edit.setText(saved.get("region", "us-east-1"))
            self._keys_endpoint_edit.setText(saved.get("endpoint_url") or "")

    def accept(self) -> None:
        """Save config before closing."""
        cfg = self.get_config()
        save_credentials(cfg)
        super().accept()

    def get_config(self) -> dict:
        """Return connection config dict."""
        tab = self._tabs.currentIndex()
        if tab == 0:
            return {
                "mode": "profile",
                "profile": self._profile_combo.currentText(),
                "region": self._region_edit.text().strip() or "us-east-1",
                "endpoint_url": self._endpoint_edit.text().strip() or None,
            }
        else:
            return {
                "mode": "keys",
                "access_key": self._access_key_edit.text().strip(),
                "secret_key": self._secret_key_edit.text().strip(),
                "session_token": self._session_token_edit.text().strip() or None,
                "region": self._keys_region_edit.text().strip() or "us-east-1",
                "endpoint_url": self._keys_endpoint_edit.text().strip() or None,
            }


class PresignDialog(QDialog):
    """Ask for expiry time before generating a presigned URL."""

    def __init__(self, filename: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generate Presigned URL")
        self.setMinimumWidth(340)
        self.setModal(True)
        self._setup_ui(filename)

    def _setup_ui(self, filename: str) -> None:
        from PySide6.QtWidgets import QSpinBox
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        info = QLabel(f"<b>{filename}</b>")
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        form.setSpacing(10)

        self._expires_spin = QSpinBox()
        self._expires_spin.setRange(60, 604800)   # 1 min → 7 days
        self._expires_spin.setValue(3600)
        self._expires_spin.setSingleStep(300)
        self._expires_spin.setSuffix(" sec")
        self._expires_spin.setToolTip("3600 = 1 hour, 86400 = 1 day, 604800 = 7 days")
        form.addRow("Expires in:", self._expires_spin)

        # Quick presets
        presets_widget = QWidget()
        presets_layout = QHBoxLayout(presets_widget)
        presets_layout.setContentsMargins(0, 0, 0, 0)
        presets_layout.setSpacing(6)
        for label, secs in [("15 min", 900), ("1 hr", 3600), ("1 day", 86400), ("7 days", 604800)]:
            btn = QPushButton(label)
            btn.setFixedHeight(24)
            btn.setProperty("flat", True)
            btn.clicked.connect(lambda _, s=secs: self._expires_spin.setValue(s))
            presets_layout.addWidget(btn)
        form.addRow("Presets:", presets_widget)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def expires_in(self) -> int:
        return self._expires_spin.value()
