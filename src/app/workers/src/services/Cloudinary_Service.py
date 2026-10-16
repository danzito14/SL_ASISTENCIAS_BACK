# workers/services/Cloudinary_Service.py
"""
Copia en Cloudinary de la foto ACEPTADA al registrar/actualizar el rostro de un
trabajador desde el panel, para consultarla después (trabajadores.foto_url).

Destino (mismo esquema que el sync SYS21 de employee_monitoring, así cada trabajador
tiene UNA foto y la última gana):
  · de nómina:     <CARPETA>/<origen_nomina>/<id_emp>
  · alta manual:   <CARPETA>/manual/<id_trabajador>
Subida firmada por la API REST (sin SDK). Si falla, el rostro queda registrado igual
y foto_url se queda como estaba.
"""
import hashlib
import logging
import time
from datetime import datetime, timezone

import requests
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core.config import settings
from src.models.AreaTrabajo_Trabajador_Model import Trabajador

logger = logging.getLogger(__name__)

_TIMEOUT = 60


def _firma(params: dict[str, str]) -> str:
    """SHA-1 de 'k1=v1&k2=v2…' (orden alfabético) + api_secret (firma de Cloudinary)."""
    cadena = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return hashlib.sha1((cadena + settings.API_SECRET_CLODINARY).encode("utf-8")).hexdigest()


def _destino(trabajador: Trabajador) -> tuple[str, str]:
    """(carpeta, public_id) del trabajador en Cloudinary."""
    base = settings.CLODINARY_CARPETA.strip("/")
    if trabajador.id_emp and trabajador.origen_nomina:
        return f"{base}/{trabajador.origen_nomina}", str(trabajador.id_emp).strip()
    return f"{base}/manual", str(trabajador.id_trabajador)


def subir(foto_bytes: bytes, carpeta: str, public_id: str) -> str | None:
    """Sube (o reemplaza) la imagen. Devuelve la URL https, o None si falla/no hay credenciales."""
    if not settings.cloudinary_activo:
        return None
    params = {
        "folder": carpeta,
        "public_id": public_id,
        "overwrite": "true",
        "invalidate": "true",
        "timestamp": str(int(time.time())),
    }
    datos = {**params, "api_key": settings.API_KEY_CLODINARY, "signature": _firma(params)}
    url = f"https://api.cloudinary.com/v1_1/{settings.CLOUD_NAME_CLODINARY}/image/upload"
    try:
        r = requests.post(url, data=datos, files={"file": (f"{public_id}.jpg", foto_bytes)},
                          timeout=_TIMEOUT)
        if r.status_code != 200:
            logger.error("cloudinary: %s/%s → HTTP %s: %s", carpeta, public_id, r.status_code, r.text[:300])
            return None
        return r.json().get("secure_url")
    except requests.RequestException as exc:
        logger.error("cloudinary: fallo subiendo %s/%s: %s", carpeta, public_id, exc)
        return None


def guardar_foto_trabajador(db: Session, trabajador: Trabajador, foto_bytes: bytes) -> str | None:
    """
    Sube la foto aceptada y guarda su URL en trabajadores.foto_url. Si el trabajador es
    de nómina, marca también sync_estado.foto_url: así el sync la da por copiada y no la
    pisa con la del SFTP (solo la reemplaza si allá aparece una foto NUEVA).
    Devuelve la URL o None (nunca lanza: el rostro ya quedó registrado).
    """
    carpeta, public_id = _destino(trabajador)
    url = subir(foto_bytes, carpeta, public_id)
    if not url:
        return None
    try:
        ahora = datetime.now(timezone.utc)
        trabajador.foto_url = url
        trabajador.foto_subida_en = ahora
        if trabajador.id_emp and trabajador.origen_nomina:
            db.execute(
                text("UPDATE sync_estado SET foto_url = :url, foto_subida_en = :ahora "
                     "WHERE id_emp = :id_emp AND origen_nomina = :origen"),
                {"url": url, "ahora": ahora, "id_emp": trabajador.id_emp,
                 "origen": trabajador.origen_nomina},
            )
        db.commit()
        db.refresh(trabajador)
    except Exception as exc:  # noqa: BLE001 — la foto ya está en Cloudinary; no tumbar la respuesta
        db.rollback()
        logger.error("cloudinary: subida OK pero no se guardó la URL de %s: %s", public_id, exc)
    return url
