# media/almacen.py
"""
Almacenamiento de archivos en disco con defensa anti path-traversal.

Único acoplamiento a disco del sistema (la "costura" de media). Para pasar a
object storage (S3/MinIO) en el futuro, se reimplementa aquí sin tocar a nadie más.
"""
import logging
import os
import re
import time

from src.core.config import settings

logger = logging.getLogger(__name__)

# Un segmento válido (subcarpeta o nombre): letras/números/._- sin '/', sin '..'.
_SEG = re.compile(r"^[A-Za-z0-9._-]+$")


def _seguro(seg: str) -> bool:
    return bool(seg) and seg not in (".", "..") and _SEG.match(seg) is not None


def _ruta_abs(subcarpeta: str, nombre: str) -> str | None:
    """Resuelve la ruta ABSOLUTA validando segmentos y que quede DENTRO de media."""
    if not (_seguro(subcarpeta) and _seguro(nombre)):
        logger.warning("Segmento inválido: %r/%r", subcarpeta, nombre)
        return None
    base = os.path.normpath(settings.media_base_dir)
    ruta = os.path.normpath(os.path.join(base, subcarpeta, nombre))
    if not ruta.startswith(base):  # defensa anti path-traversal
        logger.warning("Ruta fuera de media (traversal): %s/%s", subcarpeta, nombre)
        return None
    return ruta


def guardar(subcarpeta: str, nombre: str, contenido: bytes) -> str | None:
    """Escribe los bytes en <media>/<subcarpeta>/<nombre> y devuelve la URL web, o None."""
    ruta = _ruta_abs(subcarpeta, nombre)
    if ruta is None:
        return None
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    try:
        with open(ruta, "wb") as f:
            f.write(contenido)
    except OSError as exc:
        logger.error("No se pudo guardar %s/%s: %s", subcarpeta, nombre, exc)
        return None
    return f"{settings.MEDIA_URL}/{subcarpeta}/{nombre}"


def ruta_archivo(subcarpeta: str, nombre: str) -> str | None:
    """Ruta ABSOLUTA del archivo si existe (y es seguro), o None."""
    ruta = _ruta_abs(subcarpeta, nombre)
    return ruta if (ruta and os.path.isfile(ruta)) else None


def purgar_antiguos(dias: int, subcarpetas: list[str]) -> dict[str, int]:
    """
    Borra los archivos con más de `dias` de antigüedad en las subcarpetas indicadas.

    Se decide por la FECHA DEL ARCHIVO (mtime) y no consultando la base: media no tiene
    BD ni sabe a qué incidencia pertenece cada imagen, y esa independencia es lo que
    permite cambiar el almacenamiento sin tocar al resto. La contrapartida es que la
    limpieza de las columnas 'ruta_foto' va por su lado (job de pg_cron), con la misma
    ventana de días.

    dias <= 0 desactiva la purga. Devuelve {borrados, errores}.
    """
    if dias <= 0:
        return {"borrados": 0, "errores": 0}

    limite = time.time() - dias * 86400
    borrados = errores = 0
    base = os.path.normpath(settings.media_base_dir)

    for sub in subcarpetas:
        if not _seguro(sub):
            logger.warning("Subcarpeta de purga inválida, se omite: %r", sub)
            continue
        carpeta = os.path.join(base, sub)
        if not os.path.isdir(carpeta):
            continue
        for nombre in os.listdir(carpeta):
            ruta = os.path.join(carpeta, nombre)
            try:
                if not os.path.isfile(ruta) or os.path.getmtime(ruta) >= limite:
                    continue
                os.remove(ruta)
                borrados += 1
            except OSError as exc:
                errores += 1
                logger.warning("No se pudo borrar %s: %s", ruta, exc)

    if borrados or errores:
        logger.info("Purga de fotos (>%d días): %d borradas, %d errores.", dias, borrados, errores)
    return {"borrados": borrados, "errores": errores}
