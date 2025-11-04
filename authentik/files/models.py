"""File models"""

import uuid

from django.db import models


class BaseFile(models.Model):
    """Base file metadata model"""

    uuid = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    friendly_name = models.CharField(
        max_length=255, help_text="User-friendly name for the file"
    )
    mime_type = models.CharField(max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]

    def __str__(self):
        return self.friendly_name


class MediaFile(BaseFile):
    """Media files"""

    pass


class ReportFile(BaseFile):
    """Report files"""

    pass
