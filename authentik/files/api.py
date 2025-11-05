import re
import uuid
from pathlib import Path, PurePosixPath

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from authentik.core.api.utils import PassiveSerializer
from authentik.core.models import User
from authentik.files.backend import (
    Backend,
    FileBackend,
    S3Backend,
    Usage,
    get_mime_from_filename,
    get_storage_config,
)


def sanitize_file_path(file_path: str) -> str:
    """Sanitize file path to prevent directory traversal attacks.
    """
    if not file_path:
        raise ValidationError("File path cannot be empty")

    # Strip whitespace
    file_path = file_path.strip()

    # Convert to posix path for consistent handling
    path = PurePosixPath(file_path)

    # Check for absolute paths
    if path.is_absolute():
        raise ValidationError("Absolute paths are not allowed")

    # Normalize the path and check for directory traversal
    normalized = str(path)

    # Check for parent directory references or current directory at start
    if ".." in path.parts:
        raise ValidationError("Parent directory references (..) are not allowed")

    # Disallow paths starting with dot (hidden files at root level)
    if normalized.startswith("."):
        raise ValidationError("Paths cannot start with '.'")

    # Check path length limits
    if len(normalized) > 1024:
        raise ValidationError("File path too long (max 1024 characters)")

    for part in path.parts:
        if len(part) > 255:
            raise ValidationError("Path component too long (max 255 characters)")

    # Remove any duplicate slashes
    normalized = re.sub(r"/+", "/", normalized)

    # Final safety check: ensure the normalized path doesn't escape
    if normalized.startswith("/") or normalized.startswith(".."):
        raise ValidationError("Invalid file path")

    return normalized


class FileSerializer(PassiveSerializer):
    name = serializers.CharField(read_only=True)
    url = serializers.CharField(read_only=True)
    mime_type = serializers.CharField(read_only=True)
    size = serializers.IntegerField(read_only=True)
    usage = serializers.ChoiceField(
        choices=[(u.value, u.value) for u in Usage],
        read_only=True,
    )


class FileUploadRequestSerializer(PassiveSerializer):
    file = serializers.FileField(required=True)
    path = serializers.CharField(required=False, allow_blank=True)
    usage = serializers.ChoiceField(
        choices=[(u.value, u.value) for u in Usage],
        required=True,
    )


class UsageSerializer(PassiveSerializer):
    value = serializers.CharField()
    label = serializers.CharField()


class FileViewSet(ViewSet):
    serializer_class = FileSerializer
    parser_classes = [MultiPartParser]
    # Dummy queryset for permission checks
    queryset = User.objects.none()

    def _build_file_response(self, file_path: str, backend: Backend, usage: Usage) -> dict:
        """Build standardized file response with schema prefix for display

        Args:
            file_path: Relative file path (e.g., "my-icon.png")
            backend: Storage backend instance
            usage: Usage type

        Returns:
            Dictionary with file information including schema-prefixed name
        """
        from django.db import connection

        # Include schema prefix in displayed name for clarity about tenant
        display_name = f"{connection.schema_name}/{file_path}"

        return {
            "name": display_name,
            "url": backend.file_url(file_path),
            "mime_type": get_mime_from_filename(file_path),
            "size": backend.file_size(file_path),
            "usage": usage.value,
        }

    def _strip_schema_prefix(self, file_path: str) -> str:
        """Strip schema prefix from file path if present

        Args:
            file_path: File path possibly with schema prefix (e.g., "public/my-icon.png")

        Returns:
            File path without schema prefix (e.g., "my-icon.png")
        """
        from django.db import connection

        schema_prefix = f"{connection.schema_name}/"
        return file_path.removeprefix(schema_prefix)

    def _build_paginated_response(self, results: list) -> dict:
        """Build standardized paginated response

        Args:
            results: List of file response dictionaries

        Returns:
            Response dictionary with pagination metadata and results
        """
        count = len(results)
        return {
            "pagination": {
                "next": 0,
                "previous": 0,
                "count": count,
                "current": 1,
                "total_pages": 1 if count > 0 else 0,
                "start_index": 1 if count > 0 else 0,
                "end_index": count,
            },
            "results": results,
        }

    def _get_backend(self, usage: Usage) -> Backend:
        """Get the appropriate backend instance based on configuration

        Supports usage-specific overrides:
        - storage.media.backend or storage.reports.backend
        - Falls back to storage.backend
        """
        backend_type = get_storage_config(usage, "backend", "file")
        if backend_type == "file":
            return FileBackend(usage)
        elif backend_type == "s3":
            return S3Backend(usage)
        else:
            raise ValidationError(f"Unknown storage backend: {backend_type}")

    @extend_schema(responses={200: UsageSerializer(many=True)})
    @action(detail=False, methods=["GET"])
    def usages(self, request: Request) -> Response:
        """Get available usage types"""
        usages = [{"value": u.value, "label": u.value.title()} for u in Usage]
        return Response(usages)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="usage",
                type=str,
                enum=[u.value for u in Usage],
                default=Usage.MEDIA.value,
                description="Filter files by usage type",
            ),
            OpenApiParameter(
                name="search",
                type=str,
                required=False,
                description="Search for files by name (case-insensitive substring match)",
            ),
        ],
        responses={200: FileSerializer(many=True)},
    )
    def list(self, request: Request) -> Response:
        """List files from storage backend (filesystem or S3)"""
        usage_param = request.query_params.get("usage", Usage.MEDIA.value)
        search_query = request.query_params.get("search", "").strip().lower()

        try:
            usage = Usage(usage_param)
        except ValueError:
            raise ValidationError(f"Invalid usage: {usage_param}")

        backend = self._get_backend(usage)

        # Backend is source of truth - list all files from storage
        files = []
        for file_path in backend.list_files():
            # Apply search filter if provided
            if search_query and search_query not in file_path.lower():
                continue

            files.append(self._build_file_response(file_path, backend, usage))

        return Response(self._build_paginated_response(files))

    @extend_schema(
        request=FileUploadRequestSerializer,
        responses={200: FileSerializer},
    )
    @action(detail=False, methods=["POST"])
    def upload(self, request: Request) -> Response:
        """Upload file to storage backend"""
        serializer = FileUploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        file = serializer.validated_data["file"]
        custom_path = serializer.validated_data.get("path", "").strip()
        usage = Usage(serializer.validated_data["usage"])

        backend = self._get_backend(usage)

        # Determine file path
        if custom_path:
            # Use custom path if provided
            file_path = custom_path
            # Add extension from original filename if not present
            path_obj = PurePosixPath(file_path)
            if not path_obj.suffix and Path(file.name).suffix:
                file_path = f"{file_path}{Path(file.name).suffix}"
        else:
            # Use original filename
            file_path = file.name

        # Sanitize path to prevent directory traversal
        file_path = sanitize_file_path(file_path)

        # Save to backend
        content = file.read()
        backend.save_file(file_path, content)

        return Response(self._build_file_response(file_path, backend, usage))

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="name",
                type=str,
                required=True,
                description="File path to delete",
            ),
            OpenApiParameter(
                name="usage",
                type=str,
                enum=[u.value for u in Usage],
                default=Usage.MEDIA.value,
                description="Usage type of the file",
            ),
        ],
        responses={200: None},
    )
    @action(detail=False, methods=["DELETE"])
    def delete(self, request: Request) -> Response:
        """Delete file from storage backend"""
        file_path = request.query_params.get("name")
        usage_param = request.query_params.get("usage", Usage.MEDIA.value)

        if not file_path:
            raise ValidationError("name parameter is required")

        # Strip schema prefix if present (e.g., 'public/file.png' -> 'file.png')
        file_path = self._strip_schema_prefix(file_path)

        # Sanitize the file path to prevent directory traversal
        file_path = sanitize_file_path(file_path)

        try:
            usage = Usage(usage_param)
        except ValueError:
            raise ValidationError(f"Invalid usage: {usage_param}")

        backend = self._get_backend(usage)

        # Delete from backend
        backend.delete_file(file_path)

        return Response({"message": f"File {file_path} deleted successfully"})
