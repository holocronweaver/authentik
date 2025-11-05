import mimetypes
import os
from abc import ABC, abstractmethod
from collections.abc import Generator
from enum import Enum
from pathlib import Path
from urllib.parse import urlsplit

import boto3
from botocore.config import Config
from django.db import connection
from django.utils.functional import cached_property

from authentik.lib.config import CONFIG


def get_storage_config(usage: "Usage", key: str, default=None):
    """Get storage configuration with usage-specific override support.

    Lookup order:
    1. storage.<usage>.<key> (e.g., storage.media.backend)
    2. storage.<key> (e.g., storage.backend)
    3. default value
    """
    usage_specific = CONFIG.get(f"storage.{usage.value}.{key}", None)
    if usage_specific is not None:
        return usage_specific
    return CONFIG.get(f"storage.{key}", default)


def get_mime_from_filename(filename: str) -> str:
    """Get mime type from filename"""
    mime_type, _ = mimetypes.guess_type(filename)
    return mime_type or "application/octet-stream"


class Usage(Enum):
    MEDIA = "media"
    REPORTS = "reports"


class Backend(ABC):
    def __init__(self, usage: Usage):
        self.usage = usage
        self._backend_type = get_storage_config(usage, "backend", "file")

    def get_config(self, key: str, default=None):
        """Get configuration value with usage-specific override support"""
        return get_storage_config(self.usage, key, default)

    @abstractmethod
    def can_manage_file(self, name: str) -> bool:
        pass

    @abstractmethod
    def list_files(self) -> Generator[str]:
        pass

    @abstractmethod
    def save_file(self, name: str, content: bytes) -> None:
        pass

    @abstractmethod
    def delete_file(self, name: str) -> None:
        pass

    @abstractmethod
    def file_url(self, name: str) -> str:
        pass

    @abstractmethod
    def file_size(self, name: str) -> int:
        pass


class StaticBackend(Backend):
    def can_manage_file(self, name: str) -> bool:
        return name.startswith("/static") or name.startswith("web/dist/assets")

    def list_files(self) -> Generator[str]:
        for dir in ("assets/icons", "assets/images"):
            for _, _, files in Path(f"web/dist/{dir}").walk():
                for file in files:
                    if file.endswith(".svg") or file.endswith("png"):
                        yield f"/static/{dir}/{file}"
            for _, _, files in Path(f"web/dist/{dir}").walk():
                for file in files:
                    if file.startswith("flow_") or file.startswith("logo-"):
                        yield f"/static/{dir}/{file}"

    def file_url(self, name: str) -> str:
        prefix = CONFIG.get("web.path", "/")[:-1]
        if name.startswith("/static"):
            return prefix + name
        if name.startswith("web/dist/assets"):
            return f"{prefix}/static/dist/{name.removeprefix('web/dist/')}"
        raise RuntimeError

    def file_size(self, name: str) -> int:
        return 0  # Static files size not tracked


class PassthroughBackend(Backend):
    def can_manage_file(self, name: str) -> bool:
        return name.startswith("fa://") or name.startswith("http:")

    def list_files(self) -> Generator[str]:
        yield from []

    def file_url(self, name: str) -> str:
        return name

    def file_size(self, name: str) -> int:
        return 0  # External files size not tracked


class FileBackend(Backend):
    @property
    def base_path(self) -> Path:
        """Path structure: /data/{usage}/{schema}"""
        base_dir = Path(self.get_config("file.path", "./data"))
        return base_dir / self.usage.value / connection.schema_name

    def can_manage_file(self, name: str) -> bool:
        return self._backend_type == "file"

    def list_files(self) -> Generator[str]:
        """List all files returning relative paths from base_path"""
        if not self.base_path.exists():
            return
        for root, _, files in os.walk(self.base_path):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(self.base_path)
                yield str(rel_path)

    def save_file(self, name: str, content: bytes) -> None:
        path = self.base_path / Path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)

    def delete_file(self, name: str) -> None:
        path = self.base_path / Path(name)
        path.unlink(missing_ok=True)

    def file_url(self, name: str) -> str:
        prefix = CONFIG.get("web.path", "/")[:-1]
        return f"{prefix}/{self.usage.value}/{connection.schema_name}/{name}"

    def file_size(self, name: str) -> int:
        path = self.base_path / Path(name)
        try:
            return path.stat().st_size if path.exists() else 0
        except Exception:
            return 0


class S3Backend(Backend):
    @property
    def base_path(self) -> str:
        """S3 key prefix: {usage}/{schema}/"""
        return f"{self.usage.value}/{connection.schema_name}/"

    @cached_property
    def bucket_name(self) -> str:
        return self.get_config("s3.bucket_name")

    @cached_property
    def session(self) -> boto3.Session:
        session_profile = self.get_config("s3.session_profile", None)
        if session_profile is not None:
            return boto3.Session(profile_name=session_profile)
        else:
            return boto3.Session(
                aws_access_key_id=self.get_config("s3.access_key", None),
                aws_secret_access_key=self.get_config("s3.secret_key", None),
                aws_session_token=self.get_config("s3.security_token", None),
            )

    @cached_property
    def client(self):
        endpoint_url = self.get_config("s3.endpoint", None)
        region_name = self.get_config("s3.region", None)

        return self.session.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region_name,
            config=Config(signature_version="s3v4"),
        )

    def can_manage_file(self, name: str) -> bool:
        return self._backend_type == "s3"

    def list_files(self) -> Generator[str]:
        """List all files returning relative paths from base_path"""
        paginator = self.client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=self.bucket_name, Prefix=self.base_path)

        for page in pages:
            for obj in page.get("Contents", []):
                key = obj["Key"]
                # Remove base path prefix to get relative path
                rel_path = key.removeprefix(self.base_path)
                if rel_path:  # Skip if it's just the directory itself
                    yield rel_path

    def save_file(self, name: str, content: bytes) -> None:
        self.client.put_object(
            Bucket=self.bucket_name,
            Key=f"{self.base_path}{name}",
            Body=content,
            ACL="private",
        )

    def delete_file(self, name: str) -> None:
        self.client.delete_object(
            Bucket=self.bucket_name,
            Key=f"{self.base_path}{name}",
        )

    def file_url(self, name: str) -> str:
        use_https = self.get_config("s3.secure_urls", True)
        if isinstance(use_https, str):
            use_https = use_https.lower() in ("true", "1", "yes")
        http_method = "GET"

        params = {
            "Bucket": self.bucket_name,
            "Key": f"{self.base_path}{name}",
        }
        expires_in = self.get_config("s3.presigned_expiry", 3600)
        if isinstance(expires_in, str):
            expires_in = int(expires_in)

        url = self.client.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=expires_in,
            HttpMethod=http_method,
        )

        custom_domain = self.get_config("s3.custom_domain", None)
        if custom_domain:
            parsed = urlsplit(url)
            scheme = "https" if use_https else "http"
            url = f"{scheme}://{custom_domain}{parsed.path}?{parsed.query}"

        return url

    def file_size(self, name: str) -> int:
        try:
            response = self.client.head_object(
                Bucket=self.bucket_name,
                Key=f"{self.base_path}{name}",
            )
            return response.get("ContentLength", 0)
        except Exception:
            return 0
