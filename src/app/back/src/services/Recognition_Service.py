# app/services/recognition_service.py
"""
Cliente del microservicio RECOGNITION (motor facial compute-heavy).

El reconocimiento (InsightFace + anti-spoof + match pgvector) vive en un servicio
aparte. Este cliente le manda la(s) imagen(es) por HTTP interno (token compartido)
y recibe un resultado COARSE: estado + datos del match + el recorte de cara en
base64. El backend (access) solo orquesta el registro; ya no necesita OpenCV.
"""
import logging

import requests

from src.core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT = 30  # recognition es pesado; margen amplio


class RecognitionClient:

    def _headers(self) -> dict:
        return {"X-Internal-Token": settings.RECOGNITION_INTERNAL_TOKEN}

    def _post(self, ruta: str, files, data: dict | None = None) -> dict | None:
        url = f"{settings.RECOGNITION_SERVICE_URL}{ruta}"
        try:
            r = requests.post(url, files=files, data=data or {}, headers=self._headers(), timeout=_TIMEOUT)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as exc:
            logger.error("recognition: fallo en %s: %s", ruta, exc)
            return None

    def reconocer(self, foto_bytes: bytes, id_empresa: int | None, nombre_hint: str | None = None) -> dict | None:
        """1 imagen → pipeline completo (estado, trabajador/candidato, recorte_b64).

        nombre_hint (opcional): nombre 'sucio' que un terminal/cámara detectó, para
        ACOTAR la búsqueda facial a los trabajadores cuyo nombre coincida (indicio,
        no identificador). Si no coincide con nadie, recognition cae a búsqueda total.
        """
        data = {} if id_empresa is None else {"id_empresa": id_empresa}
        if nombre_hint:
            data["nombre_hint"] = nombre_hint
        return self._post("/reconocer", files={"foto": ("foto.jpg", foto_bytes, "image/jpeg")}, data=data)

    def reconocer_liveness(self, fotos_bytes: list[bytes], id_empresa: int | None,
                           nombre_hint: str | None = None) -> dict | None:
        """N imágenes → liveness + match. nombre_hint: ver reconocer()."""
        files = [("fotos", (f"f{i}.jpg", b, "image/jpeg")) for i, b in enumerate(fotos_bytes)]
        data = {} if id_empresa is None else {"id_empresa": id_empresa}
        if nombre_hint:
            data["nombre_hint"] = nombre_hint
        return self._post("/reconocer-liveness", files=files, data=data)

    def extraer(self, foto_bytes: bytes) -> dict | None:
        """1 imagen → embedding + scores (para enrolamiento)."""
        return self._post("/extraer", files={"foto": ("foto.jpg", foto_bytes, "image/jpeg")})

    def identificar(self, foto_bytes: bytes, id_empresa: int | None = None) -> dict | None:
        """1 imagen → match (sin registrar)."""
        data = {} if id_empresa is None else {"id_empresa": id_empresa}
        return self._post("/identificar", files={"foto": ("foto.jpg", foto_bytes, "image/jpeg")}, data=data)


recognition_service = RecognitionClient()
