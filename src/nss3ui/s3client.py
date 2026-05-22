"""Thin S3 client wrapper. All calls are blocking — run in worker threads only."""
from __future__ import annotations
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from typing import Optional, Iterator
import logging
from nss3ui.config import get_transfer_tuning

log = logging.getLogger(__name__)

PAGE_SIZE = 1000


class S3Client:
    """Wraps boto3 S3 client. Never call from the UI thread."""

    def __init__(
        self,
        profile: str = "default",
        region: str = "us-east-1",
        endpoint_url: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        session_token: Optional[str] = None,
    ):
        self._profile = profile
        self._region = region
        self._endpoint_url = endpoint_url
        self._access_key = access_key
        self._secret_key = secret_key
        self._session_token = session_token

        session_kwargs: dict = {}
        if profile and not access_key:
            session_kwargs["profile_name"] = profile

        self._session_kwargs = session_kwargs

        session = boto3.Session(**session_kwargs)

        client_kwargs: dict = {
            "service_name": "s3",
            "region_name": region,
            "config": Config(
                retries={"max_attempts": 3, "mode": "adaptive"},
                max_pool_connections=20,
            ),
        }
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        if access_key:
            client_kwargs["aws_access_key_id"] = access_key
            client_kwargs["aws_secret_access_key"] = secret_key
            if session_token:
                client_kwargs["aws_session_token"] = session_token

        # Store for async workers (without service_name / config)
        self._async_client_kwargs: dict = {"service_name": "s3", "region_name": region}
        if endpoint_url:
            self._async_client_kwargs["endpoint_url"] = endpoint_url
        if access_key:
            self._async_client_kwargs["aws_access_key_id"] = access_key
            self._async_client_kwargs["aws_secret_access_key"] = secret_key
            if session_token:
                self._async_client_kwargs["aws_session_token"] = session_token

        self._client = session.client(**client_kwargs)

    # ------------------------------------------------------------------
    # Buckets
    # ------------------------------------------------------------------

    def list_buckets(self) -> list[dict]:
        """Return list of bucket dicts with Name and CreationDate."""
        resp = self._client.list_buckets()
        return resp.get("Buckets", [])

    def create_bucket(self, name: str) -> None:
        kwargs: dict = {"Bucket": name}
        if self._region != "us-east-1":
            kwargs["CreateBucketConfiguration"] = {"LocationConstraint": self._region}
        self._client.create_bucket(**kwargs)

    def delete_bucket(self, name: str) -> None:
        self._client.delete_bucket(Bucket=name)

    def get_bucket_location(self, name: str) -> str:
        resp = self._client.get_bucket_location(Bucket=name)
        return resp.get("LocationConstraint") or "us-east-1"

    # ------------------------------------------------------------------
    # Objects
    # ------------------------------------------------------------------

    def list_objects_page(
        self,
        bucket: str,
        prefix: str = "",
        delimiter: str = "/",
        continuation_token: Optional[str] = None,
    ) -> dict:
        """
        Returns one page of objects.
        Result keys: Contents, CommonPrefixes, NextContinuationToken, IsTruncated
        """
        kwargs: dict = {
            "Bucket": bucket,
            "Prefix": prefix,
            "Delimiter": delimiter,
            "MaxKeys": PAGE_SIZE,
        }
        if continuation_token:
            kwargs["ContinuationToken"] = continuation_token
        return self._client.list_objects_v2(**kwargs)

    def list_all_objects(
        self, bucket: str, prefix: str = ""
    ) -> Iterator[dict]:
        """Yield every object dict under prefix (no delimiter — flat listing)."""
        token = None
        while True:
            kwargs: dict = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": PAGE_SIZE}
            if token:
                kwargs["ContinuationToken"] = token
            resp = self._client.list_objects_v2(**kwargs)
            for obj in resp.get("Contents", []):
                yield obj
            if not resp.get("IsTruncated"):
                break
            token = resp["NextContinuationToken"]

    def head_object(self, bucket: str, key: str) -> dict:
        return self._client.head_object(Bucket=bucket, Key=key)

    def delete_object(self, bucket: str, key: str) -> None:
        self._client.delete_object(Bucket=bucket, Key=key)

    def delete_objects(self, bucket: str, keys: list[str]) -> list[str]:
        """Batch delete. Returns list of keys that failed."""
        objects = [{"Key": k} for k in keys]
        resp = self._client.delete_objects(
            Bucket=bucket, Delete={"Objects": objects, "Quiet": False}
        )
        return [e["Key"] for e in resp.get("Errors", [])]

    def copy_object(self, src_bucket: str, src_key: str, dst_bucket: str, dst_key: str) -> None:
        self._client.copy_object(
            CopySource={"Bucket": src_bucket, "Key": src_key},
            Bucket=dst_bucket,
            Key=dst_key,
        )

    def generate_presigned_url(self, bucket: str, key: str, expires: int = 3600) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires,
        )

    # ------------------------------------------------------------------
    # Upload / Download (streaming)
    # ------------------------------------------------------------------

    def upload_file(
        self,
        local_path: str,
        bucket: str,
        key: str,
        progress_callback=None,
        extra_args: Optional[dict] = None,
    ) -> None:
        from boto3.s3.transfer import TransferConfig
        tune = get_transfer_tuning()
        max_concurrency = max(1, int(tune["max_concurrency"]))
        # High-throughput multipart transfer tuned for large file workloads.
        # Progress callback is thread-safe on worker side.
        config = TransferConfig(
            multipart_threshold=int(tune["multipart_threshold_mb"]) * 1024 * 1024,
            multipart_chunksize=int(tune["multipart_chunksize_mb"]) * 1024 * 1024,
            max_concurrency=max_concurrency,
            use_threads=max_concurrency > 1,
        )
        self._client.upload_file(
            local_path,
            bucket,
            key,
            Config=config,
            Callback=progress_callback,
            ExtraArgs=extra_args or {},
        )

    def download_file(
        self,
        bucket: str,
        key: str,
        local_path: str,
        progress_callback=None,
    ) -> None:
        from boto3.s3.transfer import TransferConfig
        tune = get_transfer_tuning()
        max_concurrency = max(1, int(tune["max_concurrency"]))
        config = TransferConfig(
            multipart_threshold=int(tune["multipart_threshold_mb"]) * 1024 * 1024,
            multipart_chunksize=int(tune["multipart_chunksize_mb"]) * 1024 * 1024,
            max_concurrency=max_concurrency,
            use_threads=max_concurrency > 1,
        )
        self._client.download_file(
            bucket,
            key,
            local_path,
            Config=config,
            Callback=progress_callback,
        )

    def get_object_partial(self, bucket: str, key: str, max_bytes: int = 65536) -> bytes:
        """Fetch first max_bytes of an object for preview."""
        resp = self._client.get_object(
            Bucket=bucket, Key=key, Range=f"bytes=0-{max_bytes - 1}"
        )
        return resp["Body"].read()

    @property
    def raw(self):
        """Expose underlying boto3 client for advanced use."""
        return self._client

    def create_multipart_upload(self, bucket: str, key: str) -> str:
        resp = self._client.create_multipart_upload(Bucket=bucket, Key=key)
        return resp["UploadId"]

    def upload_part(self, bucket: str, key: str, upload_id: str, part_number: int, body: bytes) -> str:
        resp = self._client.upload_part(
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
            PartNumber=part_number,
            Body=body,
        )
        return resp["ETag"]

    def complete_multipart_upload(
        self, bucket: str, key: str, upload_id: str, parts: list[dict]
    ) -> None:
        self._client.complete_multipart_upload(
            Bucket=bucket,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )

    def abort_multipart_upload(self, bucket: str, key: str, upload_id: str) -> None:
        self._client.abort_multipart_upload(Bucket=bucket, Key=key, UploadId=upload_id)

    def get_object_range(self, bucket: str, key: str, start: int, end: int) -> bytes:
        resp = self._client.get_object(Bucket=bucket, Key=key, Range=f"bytes={start}-{end}")
        return resp["Body"].read()

    @property
    def async_session_kwargs(self) -> dict:
        """Session kwargs for aioboto3 workers."""
        return dict(self._session_kwargs)

    @property
    def async_client_kwargs(self) -> dict:
        """Client kwargs for aioboto3 workers."""
        return dict(self._async_client_kwargs)

    def spawn(self) -> "S3Client":
        """Create an independent client instance for another worker thread."""
        return S3Client(
            profile=self._profile,
            region=self._region,
            endpoint_url=self._endpoint_url,
            access_key=self._access_key,
            secret_key=self._secret_key,
            session_token=self._session_token,
        )
