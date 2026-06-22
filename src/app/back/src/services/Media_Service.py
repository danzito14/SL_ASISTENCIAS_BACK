# app/services/media_service.py
"""
Cliente del microservicio MEDIA (almacenamiento/servido de fotos protegidas).

media es un servicio aparte, dueño del disco/object storage. Este cliente habla
con él por HTTP interno (token compartido): guarda y recupera bytes. El backend
sigue siendo el GUARDIÁN de auth+empresa de las fotos (sabe a qué incidencia/intento
pertenece cada una); media solo almacena/sirve bytes y no tiene BD.

(Antes esto era acceso a disco directo; ahora es la frontera con el servicio media.)
"""
import logging

import requests

from src.core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 10  # segundos


class MediaService:

    def _headers(self) -> dict:
        return {"X-Internal-Token": settings.MEDIA_INTERNAL_TOKEN}

    def _sub_nombre(self, ruta_foto: str) -> tuple[str, str] | None:
        """De '/media/incidencias/x.jpg' -> ('incidencias', 'x.jpg'); None si no encaja."""
        rel = ruta_foto
        if rel.startswith(settings.MEDIA_URL):
            rel = rel[len(settings.MEDIA_URL):]
        rel = rel.lstrip("/\\")
        partes = rel.split("/", 1)
        if len(partes) != 2 or not partes[0] or not partes[1]:
            return None
        return partes[0], partes[1]

    def guardar_bytes(self, contenido: bytes, subcarpeta: str, nombre: str) -> str | None:
        """
        Sube los bytes al servicio media y devuelve la URL web a guardar en la BD
        (p. ej. '/media/incidencias/escaneo_<uuid>.jpg'), o None si falla.
        """
        url = f"{settings.MEDIA_SERVICE_URL}/archivos/{subcarpeta}/{nombre}"
        try:
            r = requests.put(
                url, data=contenido,
                headers={**self._headers(), "Content-Type": "image/jpeg"},
                timeout=_TIMEOUT,
            )
            r.raise_for_status()
            return r.json().get("ruta")
        except requests.RequestException as exc:
            logger.error("media: no se pudo guardar %s/%s: %s", subcarpeta, nombre, exc)
            return None

    def obtener_bytes(self, ruta_foto: str | None) -> bytes | None:
        """
        Recupera los bytes de una foto por su ruta web (la que está en la BD).
        None si no hay foto, la ruta no encaja, o media responde 404.
        """
        if not ruta_foto:
            return None
        sn = self._sub_nombre(ruta_foto)
        if sn is None:
            logger.warning("media: ruta_foto con formato inesperado: %s", ruta_foto)
            return None
        url = f"{settings.MEDIA_SERVICE_URL}/archivos/{sn[0]}/{sn[1]}"
        try:
            r = requests.get(url, headers=self._headers(), timeout=_TIMEOUT)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except requests.RequestException as exc:
            logger.error("media: no se pudo obtener %s: %s", ruta_foto, exc)
            return None


media_service = MediaService()
