"""API URLs"""

from authentik.files.api import FileViewSet

api_urlpatterns = [
    ("files", FileViewSet, "files"),
]
