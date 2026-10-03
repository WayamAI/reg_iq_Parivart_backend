# `os` is imported here, at module scope, deliberately. It used to be imported inside
# LocalStorage.__init__, which bound it as a local of that function only -- so every
# other method's os.path.join raised NameError and the whole upload/download path was
# dead.
from abc import ABC, abstractmethod
from typing import BinaryIO, Optional
import os
import uuid

class StorageProvider(ABC):
    @abstractmethod
    async def upload_file(self, file_data: BinaryIO, file_name: str, content_type: str) -> str:
        """Upload a file and return the storage key/path."""
        pass

    @abstractmethod
    async def download_file(self, storage_key: str) -> BinaryIO:
        """Download a file given its storage key."""
        pass

    @abstractmethod
    async def delete_file(self, storage_key: str) -> bool:
        """Delete a file given its storage key."""
        pass

    @abstractmethod
    async def get_file_url(self, storage_key: str, expires_in: int = 3600) -> str:
        """Get a URL for the file (could be signed or direct)."""
        pass

class LocalStorage(StorageProvider):
    def __init__(self, base_path: str = "./storage"):
        self.base_path = base_path
        os.makedirs(self.base_path, exist_ok=True)

    async def upload_file(self, file_data: BinaryIO, file_name: str, content_type: str) -> str:
        # Generate a unique filename to avoid collisions
        file_id = str(uuid.uuid4())
        # Keep original extension
        ext = file_name.split('.')[-1] if '.' in file_name else ''
        storage_filename = f"{file_id}.{ext}" if ext else file_id
        storage_path = os.path.join(self.base_path, storage_filename)

        # Write the file
        with open(storage_path, "wb") as f:
            # Assuming file_data is a file-like object
            content = file_data.read()
            f.write(content)

        return storage_filename  # Return just the filename; we can store the base path elsewhere

    async def download_file(self, storage_key: str) -> BinaryIO:
        storage_path = os.path.join(self.base_path, storage_key)
        if not os.path.exists(storage_path):
            raise FileNotFoundError(f"File not found: {storage_key}")
        return open(storage_path, "rb")

    async def delete_file(self, storage_key: str) -> bool:
        storage_path = os.path.join(self.base_path, storage_key)
        if os.path.exists(storage_path):
            os.remove(storage_path)
            return True
        return False

    async def get_file_url(self, storage_key: str, expires_in: int = 3600) -> str:
        # For local storage, we can return a path or a URL if served via a web server.
        # For simplicity, we return a relative path that the app can serve.
        return f"/storage/{storage_key}"