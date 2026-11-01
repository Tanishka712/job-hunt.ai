"""Azure Blob Storage adapter implementing BlobStore port."""

from collections.abc import Callable
from typing import Protocol


class AsyncBlobClientLike(Protocol):
    """Structural interface for an Azure `BlobClient`."""

    @property
    def url(self) -> str: ...

    async def upload_blob(
        self, data: bytes, *, overwrite: bool = True, content_type: str | None = None
    ) -> None: ...

    async def download_blob(self) -> "AsyncStorageStreamLike": ...


class AsyncStorageStreamLike(Protocol):
    """Structural interface for an Azure `StorageStreamDownloader`."""

    async def readall(self) -> bytes: ...


class AsyncBlobServiceClientLike(Protocol):
    """Structural interface for an Azure `BlobServiceClient`."""

    def get_blob_client(self, container: str, blob: str) -> AsyncBlobClientLike: ...


class AzureBlobStore:
    """Azure Blob Storage adapter with short-lived read-only SAS URL generation."""

    def __init__(
        self,
        service_client: AsyncBlobServiceClientLike,
        sas_token_builder: Callable[[str, str, int], str],
    ) -> None:
        self._service_client = service_client
        self._sas_token_builder = sas_token_builder

    async def upload_bytes(
        self, container: str, blob_path: str, data: bytes, content_type: str
    ) -> str:
        blob_client = self._service_client.get_blob_client(container=container, blob=blob_path)
        await blob_client.upload_blob(data, overwrite=True, content_type=content_type)
        return blob_client.url

    async def download_bytes(self, container: str, blob_path: str) -> bytes:
        blob_client = self._service_client.get_blob_client(container=container, blob=blob_path)
        stream = await blob_client.download_blob()
        return await stream.readall()

    async def generate_read_sas_url(
        self, container: str, blob_path: str, expires_in_seconds: int = 900
    ) -> str:
        blob_client = self._service_client.get_blob_client(container=container, blob=blob_path)
        sas_token = self._sas_token_builder(container, blob_path, expires_in_seconds)
        return f"{blob_client.url}?{sas_token.lstrip('?')}"
