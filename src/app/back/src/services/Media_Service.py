# app/services/media_service.py
"""
Servicio de MEDIA: almacenamiento y resolución de rutas de las fotos protegidas
(incidencias e intentos del scanner).

Concentra en UN solo lugar todo el acoplamiento a disco: es la "costura" para
extraer 'media' como microservicio (object storage / URLs firmadas) sin tocar al
resto del backend. No depende de cv2/numpy: recibe y entrega bytes. El recorte del
rostro (que usa OpenCV) vive en el scanner (dominio recognition); aquí solo se
persiste y se sirve.
"""
import logging
import os

from src.core.config import settings

logger = logging.getLogger(__name__)


class MediaService:

    def guardar_bytes(self, contenido: bytes, subcarpeta: str, nombre: str) -> str | None:
        """
        Guarda los bytes en media/<subcarpeta>/<nombre> y devuelve la URL web
        (p. ej. '/media/incidencias/escaneo_<uuid>.jpg'), o None si falla la escritura.
        """
        carpeta = os.path.join(settings.media_base_dir, subcarpeta)
        os.makedirs(carpeta, exist_ok=True)
        try:
            with open(os.path.join(carpeta, nombre), "wb") as f:
                f.write(contenido)
        except OSError as exc:
            logger.error("No se pudo guardar la imagen en %s/%s: %s", subcarpeta, nombre, exc)
            return None
        return f"{settings.MEDIA_URL}/{subcarpeta}/{nombre}"

    def ruta_archivo(self, ruta_foto: str | None) -> str | None:
        """
        Mapea una URL web de foto ('/media/<sub>/<archivo>') a su ruta ABSOLUTA en
        disco, con defensa anti path-traversal. Devuelve None si no hay foto, si la
        ruta se sale de la carpeta media, o si el archivo no existe.
        """
        if not ruta_foto:
            return None

        rel = ruta_foto
        if rel.startswith(settings.MEDIA_URL):
            rel = rel[len(settings.MEDIA_URL):]
        rel = rel.lstrip("/\\")

        base = os.path.normpath(settings.media_base_dir)
        ruta = os.path.normpath(os.path.join(base, rel))
        # La ruta resuelta debe quedar DENTRO de la carpeta media.
        if not ruta.startswith(base):
            logger.warning("Ruta de foto fuera de media (posible traversal): %s", ruta_foto)
            return None
        return ruta if os.path.isfile(ruta) else None


media_service = MediaService()
