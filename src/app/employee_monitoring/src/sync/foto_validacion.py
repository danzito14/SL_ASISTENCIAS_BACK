# employee_monitoring/sync/foto_validacion.py
"""
Validación LOCAL y barata de la foto, ANTES de mandarla a recognition (ahorra
llamadas HTTP). Reglas estrictas configurables por .env (formato, resolución
mínima, tamaño máximo, archivo no corrupto).

La validación del ROSTRO (una sola cara, det_score, anti-spoofing) la hace
recognition; aquí solo se filtra lo que no vale la pena enviar.

Devuelve (ok, motivo): si ok es False, motivo es uno canónico de FotoPendiente.MOTIVOS.
"""
import io
import logging

from PIL import Image, ImageStat

from src.core.config import settings

logger = logging.getLogger(__name__)


def validar_foto_local(foto_bytes: bytes | None) -> tuple[bool, str | None]:
    """Aplica las reglas locales. (True, None) si pasa; (False, motivo) si no."""
    if not foto_bytes:
        return False, "archivo_corrupto"

    if len(foto_bytes) > settings.FOTO_MAX_BYTES:
        return False, "archivo_grande"

    # 1) Integridad: verify() detecta archivos truncados/corruptos. Tras verify()
    #    la imagen queda inutilizable, así que se reabre para leer formato/tamaño.
    try:
        Image.open(io.BytesIO(foto_bytes)).verify()
        img = Image.open(io.BytesIO(foto_bytes))
    except Exception:  # noqa: BLE001 — cualquier fallo de PIL = imagen no usable
        return False, "archivo_corrupto"

    # 2) Formato permitido (JPEG/PNG por defecto).
    if (img.format or "").upper() not in settings.foto_formatos_set:
        return False, "formato_invalido"

    # 3) Resolución mínima.
    ancho, alto = img.size
    if ancho < settings.FOTO_MIN_WIDTH or alto < settings.FOTO_MIN_HEIGHT:
        return False, "resolucion_baja"

    # 4) Brillo: ni muy oscura ni quemada (promedio en escala de grises 0-255).
    brillo = ImageStat.Stat(img.convert("L")).mean[0]
    if brillo < settings.FOTO_BRILLO_MIN:
        return False, "muy_oscura"
    if brillo > settings.FOTO_BRILLO_MAX:
        return False, "muy_clara"

    return True, None
