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

STORAGE_BACKEND = CONFIG.get("storage.backend", "file")


def get_extension_from_mime(mime_type: str) -> str:
    """Convert mime type to file extension"""
    if not mime_type:
        return ""
    ext = mimetypes.guess_extension(mime_type)
    return ext if ext else ""


class Usage(Enum):
    MEDIA = "media"
    REPORTS = "reports"


class Backend(ABC):
    def __init__(self, usage: Usage):
        self.usage = usage

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
    def file_url(self, name: str, mime_type: str = "") -> str:
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

    def file_url(self, name: str, mime_type: str = "") -> str:
        prefix = CONFIG.get("web.path", "/")[:-1]
        if name.startswith("/static"):
            return prefix + name
        if name.startswith("web/dist/assets"):
            return f"{prefix}/static/dist/{name.removeprefix('web/dist/')}"
        raise RuntimeError


class PassthroughBackend(Backend):
    def can_manage_file(self, name: str) -> bool:
        return name.startswith("fa://") or name.startswith("http:")

    def list_files(self) -> Generator[str]:
        yield from []

    def file_url(self, name: str, mime_type: str = "") -> str:
        return name


class FileBackend(Backend):
    @property
    def base_path(self) -> Path:
        """Path structure: /data/{usage}/{schema}"""
        base_dir = Path(CONFIG.get("storage.file.path", "./data"))
        return base_dir / self.usage.value / connection.schema_name

    def can_manage_file(self, name: str) -> bool:
        return STORAGE_BACKEND == "file"

    def list_files(self) -> Generator[str]:
        for dir, _, files in self.base_path.walk():
            for file in files:
                yield file

    def save_file(self, name: str, content: bytes) -> None:
        path = self.base_path / Path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            f.write(content)

    def delete_file(self, name: str) -> None:
        path = self.base_path / Path(name)
        path.unlink(missing_ok=True)

    def file_url(self, name: str, mime_type: str = "") -> str:
        prefix = CONFIG.get("web.path", "/")[:-1]
        ext = get_extension_from_mime(mime_type)
        return f"{prefix}/{self.usage.value}/{connection.schema_name}/{name}{ext}"


class S3Backend(Backend):
    @property
    def base_path(self) -> str:
        """S3 key prefix: {usage}/{schema}/"""
        return f"{self.usage.value}/{connection.schema_name}/"

    @cached_property
    def bucket_name(self) -> str:
        return CONFIG.get("storage.s3.bucket_name")

    @cached_property
    def session(self) -> boto3.Session:
        session_profile = CONFIG.get("storage.s3.session_profile", None)
        if session_profile is not None:
            return boto3.Session(profile_name=session_profile)
        else:
            return boto3.Session(
                aws_access_key_id=CONFIG.get("storage.s3.access_key", None),
                aws_secret_access_key=CONFIG.get("storage.s3.secret_key", None),
                aws_session_token=CONFIG.get("storage.s3.security_token", None),
            )

    @cached_property
    def client(self):
        endpoint_url = CONFIG.get("storage.s3.endpoint", None)
        region_name = CONFIG.get("storage.s3.region", None)

        return self.session.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region_name,
            config=Config(signature_version="s3v4"),
        )

    def can_manage_file(self, name: str) -> bool:
        return STORAGE_BACKEND == "s3"

    def list_files(self) -> Generator[str]:
        paginator = self.client.get_paginator("list_objects_v2")
        pages = paginator.paginate(Bucket=self.bucket_name, Prefix=self.base_path)

        for page in pages:
            for obj in page.get("Contents", []):
                key = obj["Key"]
                yield key.removeprefix(self.base_path)

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

    def file_url(self, name: str, mime_type: str = "") -> str:
        use_https = CONFIG.get_bool("storage.s3.secure_urls", True)
        http_method = "GET"

        ext = get_extension_from_mime(mime_type)
        key_with_ext = f"{self.base_path}{name}{ext}"

        params = {
            "Bucket": self.bucket_name,
            "Key": key_with_ext,
        }
        expires_in = CONFIG.get_int("storage.s3.presigned_expiry", 3600)

        url = self.client.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=expires_in,
            HttpMethod=http_method,
        )

        custom_domain = CONFIG.get("storage.s3.custom_domain", None)
        if custom_domain:
            parsed = urlsplit(url)
            scheme = "https" if use_https else "http"
            url = f"{scheme}://{custom_domain}{parsed.path}?{parsed.query}"

        return url
