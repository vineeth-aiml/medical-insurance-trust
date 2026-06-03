from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Central production configuration.

    Defaults are local-dev friendly. In production, set these through environment
    variables or a secret manager.
    """

    app_name: str = "Medical Document Trust Engine"
    environment: Literal["local", "dev", "staging", "production"] = "local"
    debug: bool = False

    data_dir: Path = BASE_DIR / "data"
    upload_dir: Path = BASE_DIR / "data" / "uploads"
    processed_dir: Path = BASE_DIR / "data" / "processed"
    allowed_extensions: set[str] = {".pdf", ".png", ".jpg", ".jpeg"}
    max_upload_mb: int = 50

    # Production default should be PostgreSQL. SQLite remains only for local demos.
    database_url: str = Field(
        default=f"sqlite:///{BASE_DIR / 'medical_trust_engine.db'}",
        description="Use postgresql+psycopg2://user:pass@postgres:5432/medical_trust_engine in production",
    )

    # Async pipeline.
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    async_processing: bool = False

    # Object storage. If disabled/unavailable, the app falls back to local storage.
    use_minio: bool = False
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "medical-claims"
    minio_secure: bool = False

    # OCR engines.
    ocr_engine: Literal["auto", "paddle", "tesseract", "none"] = "auto"
    paddle_use_gpu: bool = False
    paddle_lang: str = "en"
    enable_trocr: bool = False

    # External verification providers. Leave blank when not contracted.
    hospital_api_base_url: Optional[str] = None
    hospital_api_token: Optional[str] = None
    nmc_api_base_url: Optional[str] = None
    nmc_api_token: Optional[str] = None

    # Manual/seeded verification data.
    known_doctors_file: Path = BASE_DIR / "app" / "seed_data" / "known_doctors.json"
    verified_invoices_file: Path = BASE_DIR / "app" / "seed_data" / "verified_invoices.json"
    signature_reference_dir: Path = BASE_DIR / "app" / "seed_data" / "reference_signatures"
    stamp_reference_dir: Path = BASE_DIR / "app" / "seed_data" / "reference_stamps"

    # UI behavior.
    show_debug_json: bool = False

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    for directory in [settings.data_dir, settings.upload_dir, settings.processed_dir]:
        directory.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()

# Backward-compatible names used by older service code.
DATA_DIR = settings.data_dir
UPLOAD_DIR = settings.upload_dir
PROCESSED_DIR = settings.processed_dir
DATABASE_URL = settings.database_url
ALLOWED_EXTENSIONS = settings.allowed_extensions
MAX_UPLOAD_MB = settings.max_upload_mb
