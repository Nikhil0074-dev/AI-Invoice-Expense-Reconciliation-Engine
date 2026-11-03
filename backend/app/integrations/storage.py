"""Private file storage behind a small interface (swap LocalStorage for an S3-compatible adapter in production)."""
import os
import uuid
from abc import ABC, abstractmethod

from app.core.config import get_settings


class StorageBackend(ABC):
    @abstractmethod
    def put(self, data: bytes) -> str: ...
    @abstractmethod
    def path(self, key: str) -> str: ...
    @abstractmethod
    def delete(self, key: str) -> None: ...


class LocalStorage(StorageBackend):
    def __init__(self, root: str | None = None):
        self.root = os.path.abspath(root or get_settings().storage_dir)
        os.makedirs(self.root, exist_ok=True)

    def put(self, data: bytes) -> str:
        key = uuid.uuid4().hex  # generated key: never derived from user input, never a public URL
        with open(os.path.join(self.root, key), "wb") as f:
            f.write(data)
        return key

    def path(self, key: str) -> str:
        if not key.isalnum():
            raise ValueError("invalid storage key")
        return os.path.join(self.root, key)

    def delete(self, key: str) -> None:
        try:
            os.remove(self.path(key))
        except FileNotFoundError:
            pass


def get_storage() -> StorageBackend:
    return LocalStorage()
