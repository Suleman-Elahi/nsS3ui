"""Application controller that orchestrates client + transfer manager creation."""
from __future__ import annotations
from nss3ui.s3client import S3Client
from nss3ui.transfer_manager import TransferManager


class AppController:
    def __init__(self, parent=None):
        self._parent = parent
        self.client: S3Client | None = None
        self.manager: TransferManager | None = None

    def connect_profile(self, profile: str, region: str, endpoint_url: str | None = None) -> None:
        self.client = S3Client(profile=profile, region=region, endpoint_url=endpoint_url)
        self.manager = TransferManager(self.client, self._parent)

    def connect_keys(
        self,
        region: str,
        access_key: str,
        secret_key: str,
        session_token: str | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        self.client = S3Client(
            region=region,
            endpoint_url=endpoint_url,
            access_key=access_key,
            secret_key=secret_key,
            session_token=session_token,
        )
        self.manager = TransferManager(self.client, self._parent)

    def disconnect(self) -> None:
        self.client = None
        self.manager = None
