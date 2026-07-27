# kiosk_local/services/Recognition_Client.py
# Cliente del contenedor recognition LOCAL (mismo código de prod, apuntando a la BD local).
# Le manda la foto y recognition detecta → extrae embedding → match pgvector contra el
# ROSTER LOCAL (motor.buscar_en_bd) → devuelve el trabajador. Token interno compartido.
import logging

import httpx

from src.core.config import settings

logger = logging.getLogger(__name__)


class RecognitionClient:
    def __init__(self) -> None:
        self._client = httpx.Client(base_url=settings.RECOGNITION_URL,
                                    timeout=settings.RECOGNITION_TIMEOUT)

    def _headers(self) -> dict:
        return {"X-Internal-Token": settings.RECOGNITION_INTERNAL_TOKEN}

    def reconocer(self, foto: bytes, id_empresa: int | None, nombre_hint: str | None = None) -> dict:
        """1 foto → pipeline completo (detecta, anti-spoof, match local). Devuelve el
        dict de recognition: {estado: match|no_match|no_rostro|spoof, trabajador?, ...}."""
        data: dict = {}
        if id_empresa is not None:
            data["id_empresa"] = id_empresa
        if nombre_hint:
            data["nombre_hint"] = nombre_hint
        r = self._client.post("/reconocer", headers=self._headers(),
                              files={"foto": ("foto.jpg", foto, "image/jpeg")}, data=data)
        r.raise_for_status()
        return r.json()

    def reconocer_liveness(self, fotos: list[bytes], id_empresa: int | None,
                           nombre_hint: str | None = None) -> dict:
        """N fotos → /reconocer-liveness: valida MOVIMIENTO entre frames (foto estática =
        'no_vivo') + anti-spoof pasivo + match local. Devuelve el dict de recognition
        {estado: match|no_match|no_vivo|spoof|pocos_rostros|baja_calidad, trabajador?, ...}."""
        files = [("fotos", (f"f{i}.jpg", b, "image/jpeg")) for i, b in enumerate(fotos)]
        data: dict = {}
        if id_empresa is not None:
            data["id_empresa"] = id_empresa
        if nombre_hint:
            data["nombre_hint"] = nombre_hint
        r = self._client.post("/reconocer-liveness", headers=self._headers(), files=files, data=data)
        r.raise_for_status()
        return r.json()

    def config(self) -> dict:
        """GET /config del recognition local: umbrales EFECTIVOS (default de env + overrides
        en caliente de parametros_sistema). Para que el front muestre/calibre la config."""
        r = self._client.get("/config", headers=self._headers())
        r.raise_for_status()
        return r.json()

    def disponible(self) -> bool:
        try:
            self._client.get("/health", timeout=5.0).raise_for_status()
            return True
        except Exception:
            return False


recognition_client = RecognitionClient()
