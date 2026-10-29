"""Object storage for photos (S3-compatible: MinIO locally, S3 or Cloudflare R2 in production).

boto3 is synchronous, so every call runs in a worker thread and never blocks the event loop.
"""

import asyncio
import logging

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)


class ObjectStore:
    async def put(self, key: str, data: bytes, content_type: str) -> None:
        raise NotImplementedError

    async def get(self, key: str) -> bytes:
        raise NotImplementedError

    async def presign_get(self, key: str, expires: int) -> str:
        raise NotImplementedError

    async def ensure_ready(self) -> None:
        """Create the bucket if it does not exist yet."""


class S3Store(ObjectStore):
    def __init__(self) -> None:
        cfg = Config(
            signature_version="s3v4",
            s3={"addressing_style": "path"},
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=5,
            read_timeout=20,
        )

        def make(endpoint: str | None):
            return boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=settings.S3_ACCESS_KEY,
                aws_secret_access_key=settings.S3_SECRET_KEY,
                region_name=settings.S3_REGION,
                config=cfg,
            )

        self._client = make(settings.S3_ENDPOINT_URL)
        # Signing links is local work; use the address a browser can reach.
        self._signer = make(settings.S3_PUBLIC_URL or settings.S3_ENDPOINT_URL)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object, Bucket=settings.S3_BUCKET, Key=key, Body=data, ContentType=content_type
        )

    async def get(self, key: str) -> bytes:
        def read() -> bytes:
            return self._client.get_object(Bucket=settings.S3_BUCKET, Key=key)["Body"].read()

        return await asyncio.to_thread(read)

    async def presign_get(self, key: str, expires: int) -> str:
        return await asyncio.to_thread(
            self._signer.generate_presigned_url,
            "get_object",
            Params={"Bucket": settings.S3_BUCKET, "Key": key},
            ExpiresIn=expires,
        )

    async def ensure_ready(self) -> None:
        def ensure() -> None:
            try:
                self._client.head_bucket(Bucket=settings.S3_BUCKET)
            except ClientError:
                self._client.create_bucket(Bucket=settings.S3_BUCKET)

        await asyncio.to_thread(ensure)


class MemoryStore(ObjectStore):
    """In-process store for tests."""

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    async def get(self, key: str) -> bytes:
        return self.objects[key][0]

    async def presign_get(self, key: str, expires: int) -> str:
        return f"memory://{key}?expires={expires}"


_store: ObjectStore | None = None
_override: ObjectStore | None = None


def get_store() -> ObjectStore | None:
    """The configured store, or None when photo uploads are not set up."""
    global _store
    if _override is not None:
        return _override
    if not settings.S3_ENDPOINT_URL:
        return None
    if _store is None:
        _store = S3Store()
    return _store


def use_store(store: ObjectStore | None) -> None:
    """Replace the store (tests)."""
    global _override
    _override = store
