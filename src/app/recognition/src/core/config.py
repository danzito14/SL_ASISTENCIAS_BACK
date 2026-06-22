# recognition/core/config.py
import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # PostgreSQL — recognition se conecta como svc_recognition (SOLO LECTURA de
    # embeddings/trabajadores) para el match con pgvector.
    DB_HOST:     str
    DB_PORT:     int
    DB_USER:     str
    DB_PASSWORD: str
    DB_NAME:     str

    # App
    APP_TITLE:   str = "Recognition Service"
    APP_VERSION: str = "1.0.0"
    DEBUG:       bool = False
    CORS_ORIGINS: str = ""

    # Modelo facial
    PRELOAD_FACE_MODEL: bool = False  # precargar buffalo_l al arrancar

    # Anti-spoofing (Silent-Face / MiniFASNet vía ONNX)
    ANTISPOOFING_ACTIVO: bool = False
    ANTISPOOF_MODEL_DIR: str = "models/antispoof"
    ANTISPOOF_UMBRAL:    float = 0.0
    ANTISPOOF_REAL_INDEX: int = 1
    ANTISPOOF_DIV255: bool = True

    # Secreto compartido con el backend para la API interna (no se expone). Fail-closed.
    RECOGNITION_INTERNAL_TOKEN: str = os.getenv("RECOGNITION_INTERNAL_TOKEN", "")

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+psycopg2://"
            f"{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}"
            f"/{self.DB_NAME}"
        )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


settings = Settings()
