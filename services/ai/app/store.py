"""Read-only access to the photo storage the report-service writes to (S3-compatible).

boto3 is synchronous, so each call runs in a worker thread and never blocks the event loop.
"""

import asyncio

import boto3
from botocore.config import Config

from app.config import settings


class PhotoStore:
    async def get(self, key: str) -> bytes:
        raise NotImplementedError


class S3PhotoStore(PhotoStore):
    def __init__(self) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5,
                read_timeout=20,
            ),
        )

    async def get(self, key: str) -> bytes:
        def read() -> bytes:
            return self._client.get_object(Bucket=settings.S3_BUCKET, Key=key)["Body"].read()

        return await asyncio.to_thread(read)


def build_store() -> PhotoStore | None:
    return S3PhotoStore() if settings.S3_ENDPOINT_URL else None
