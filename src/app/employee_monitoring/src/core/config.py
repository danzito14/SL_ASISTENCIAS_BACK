# employee_monitoring/core/config.py
import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # PostgreSQL — employee_monitoring corre como svc_workers (escribe trabajadores/
    # embeddings y sus tablas de estado de sync; con SELECT sobre area_trabajo de
    # tenancy para validar/clasificar áreas).
    DB_HOST:     str
    DB_PORT:     int
    DB_USER:     str
    DB_PASSWORD: str
    DB_NAME:     str

    APP_TITLE:   str = "Employee Monitoring Service"
    APP_VERSION: str = "1.0.0"
    DEBUG:       bool = False
    CORS_ORIGINS: str = ""

    # ── Nómina externa SYS21 (MSSQL) — ORIGEN de empleados ────────────────────
    # Dos bases distintas (cada una mapea a una empresa); columnas y filtros
    # propios por origen (ver sources/sys21_reader.py). Solo lectura.
    SYS_21_URL_AGRICOLA:     str = ""
    SYS_21_URL_AGRICOLA_COM: str = ""

    # ── Servidor de fotos (acceso por SSH/SFTP con llave) ─────────────────────
    FOTOS_SFTP_HOST:           str = ""
    FOTOS_SFTP_PORT:           int = 22
    FOTOS_SFTP_USER:           str = ""
    FOTOS_SFTP_KEY_PATH:       str = ""           # ruta a la llave privada (montada read-only)
    FOTOS_SFTP_KEY_PASSPHRASE: str | None = None
    FOTOS_SFTP_BASE_DIR:       str = "."          # carpeta remota base de las fotos
    FOTOS_EXTENSIONES:         str = "jpg,jpeg,png"  # se prueban en orden para <id_emp>.<ext>

    # ── Validación de foto (estricta, configurable) ───────────────────────────
    FOTO_MIN_WIDTH:        int = 320
    FOTO_MIN_HEIGHT:       int = 320
    FOTO_MAX_BYTES:        int = 8_000_000
    FOTO_FORMATOS:         str = "JPEG,PNG"        # formatos PIL aceptados
    FOTO_DET_SCORE_MIN:    float = 0.65            # umbral de det_score de recognition
    FOTO_EXIGIR_ANTISPOOF: bool = True

    # ── Sincronización / scheduler ────────────────────────────────────────────
    SYNC_ENABLED:          bool = True             # arranca el scheduler interno
    SYNC_INTERVAL_MINUTES: int = 60
    SYNC_RUN_ON_STARTUP:   bool = False
    SYNC_BATCH_SIZE:       int = 500               # tamaño de lote de upsert
    SYNC_RECOG_CONCURRENCY: int = 4                # llamadas paralelas a recognition

    # JWT — employee_monitoring NO emite ni valida tokens; el gateway valida el JWT.
    JWT_SECRET: str | None = os.getenv("JWT_SECRET")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 0
    ROLES_TOKEN_SIN_EXPIRACION: str = "kiosko"
    EMPRESA_ADMIN: int = 99
    GATEWAY_INTERNAL_TOKEN: str = ""  # X-Gateway-Token que inyecta Traefik; vacio = no se exige

    # Microservicio recognition: se le manda la foto para extraer el embedding.
    RECOGNITION_SERVICE_URL: str = "http://recognition:8000"
    RECOGNITION_INTERNAL_TOKEN: str = os.getenv("RECOGNITION_INTERNAL_TOKEN", "")

    @property
    def roles_token_sin_expiracion(self) -> set[str]:
        return {r.strip() for r in self.ROLES_TOKEN_SIN_EXPIRACION.split(",") if r.strip()}

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

    @property
    def sys21_urls(self) -> dict[str, str]:
        """Mapa origen → URL MSSQL (solo los configurados). La 'clave' identifica el origen."""
        urls = {
            "agricola":     self.SYS_21_URL_AGRICOLA,
            "agricola_com": self.SYS_21_URL_AGRICOLA_COM,
        }
        return {origen: url for origen, url in urls.items() if url}

    @property
    def foto_extensiones_list(self) -> list[str]:
        return [e.strip().lower() for e in self.FOTOS_EXTENSIONES.split(",") if e.strip()]

    @property
    def foto_formatos_set(self) -> set[str]:
        return {f.strip().upper() for f in self.FOTO_FORMATOS.split(",") if f.strip()}

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=True)


settings = Settings()
