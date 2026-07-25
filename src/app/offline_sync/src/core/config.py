# offline_sync/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # PostgreSQL — offline_sync corre como svc_offline.
    DB_HOST:     str
    DB_PORT:     int
    DB_USER:     str
    DB_PASSWORD: str
    DB_NAME:     str

    APP_TITLE:   str = "Offline Sync Service"
    APP_VERSION: str = "1.0.0"
    DEBUG:       bool = False
    CORS_ORIGINS: str = ""

    # ── Roster ────────────────────────────────────────────────────────────────
    # Tipos de fichaje que un dispositivo puede pedir (área: campo/oficina/empaque).
    ROSTER_TIPOS: str = "campo,oficina,empaque"
    # Regla del roster. False = OPCIÓN A (estricto por tipo_area + permiso 'super').
    # True = además incluye permiso_escaneo='general' (a futuro, cuando se afinen
    # los permisos por área). Cambiarlo es un solo valor de entorno, sin redeploy.
    ROSTER_INCLUIR_GENERAL: bool = False

    # ── Ingesta ───────────────────────────────────────────────────────────────
    INGESTA_MAX_FILAS: int = 50_000   # tope defensivo de filas por CSV

    # ── Enrolamiento (walk-in) ────────────────────────────────────────────────
    ENROL_ORIGEN:    str = "apk"      # origen_nomina de los enrolados en el APK
    EMBEDDING_DIM:   int = 512        # dimensión esperada del vector (buffalo_l)
    ENROL_MODELO_IA: str = "buffalo_l"

    # ── Modelos IA para el APK ────────────────────────────────────────────────
    # El APK NO hornea los .onnx pesados; los baja en el 1er arranque desde
    # GET /off_sync/modelo/{nombre}. Carpeta (montada como volumen) con los .onnx.
    MODELOS_DIR: str = "/models"

    # ── Microservicio media (fotos de evidencia de intentos capturados offline) ─
    # El edge/kiosko sube la foto del intento por POST /off_sync/intentos/foto; este
    # servicio la guarda en 'media' (igual que el scanner online) y pone la ruta en
    # intentos_acceso.ruta_foto. Token interno compartido con media.
    MEDIA_SERVICE_URL:    str = "http://media:8000"
    MEDIA_URL:            str = "/media"   # prefijo web que se guarda en ruta_foto
    MEDIA_INTERNAL_TOKEN: str = ""

    # ── Auth — el gateway valida el JWT; aquí solo se leen headers X-* y scopes ─
    EMPRESA_ADMIN: int = 99
    GATEWAY_INTERNAL_TOKEN: str = ""  # X-Gateway-Token que inyecta Traefik; vacío = no se exige
    # DEV/PRUEBA: si es true, guard_scopes NO exige identidad ni scopes (principal
    # super-admin). Solo para probar local sin el gateway. NUNCA en producción.
    AUTH_DISABLED: bool = False

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def roster_tipos_set(self) -> set[str]:
        return {t.strip().lower() for t in self.ROSTER_TIPOS.split(",") if t.strip()}

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
