# media/core/config.py
import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_TITLE:   str = "Media Service"
    APP_VERSION: str = "1.0.0"
    DEBUG:       bool = False

    # Carpeta de almacenamiento (se monta como volumen). MEDIA_URL = prefijo web con
    # que se guarda la ruta en la BD del resto de servicios (ej. /media/incidencias/x.jpg).
    MEDIA_DIR: str = "data"
    MEDIA_URL: str = "/media"

    # Secreto compartido para la API interna (solo el backend la llama). Fail-closed:
    # si está vacío, se rechaza todo.
    MEDIA_INTERNAL_TOKEN: str = os.getenv("MEDIA_INTERNAL_TOKEN", "")

    @property
    def media_base_dir(self) -> str:
        """Ruta ABSOLUTA de la carpeta de media. Si MEDIA_DIR es relativo, se ancla a
        la raíz del servicio (este archivo está en media/src/core/)."""
        base = self.MEDIA_DIR
        if os.path.isabs(base):
            return base
        raiz = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return os.path.join(raiz, base)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )


settings = Settings()
