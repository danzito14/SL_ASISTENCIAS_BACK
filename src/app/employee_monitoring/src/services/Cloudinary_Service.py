# employee_monitoring/services/Cloudinary_Service.py
"""
Copia en Cloudinary de las fotos de trabajadores que el sync ACEPTÓ (pasaron las
validaciones y generaron su embedding), para poder consultarlas después.

Destino: <CLODINARY_CARPETA>/<origen>/<id_emp> (p. ej. SL-Asistencias/agricola/99164).
El public_id es fijo por empleado → si su foto cambia, se REEMPLAZA (overwrite) e
invalida la caché del CDN. Subida firmada por la API REST (sin SDK).
"""
import hashlib
import logging
import time

import requests

from src.core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 60


class CloudinaryClient:

    @property
    def activo(self) -> bool:
        return settings.cloudinary_activo

    def _firma(self, params: dict[str, str]) -> str:
        """SHA-1 de 'k1=v1&k2=v2…' (orden alfabético) + api_secret (firma de Cloudinary)."""
        cadena = "&".join(f"{k}={params[k]}" for k in sorted(params))
        return hashlib.sha1((cadena + settings.API_SECRET_CLODINARY).encode("utf-8")).hexdigest()

    def subir_foto_trabajador(self, foto_bytes: bytes, origen: str, id_emp: str) -> str | None:
        """Sube (o reemplaza) la foto del empleado. Devuelve la URL https, o None si falla."""
        if not self.activo:
            return None
        params = {
            "folder": f"{settings.CLODINARY_CARPETA.strip('/')}/{origen}",
            "public_id": str(id_emp).strip(),
            "overwrite": "true",
            "invalidate": "true",
            "timestamp": str(int(time.time())),
        }
        datos = {**params, "api_key": settings.API_KEY_CLODINARY, "signature": self._firma(params)}
        url = f"https://api.cloudinary.com/v1_1/{settings.CLOUD_NAME_CLODINARY}/image/upload"
        try:
            r = requests.post(url, data=datos, files={"file": (f"{id_emp}.jpg", foto_bytes)},
                              timeout=_TIMEOUT)
            if r.status_code != 200:
                # El cuerpo trae {"error": {"message": ...}}: útil para credenciales mal puestas.
                logger.error("cloudinary: %s/%s → HTTP %s: %s", origen, id_emp, r.status_code, r.text[:300])
                return None
            return r.json().get("secure_url")
        except requests.RequestException as exc:
            logger.error("cloudinary: fallo subiendo %s/%s: %s", origen, id_emp, exc)
            return None


cloudinary_service = CloudinaryClient()
