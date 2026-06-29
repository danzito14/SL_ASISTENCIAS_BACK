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
    # Local (PIL):
    FOTO_MIN_WIDTH:        int = 320
    FOTO_MIN_HEIGHT:       int = 320
    FOTO_MAX_BYTES:        int = 8_000_000
    FOTO_FORMATOS:         str = "JPEG,PNG"        # formatos PIL aceptados
    FOTO_BRILLO_MIN:       int = 40               # brillo medio (0-255): rechaza muy oscura
    FOTO_BRILLO_MAX:       int = 225              # rechaza muy clara/quemada
    # Recognition (calidad de la cara). Ajusta los umbrales a tu set de fotos:
    FOTO_DET_SCORE_MIN:    float = 0.65            # confianza de detección de la cara
    FOTO_EXIGIR_UNA_CARA:  bool = True             # rechazar si hay 2+ caras
    FOTO_MIN_FACE_RATIO:   float = 0.05            # área cara / área imagen (cara no lejana)
    FOTO_MAX_YAW:          float = 25.0            # grados de giro izq/der permitidos
    FOTO_MAX_PITCH:        float = 25.0            # grados arriba/abajo permitidos
    FOTO_BLUR_MIN:         float = 50.0            # varianza Laplaciano mínima (nitidez)
    # Anti-spoofing: hoy recognition lo tiene apagado → lo dejamos NO exigible.
    # Ponlo en true cuando actives ANTISPOOFING_ACTIVO en recognition.
    FOTO_EXIGIR_ANTISPOOF: bool = False

    # ── Sincronización / scheduler ────────────────────────────────────────────
    SYNC_ENABLED:          bool = True             # arranca el scheduler interno
    SYNC_RUN_ON_STARTUP:   bool = False            # correr una vez al arrancar (pruebas)
    # Programación por CRON en hora LOCAL. Cada valor son las HORAS (lista cron) en
    # que corre ese origen. Default: comercial 02:00 y 14:00; agrícola 03:00 y 15:00
    # (escalonado 1h para que el origen comercial termine antes que el agrícola).
    SYNC_TZ:               str = "America/Mazatlan"  # Mazatlán/Sinaloa = UTC-7 (sin DST)
    SYNC_CRON_COM:         str = "2,14"            # horas para agricola_com (comercial)
    SYNC_CRON_AGRICOLA:    str = "3,15"            # horas para agricola
    # PRUEBA: si > 0, el comercial corre por INTERVALO de N minutos (en vez del cron),
    # para verificar el scheduler sin esperar la hora. 0 = cron normal (producción).
    SYNC_COM_TEST_INTERVAL_MIN: int = 0
    SYNC_BATCH_SIZE:       int = 500               # tamaño de lote de upsert
    SYNC_RECOG_CONCURRENCY: int = 4                # llamadas paralelas a recognition

    # JWT — employee_monitoring NO emite ni valida tokens; el gateway valida el JWT.
    JWT_SECRET: str | None = os.getenv("JWT_SECRET")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 0
    ROLES_TOKEN_SIN_EXPIRACION: str = "kiosko"
    EMPRESA_ADMIN: int = 99
    GATEWAY_INTERNAL_TOKEN: str = ""  # X-Gateway-Token que inyecta Traefik; vacio = no se exige
    # DEV/PRUEBA: si es true, guard_scopes NO exige identidad ni scopes y usa un
    # principal super-admin. Úsalo solo para probar local sin el gateway. NUNCA en prod.
    AUTH_DISABLED: bool = False

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
