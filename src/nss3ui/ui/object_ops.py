"""Dialogs and parsing helpers for object-level S3 operations."""
from __future__ import annotations

from typing import Optional
from PySide6.QtWidgets import QInputDialog, QMessageBox, QWidget

ACL_OPTIONS = (
    "private",
    "public-read",
    "public-read-write",
    "authenticated-read",
    "aws-exec-read",
    "bucket-owner-read",
    "bucket-owner-full-control",
)


def parse_tags(text: str) -> dict[str, str]:
    """
    Parse tags from lines in `key=value` format.
    Empty lines are ignored.
    """
    tags: dict[str, str] = {}
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "=" not in line:
            raise ValueError(f"Invalid tag line: {line!r}. Use key=value format.")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError("Tag key cannot be empty.")
        tags[key] = value
    return tags


def prompt_for_tags(parent: QWidget, bucket: str, key: str) -> Optional[dict[str, str]]:
    text, ok = QInputDialog.getMultiLineText(
        parent,
        "Set Object Tags",
        f"Tags for s3://{bucket}/{key}\n(one per line: key=value)",
        "",
    )
    if not ok:
        return None
    try:
        return parse_tags(text)
    except ValueError as exc:
        QMessageBox.warning(parent, "Invalid Tags", str(exc))
        return None


def prompt_for_acl(parent: QWidget, bucket: str, key: str) -> Optional[str]:
    value, ok = QInputDialog.getItem(
        parent,
        "Set Object ACL",
        f"ACL for s3://{bucket}/{key}",
        list(ACL_OPTIONS),
        0,
        False,
    )
    if not ok:
        return None
    return (value or "").strip() or None


def prompt_for_destination_prefix(
    parent: QWidget, bucket: str, source_prefix: str
) -> Optional[str]:
    text, ok = QInputDialog.getText(
        parent,
        "Rename/Move Folder",
        (
            f"Move folder in s3://{bucket}\n"
            "Enter destination prefix (bucket-relative), e.g. path/new-folder/"
        ),
        text=source_prefix,
    )
    if not ok:
        return None
    dst = (text or "").strip().lstrip("/")
    if not dst:
        return None
    if not dst.endswith("/"):
        dst += "/"
    return dst

