# kiosk_local/core/config.py
# Micro LOCAL del kiosko de escritorio (corre en la PC, NO en la nube). Baja el roster
# de la nube (offline_sync) a un postgres+pgvector LOCAL, reconoce offline (recognition
# local) y sube los fichajes a la nube cuando hay internet. Independiente si se cae la red.
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── PostgreSQL LOCAL (en la PC; mismo esquema init.sql, con pgvector) ──────
    DB_HOST:     str
    DB_PORT:     int
    DB_USER:     str
    DB_PASSWORD: str
    DB_NAME:     str

    APP_TITLE:   str = "Kiosk Local Service"
    APP_VERSION: str = "1.0.0"
    DEBUG:       bool = False

    # ── NUBE — de dónde baja el roster y a dónde sube los eventos ──────────────
    # Gateway de prod (mismo que usa el APK): https://sl-asistencias.slagricola.cloud/api
    # Login: POST {CLOUD_BASE_URL}/usuarios/login ; roster/subida: {CLOUD_BASE_URL}/off_sync/*
    CLOUD_BASE_URL:  str = "http://localhost:8000"
    KIOSK_USER:      str = ""          # usuario kiosko (rol escaneador) → define la EMPRESA
    KIOSK_PASSWORD:  str = ""
    KIOSK_TIPO:      str = "oficina"   # campo | oficina | empaque | mixto
    KIOSK_EMPRESA:   int | None = None  # opcional; si el token no acota, se pasa ?id_empresa=
    KIOSK_TZ:        str = "America/Mazatlan"  # zona horaria de la empresa local (el roster no la trae)
    HTTP_TIMEOUT:    float = 60.0
    EMBEDDING_DIM:   int = 512

    # ── Reconocimiento LOCAL (contenedor recognition apuntando a la BD local) ──
    RECOGNITION_URL:            str = "http://recognition:8000"
    RECOGNITION_INTERNAL_TOKEN: str = ""
    RECOGNITION_TIMEOUT:        float = 30.0

    # ── Fichaje local ─────────────────────────────────────────────────────────
    # Puerta donde ficha este kiosko (debe existir en el roster). Si es None, se usa
    # la primera puerta activa del roster local. id_dispositivo_origen = auditoría offline.
    KIOSK_PUERTA:       int | None = None
    KIOSK_DISPOSITIVO:  int | None = None

    # ── Auto-sync (sube la cola de escaneos a la nube solo) ───────────────────
    KIOSK_SYNC_INTERVAL_SEG: float = 30.0   # cada cuánto intenta subir la cola
    KIOSK_SYNC_BATCH:        int = 500      # máx escaneos por lote de subida

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+psycopg2://"
            f"{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}"
            f"/{self.DB_NAME}"
        )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=True)


settings = Settings()
