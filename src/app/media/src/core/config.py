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

    # ── Retención de fotos ────────────────────────────────────────────────────
    # Las fotos de incidencias e intentos son evidencia puntual y dato biométrico:
    # se conservan un mes y se borran. El REGISTRO (la incidencia, el intento) se
    # queda para siempre; lo que se elimina es la imagen. Minimiza el daño de un robo
    # del equipo y el volumen del disco, que crece con cada rostro no reconocido.
    # 0 = no borrar nunca.
    MEDIA_RETENCION_DIAS: int = 30
    # Solo estas subcarpetas se purgan. Se listan explícitamente para que, si mañana
    # se guarda aquí algo que deba conservarse, no desaparezca por barrido.
    MEDIA_PURGA_SUBCARPETAS: str = "incidencias,intentos"
    # Cada cuánto barre (el servicio corre siempre; no hay cron en este contenedor).
    MEDIA_PURGA_INTERVALO_HORAS: float = 24.0

    @property
    def purga_subcarpetas(self) -> list[str]:
        return [s.strip() for s in self.MEDIA_PURGA_SUBCARPETAS.split(",") if s.strip()]

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
