"""
Persistent app configuration stored in ~/.config/nss3ui/config.json
Saves: last connection, theme preference, window state.
"""
from __future__ import annotations
import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

_CONFIG_DIR = Path.home() / ".config" / "nss3ui"
_CONFIG_FILE = _CONFIG_DIR / "config.json"
_CREDS_FILE = _CONFIG_DIR / "credentials.json"


def _ensure_dir() -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------
# Generic config
# ------------------------------------------------------------------

def load_config() -> dict:
    try:
        if _CONFIG_FILE.exists():
            return json.loads(_CONFIG_FILE.read_text())
    except Exception as exc:
        log.warning("Could not load config: %s", exc)
    return {}


def save_config(data: dict) -> None:
    try:
        _ensure_dir()
        _CONFIG_FILE.write_text(json.dumps(data, indent=2))
    except Exception as exc:
        log.warning("Could not save config: %s", exc)


def get(key: str, default: Any = None) -> Any:
    return load_config().get(key, default)


def set_value(key: str, value: Any) -> None:
    cfg = load_config()
    cfg[key] = value
    save_config(cfg)


# ------------------------------------------------------------------
# Saved credentials (stored in separate file, not keyring)
# ------------------------------------------------------------------

def save_credentials(creds: dict) -> None:
    """Save last-used connection config."""
    try:
        _ensure_dir()
        _CREDS_FILE.write_text(json.dumps(creds, indent=2))
    except Exception as exc:
        log.warning("Could not save credentials: %s", exc)


def load_credentials() -> Optional[dict]:
    try:
        if _CREDS_FILE.exists():
            return json.loads(_CREDS_FILE.read_text())
    except Exception as exc:
        log.warning("Could not load credentials: %s", exc)
    return None


# ------------------------------------------------------------------
# Theme
# ------------------------------------------------------------------

def get_theme() -> str:
    """Return 'dark' or 'light'."""
    return get("theme", "dark")


def set_theme(theme: str) -> None:
    set_value("theme", theme)


# ------------------------------------------------------------------
# Transfer tuning
# ------------------------------------------------------------------

def get_transfer_tuning() -> dict:
    defaults = {
        "max_concurrency": 8,
        "multipart_chunksize_mb": 16,
        "multipart_threshold_mb": 16,
    }
    cfg = get("transfer_tuning", {}) or {}
    out = dict(defaults)
    out.update({k: v for k, v in cfg.items() if k in defaults})
    return out


def set_transfer_tuning(values: dict) -> None:
    set_value("transfer_tuning", values)
