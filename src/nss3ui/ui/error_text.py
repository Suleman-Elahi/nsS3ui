"""Concise user-facing error text formatting for UI surfaces."""
from __future__ import annotations


def short_error(message: str) -> str:
    msg = (message or "").strip()
    if not msg:
        return "Operation failed."

    low = msg.lower()
    if "accessdenied" in low or "not authorized to perform" in low:
        if "listbucket" in low:
            return "Access denied: missing permission `s3:ListBucket`."
        if "getobject" in low:
            return "Access denied: missing permission `s3:GetObject`."
        if "putobject" in low:
            return "Access denied: missing permission `s3:PutObject`."
        return "Access denied: your AWS identity lacks required permission."

    # Remove noisy boto3 wrapper prefix if present.
    marker = "when calling the"
    idx = low.find(marker)
    if idx != -1:
        tail = msg[idx:]
        # keep the most useful part after the service wrapper
        parts = tail.split(":", 1)
        if len(parts) == 2 and parts[1].strip():
            return parts[1].strip()

    first_line = msg.splitlines()[0].strip()
    return first_line if first_line else "Operation failed."

