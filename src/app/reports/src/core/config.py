# reports/core/config.py
import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # PostgreSQL — reports se conecta como svc_reports (SOLO LECTURA de todo;
    # idealmente apuntando a una réplica).
    DB_HOST:     str
    DB_PORT:     int
    DB_USER:     str
    DB_PASSWORD: str
    DB_NAME:     str

    APP_TITLE:   str = "Reports Service"
    APP_VERSION: str = "1.0.0"
    DEBUG:       bool = False
    CORS_ORIGINS: str = ""

    # JWT — reports NO emite tokens; valida (stateless) el de identity.
    JWT_SECRET: str | None = os.getenv("JWT_SECRET")  # ya NO se usa aqui; el gateway valida el JWT
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 0
    ROLES_TOKEN_SIN_EXPIRACION: str = "kiosko"
    EMPRESA_ADMIN: int = 99
    GATEWAY_INTERNAL_TOKEN: str = ""  # X-Gateway-Token que inyecta Traefik; vacio = no se exige

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
