import mimetypes
import uuid

from django.http import FileResponse, Http404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError, NotFound
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from authentik.core.api.utils import PassiveSerializer
from authentik.core.models import User
from authentik.files.backend import STORAGE_BACKEND, Backend, FileBackend, S3Backend, Usage
from authentik.files.models import MediaFile, ReportFile


class FileSerializer(PassiveSerializer):
    uuid = serializers.UUIDField(read_only=True)
    friendly_name = serializers.CharField(read_only=True)
    url = serializers.CharField(read_only=True)
    mime_type = serializers.CharField(read_only=True)
    size = serializers.IntegerField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    usage = serializers.ChoiceField(
        choices=[(u.value, u.value) for u in Usage],
        read_only=True,
    )


class FileUploadRequestSerializer(PassiveSerializer):
    file = serializers.FileField(required=True)
    friendly_name = serializers.CharField(required=False, allow_blank=True)
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

    def _get_backend(self, usage: Usage) -> Backend:
        """Get the appropriate backend instance based on configuration"""
        if STORAGE_BACKEND == "file":
            return FileBackend(usage)
        elif STORAGE_BACKEND == "s3":
            return S3Backend(usage)
        else:
            raise ValidationError(f"Unknown storage backend: {STORAGE_BACKEND}")

    def _get_model_for_usage(self, usage: Usage):
        """Map Usage enum to database model

        Each usage type has its own table for metadata (friendly_name, mime_type, created_at)
        """
        mapping = {
            Usage.MEDIA: MediaFile,
            Usage.REPORTS: ReportFile,
        }
        return mapping.get(usage)

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
            )
        ],
        responses={200: FileSerializer(many=True)},
    )
    def list(self, request: Request) -> Response:
        """List files from backend (source of truth), complement with DB metadata"""
        usage_param = request.query_params.get("usage", Usage.MEDIA.value)
        try:
            usage = Usage(usage_param)
        except ValueError:
            raise ValidationError(f"Invalid usage: {usage_param}")

        model = self._get_model_for_usage(usage)
        backend = self._get_backend(usage)

        # Backend (FS/S3) is source of truth - list all files from storage
        file_uuids = [uuid.UUID(f) for f in backend.list_files()]

        # Single bulk query for all metadata instead of N+1 queries
        db_files = {str(f.uuid): f for f in model.objects.filter(uuid__in=file_uuids)}

        files = []
        for file_uuid in file_uuids:
            uuid_str = str(file_uuid)
            db_file = db_files.get(uuid_str)

            try:
                file_path = backend.base_path / uuid_str
                file_size = file_path.stat().st_size if file_path.exists() else 0
            except Exception:
                file_size = 0

            mime_type = db_file.mime_type if db_file else ""
            files.append(
                {
                    "uuid": uuid_str,
                    "friendly_name": db_file.friendly_name if db_file else uuid_str,
                    "url": backend.file_url(uuid_str, mime_type),
                    "mime_type": mime_type,
                    "size": file_size,
                    "created_at": db_file.created_at if db_file else None,
                    "usage": usage.value,
                }
            )

        return Response(
            {
                "pagination": {
                    "next": 0,
                    "previous": 0,
                    "count": len(files),
                    "current": 1,
                    "total_pages": 1,
                    "start_index": 1,
                    "end_index": len(files),
                },
                "results": files,
            }
        )

    @extend_schema(
        request=FileUploadRequestSerializer,
        responses={200: FileSerializer},
    )
    @action(detail=False, methods=["POST"])
    def upload(self, request: Request) -> Response:
        """Upload file with UUID name, store metadata in DB"""
        serializer = FileUploadRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        file = serializer.validated_data["file"]
        friendly_name = serializer.validated_data.get("friendly_name")
        usage = Usage(serializer.validated_data["usage"])

        model = self._get_model_for_usage(usage)
        backend = self._get_backend(usage)

        # Generate UUID for file storage
        file_uuid = uuid.uuid4()

        # Use UUID if no friendly_name provided
        if not friendly_name:
            friendly_name = str(file_uuid)

        # Detect mime type
        mime_type, _ = mimetypes.guess_type(file.name)
        if not mime_type:
            mime_type = file.content_type or "application/octet-stream"

        # Save to backend with UUID as filename
        content = file.read()
        file_size = len(content)
        backend.save_file(str(file_uuid), content)

        # Save metadata to DB
        db_file = model.objects.create(
            uuid=file_uuid,
            friendly_name=friendly_name,
            mime_type=mime_type,
        )

        return Response(
            {
                "uuid": str(db_file.uuid),
                "friendly_name": db_file.friendly_name,
                "url": backend.file_url(str(file_uuid), db_file.mime_type),
                "mime_type": db_file.mime_type,
                "size": file_size,
                "created_at": db_file.created_at,
                "usage": usage.value,
            }
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="name",
                type=str,
                required=True,
                description="File name to delete",
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
        """Delete file from backend and DB"""
        uuid_str = request.query_params.get("name")
        usage_param = request.query_params.get("usage", Usage.MEDIA.value)

        if not uuid_str:
            raise ValidationError("name parameter is required")

        try:
            usage = Usage(usage_param)
            file_uuid = uuid.UUID(uuid_str)
        except ValueError:
            raise ValidationError(f"Invalid UUID or usage")

        model = self._get_model_for_usage(usage)
        backend = self._get_backend(usage)

        # Delete from backend (source of truth)
        backend.delete_file(uuid_str)

        # Delete metadata from DB
        model.objects.filter(uuid=file_uuid).delete()

        return Response({"message": f"File {uuid_str} deleted successfully"})
