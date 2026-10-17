"""
An object store a bot writes into: `put` and `delete`, by key, and --
for keeping the bucket inside R2's free plan alone -- `list`, every key
and its size, and `get`, an object's bytes (docs/design/pbd-site.md,
"The store", "The free plan").

- `R2Store` is Cloudflare R2 over its S3 API, through boto3. Every call
  runs in `asyncio.to_thread`, since boto3 blocks, and boto3 is imported
  in the constructor, never here: a checkout without it imports this
  module, and the suite runs with no boto3 installed.
- `MemoryStore` is the tests' store: the objects in a dict, every call
  in the order it was made, and a failure on demand.

Shared by both bots in principle -- nothing here knows Codex -- though
only the Codex publisher writes through it today.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Optional, Protocol


class ObjectStore(Protocol):
    """Where a publisher writes. Every call raises on a failure; the
    caller decides what a failure means."""

    async def put(self, key: str, body: bytes, content_type: str, cache_control: str) -> None:
        ...

    async def delete(self, key: str) -> None:
        ...

    async def list(self, prefix: str = "") -> dict[str, int]:
        """Every key under `prefix`, with its size in bytes."""
        ...

    async def get(self, key: str) -> bytes:
        ...


#: The most keys one listing hands back: S3's `ListObjectsV2` page,
#: which R2 keeps. Each page is one Class A operation.
LIST_PAGE = 1000


def list_pages(count: int) -> int:
    """How many listings `count` keys took -- one even for none."""
    return max(1, -(-count // LIST_PAGE))


def r2_endpoint(account_id: str) -> str:
    """R2's S3 endpoint for an account."""
    return f"https://{account_id}.r2.cloudflarestorage.com"


class R2Store:
    """
    A bucket on Cloudflare R2, written through its S3 API with a token
    scoped to that bucket. Raises `ImportError` where boto3 is not
    installed, so the caller can turn the publisher off rather than fail.
    """

    def __init__(self, account_id: str, access_key_id: str, secret_access_key: str,
                 bucket: str) -> None:
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=r2_endpoint(account_id),
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
            config=Config(
                connect_timeout=10,
                read_timeout=30,
                retries={"max_attempts": 3, "mode": "standard"},
                # botocore 1.36 began sending a checksum on every request
                # by default; R2 is S3-compatible rather than S3, so ask for
                # one only where an operation requires it.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    async def put(self, key: str, body: bytes, content_type: str, cache_control: str) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
            CacheControl=cache_control,
        )

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._client.delete_object, Bucket=self.bucket, Key=key)

    async def list(self, prefix: str = "") -> dict[str, int]:
        return await asyncio.to_thread(self._list, prefix)

    def _list(self, prefix: str) -> dict[str, int]:
        found: dict[str, int] = {}
        pages = self._client.get_paginator("list_objects_v2").paginate(
            Bucket=self.bucket, Prefix=prefix, PaginationConfig={"PageSize": LIST_PAGE})
        for page in pages:
            for entry in page.get("Contents", []):
                found[entry["Key"]] = int(entry["Size"])
        return found

    async def get(self, key: str) -> bytes:
        return await asyncio.to_thread(self._get, key)

    def _get(self, key: str) -> bytes:
        return self._client.get_object(Bucket=self.bucket, Key=key)["Body"].read()


@dataclass(frozen=True)
class StoredObject:
    body: bytes
    content_type: str
    cache_control: str


class MemoryStore:
    """
    The tests' store. `objects` holds what is up; `calls` every call made,
    in order, as `("put", key)`, `("delete", key)`, `("list", prefix)` or
    `("get", key)`, failed ones included.
    `fail` decides, per call, whether it raises: a bool for every call, or
    a function of `(operation, key)`.
    """

    def __init__(self) -> None:
        self.objects: dict[str, StoredObject] = {}
        self.calls: list[tuple[str, str]] = []
        self.fail: bool | Callable[[str, str], bool] = False
        #: Awaited before every call where set, so a test can hold a call
        #: in flight while it makes more changes.
        self.gate: Optional[asyncio.Event] = None

    def _failing(self, operation: str, key: str) -> bool:
        return self.fail(operation, key) if callable(self.fail) else bool(self.fail)

    async def _call(self, operation: str, key: str) -> None:
        self.calls.append((operation, key))
        if self.gate is not None:
            await self.gate.wait()
        else:
            await asyncio.sleep(0)
        if self._failing(operation, key):
            raise ConnectionError(f"MemoryStore refused {operation} {key}")

    async def put(self, key: str, body: bytes, content_type: str, cache_control: str) -> None:
        await self._call("put", key)
        self.objects[key] = StoredObject(bytes(body), content_type, cache_control)

    async def delete(self, key: str) -> None:
        await self._call("delete", key)
        self.objects.pop(key, None)

    async def list(self, prefix: str = "") -> dict[str, int]:
        await self._call("list", prefix)
        return {key: len(stored.body) for key, stored in self.objects.items()
                if key.startswith(prefix)}

    async def get(self, key: str) -> bytes:
        await self._call("get", key)
        if key not in self.objects:
            raise KeyError(key)
        return self.objects[key].body

    def puts(self) -> list[str]:
        return [key for operation, key in self.calls if operation == "put"]

    def deletes(self) -> list[str]:
        return [key for operation, key in self.calls if operation == "delete"]
