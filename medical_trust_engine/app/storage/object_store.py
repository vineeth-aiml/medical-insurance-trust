from pathlib import Path
from typing import BinaryIO, Optional

from app.core.config import settings

try:
    from minio import Minio
    from minio.error import S3Error
except Exception:  # pragma: no cover
    Minio = None
    S3Error = Exception


class ObjectStore:
    """MinIO/S3 first, local fallback second.

    The pipeline stores the original file locally for deterministic processing, but
    also uploads it to MinIO when enabled. This keeps local development simple and
    production audit storage durable.
    """

    def __init__(self):
        self.enabled = bool(settings.use_minio and Minio)
        self.client = None
        if self.enabled:
            self.client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )
            if not self.client.bucket_exists(settings.minio_bucket):
                self.client.make_bucket(settings.minio_bucket)

    def put_file(self, local_path: Path, object_key: str, content_type: str = "application/octet-stream") -> dict:
        if not self.enabled:
            return {"backend": "local", "key": str(local_path), "uploaded": False}
        self.client.fput_object(settings.minio_bucket, object_key, str(local_path), content_type=content_type)
        return {"backend": "minio", "bucket": settings.minio_bucket, "key": object_key, "uploaded": True}

    def get_file(self, object_key: str, dest_path: Path) -> Path:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.enabled:
            return Path(object_key)
        self.client.fget_object(settings.minio_bucket, object_key, str(dest_path))
        return dest_path


object_store = ObjectStore()
