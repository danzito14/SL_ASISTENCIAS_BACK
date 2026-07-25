# offline_sync/services/Media_Client.py
# Cliente del microservicio MEDIA para guardar la foto de evidencia de un intento
# capturado offline. Mismo contrato que el scanner online: PUT /archivos/{sub}/{nombre}
# con los bytes crudos (image/jpeg) y token interno; media devuelve la {ruta} web
# (/media/...) que va a intentos_acceso.ruta_foto. media no tiene BD: solo almacena bytes.
import logging

import requests

from src.core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 10


class MediaClient:

    def guardar_bytes(self, contenido: bytes, subcarpeta: str, nombre: str) -> str | None:
        """Sube los bytes a media y devuelve la ruta web (/media/...) o None si falla."""
        url = f"{settings.MEDIA_SERVICE_URL}/archivos/{subcarpeta}/{nombre}"
        try:
            r = requests.put(
                url, data=contenido,
                headers={"X-Internal-Token": settings.MEDIA_INTERNAL_TOKEN,
                         "Content-Type": "image/jpeg"},
                timeout=_TIMEOUT,
            )
            r.raise_for_status()
            return r.json().get("ruta")
        except requests.RequestException as exc:
            logger.error("media: no se pudo guardar %s/%s: %s", subcarpeta, nombre, exc)
            return None


media_client = MediaClient()
