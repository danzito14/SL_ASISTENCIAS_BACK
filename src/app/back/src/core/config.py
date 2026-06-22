# app/core/config.py
import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # PostgreSQL
    DB_HOST:     str
    DB_PORT:     int
    DB_USER:     str
    DB_PASSWORD: str
    DB_NAME:     str

    # App
    APP_TITLE:   str
    APP_VERSION: str
    DEBUG:       bool
    # Orígenes CORS extra (dominios del front en producción), separados por comas.
    # Ej: "https://app.midominio.com,https://admin.midominio.com".
    # Los de localhost/LAN ya los permite el regex de main.py.
    CORS_ORIGINS: str = ""

    # Autenticación (JWT). Ya NO se usa aquí: el gateway (identity /validate) valida
    # el token y este servicio confía en los headers X-*. Opcional por compatibilidad.
    JWT_SECRET: str | None = os.getenv("JWT_SECRET")
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 0  # Duración del token (min) para usuarios normales. 0 = NO expira.
    # Roles cuyo token NUNCA expira (lista separada por comas). El kiosko
    # está siempre encendido, así que su token no debe caducar aunque los demás sí.
    ROLES_TOKEN_SIN_EXPIRACION: str = "kiosko"

    # Empresa "comodín": un usuario con este id de empresa es super-admin y puede
    # ver/operar TODAS las empresas (se salta el filtro por empresa).
    EMPRESA_ADMIN: int = 99
    GATEWAY_INTERNAL_TOKEN: str = ""  # X-Gateway-Token que inyecta Traefik; vacio = no se exige

    # Archivos (fotos de incidencias, etc.)
    MEDIA_DIR: str = "media"    # (en desuso: media es dueño del disco) carpeta heredada
    MEDIA_URL: str = "/media"   # prefijo web con el que se guarda la ruta_foto en la BD
    # Microservicio media (almacenamiento/servido de fotos). El backend habla con él
    # por HTTP interno (token compartido); ya no toca el disco directamente.
    MEDIA_SERVICE_URL: str = "http://media:8000"
    MEDIA_INTERNAL_TOKEN: str = os.getenv("MEDIA_INTERNAL_TOKEN", "")

    # Microservicio recognition (motor facial). El backend le manda las imágenes y
    # recibe el resultado + el recorte de cara. Ya no corre InsightFace/OpenCV aquí.
    RECOGNITION_SERVICE_URL: str = "http://recognition:8000"
    RECOGNITION_INTERNAL_TOKEN: str = os.getenv("RECOGNITION_INTERNAL_TOKEN", "")

    # Reconocimiento facial
    PRELOAD_FACE_MODEL: bool = False  # Si True, carga buffalo_l al arrancar

    # Anti-spoofing (Silent-Face / MiniFASNet vía ONNX)
    ANTISPOOFING_ACTIVO: bool = False              # Activa el check anti-spoof en asistencia
    ANTISPOOF_MODEL_DIR: str = "models/antispoof"  # Carpeta con los .onnx (relativa a back_py)
    ANTISPOOF_UMBRAL:    float = 0.0               # Confianza mínima de "real" (0 = solo argmax)
    ANTISPOOF_REAL_INDEX: int = 1                  # Índice de la clase "real" en el softmax (calibrar)
    ANTISPOOF_DIV255: bool = True                  # /255 (garciafido/original). yakhyo NO divide → false

    @property
    def media_base_dir(self) -> str:
        """Ruta ABSOLUTA de la carpeta de media. Si MEDIA_DIR es relativo, se ancla
        a la raíz de back_py (este archivo está en back_py/src/core/)."""
        base = self.MEDIA_DIR
        if os.path.isabs(base):
            return base
        raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(raiz, base)

    @property
    def roles_token_sin_expiracion(self) -> set[str]:
        """Nombres de rol cuyo token no expira (parseados de ROLES_TOKEN_SIN_EXPIRACION)."""
        return {r.strip() for r in self.ROLES_TOKEN_SIN_EXPIRACION.split(",") if r.strip()}

    @property
    def cors_origins_list(self) -> list[str]:
        """Orígenes CORS extra (parseados de CORS_ORIGINS, separados por comas)."""
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