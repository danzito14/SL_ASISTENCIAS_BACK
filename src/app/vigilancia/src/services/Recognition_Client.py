# vigilancia/services/Recognition_Client.py
# Cliente del microservicio recognition (mismo motor facial de asistencia) para el PASO
# DEL ROSTRO del reid: manda un recorte a POST /identificar (match SIN registrar asistencia
# y SIN anti-spoof) → devuelve el trabajador si reconoce. API interna con token compartido.
import httpx

from src.core.config import settings


class RecognitionClient:
    def __init__(self) -> None:
        self._client = httpx.Client(base_url=settings.RECOGNITION_URL,
                                    timeout=settings.RECOGNITION_TIMEOUT)

    def identificar(self, foto: bytes, id_empresa: int | None = None) -> dict:
        """POST /identificar. Devuelve {reconocido, trabajador?, similitud?, det_score?, estado?}."""
        data = {"id_empresa": str(id_empresa)} if id_empresa is not None else {}
        r = self._client.post(
            "/identificar",
            headers={"X-Internal-Token": settings.RECOGNITION_INTERNAL_TOKEN},
            files={"foto": ("rostro.jpg", foto, "image/jpeg")},
            data=data,
        )
        r.raise_for_status()
        return r.json()


recognition_client = RecognitionClient()
