# workers/core/config.py
import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # PostgreSQL — workers se conecta como svc_workers (dueño de trabajadores/embeddings;
    # con SELECT sobre area_trabajo de tenancy para validar el área).
    DB_HOST:     str
    DB_PORT:     int
    DB_USER:     str
    DB_PASSWORD: str
    DB_NAME:     str

    APP_TITLE:   str = "Workers Service"
    APP_VERSION: str = "1.0.0"
    DEBUG:       bool = False
    CORS_ORIGINS: str = ""

    # JWT — workers NO emite tokens; valida (stateless) el de identity.
    JWT_SECRET: str | None = os.getenv("JWT_SECRET")  # ya NO se usa aqui; el gateway valida el JWT
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 0
    ROLES_TOKEN_SIN_EXPIRACION: str = "kiosko"
    EMPRESA_ADMIN: int = 99
    GATEWAY_INTERNAL_TOKEN: str = ""  # X-Gateway-Token que inyecta Traefik; vacio = no se exige

    # Microservicio recognition: workers le manda la foto para extraer el embedding.
    RECOGNITION_SERVICE_URL: str = "http://recognition:8000"
    RECOGNITION_INTERNAL_TOKEN: str = os.getenv("RECOGNITION_INTERNAL_TOKEN", "")

    # Cloudinary: copia de la foto ACEPTADA al registrar/actualizar un rostro desde
    # el panel. Mismas credenciales y carpeta que employee_monitoring. Si falta
    # alguna de las 3, no se sube (el rostro se registra igual).
    CLOUD_NAME_CLODINARY: str = ""
    API_KEY_CLODINARY: str = ""
    API_SECRET_CLODINARY: str = ""
    CLODINARY_CARPETA: str = "SL-Asistencias"

    @property
    def cloudinary_activo(self) -> bool:
        return bool(self.CLOUD_NAME_CLODINARY and self.API_KEY_CLODINARY and self.API_SECRET_CLODINARY)

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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", case_sensitive=True)


settings = Settings()
