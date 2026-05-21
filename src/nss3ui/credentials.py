"""Credential management: AWS profiles + manual key storage via keyring."""
from __future__ import annotations
import logging
from typing import Optional
import boto3
from botocore.exceptions import ProfileNotFound

log = logging.getLogger(__name__)


def list_profiles() -> list[str]:
    """Return all configured AWS profile names."""
    try:
        session = boto3.Session()
        return session.available_profiles
    except Exception as exc:
        log.warning("Could not list profiles: %s", exc)
        return ["default"]


def profile_exists(profile: str) -> bool:
    try:
        boto3.Session(profile_name=profile)
        return True
    except ProfileNotFound:
        return False


def save_keys(profile: str, access_key: str, secret_key: str) -> None:
    """Persist access/secret key pair in OS keychain under profile name."""
    try:
        import keyring
        keyring.set_password("nss3ui", f"{profile}:access_key", access_key)
        keyring.set_password("nss3ui", f"{profile}:secret_key", secret_key)
    except Exception as exc:
        log.warning("keyring unavailable, keys not persisted: %s", exc)


def load_keys(profile: str) -> tuple[Optional[str], Optional[str]]:
    """Load access/secret key pair from OS keychain."""
    try:
        import keyring
        ak = keyring.get_password("nss3ui", f"{profile}:access_key")
        sk = keyring.get_password("nss3ui", f"{profile}:secret_key")
        return ak, sk
    except Exception:
        return None, None


def delete_keys(profile: str) -> None:
    try:
        import keyring
        keyring.delete_password("nss3ui", f"{profile}:access_key")
        keyring.delete_password("nss3ui", f"{profile}:secret_key")
    except Exception:
        pass
