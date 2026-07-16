# vigilancia/capture/scanner_client.py
# Cliente del scanner del back. vigilancia es DELGADO: manda los frames capturados al
# scanner (POST /scanner/acceso/foto|liveness) por el GATEWAY, autenticado como cuenta
# de servicio (rol vigilancia_edge, scanner:use). El scanner reusa recognition +
# anti-spoof + escribe escaneos + consolida; aquí solo se recibe el ScanResponse.
import logging
import threading

import httpx

from src.core.config import settings

logger = logging.getLogger(__name__)


class ScannerClient:
    def __init__(self) -> None:
        self._token: str | None = None
        self._lock = threading.Lock()  # login/token compartido entre hilos de cámara
        self._client = httpx.Client(base_url=settings.SCANNER_BASE_URL, timeout=settings.SCANNER_TIMEOUT)

    def _login(self) -> None:
        r = self._client.post("/usuarios/login", json={
            "nombre_usuario": settings.VIGILANCIA_SERVICE_USER,
            "contrasena": settings.VIGILANCIA_SERVICE_PASSWORD,
        })
        r.raise_for_status()
        self._token = r.json()["access_token"]
        logger.info("scanner_client: login OK como %s", settings.VIGILANCIA_SERVICE_USER)

    def _asegurar_token(self) -> str:
        with self._lock:
            if self._token is None:
                self._login()
            return self._token

    def _invalidar(self) -> None:
        with self._lock:
            self._token = None

    def _files(self, frames: list[bytes]) -> tuple[str, list]:
        """Arma el multipart. Con liveness va el campo 'fotos' (N); si no, 'foto' (1)."""
        if settings.SCANNER_USAR_LIVENESS and len(frames) >= 2:
            return "/scanner/acceso/liveness", [
                ("fotos", (f"f{i}.jpg", fr, "image/jpeg")) for i, fr in enumerate(frames)
            ]
        return "/scanner/acceso/foto", [("foto", ("f0.jpg", frames[0], "image/jpeg"))]

    def enviar(self, frames: list[bytes], id_puerta: int, tipo_registro: str = "entrada",
               id_dispositivo: int | None = None, nombre_hint: str | None = None) -> dict:
        """POST al scanner. Devuelve el ScanResponse (dict). Reintenta 1 vez si el token expiró.

        nombre_hint: nombre 'sucio' que el terminal detectó (evento). El scanner lo
        reenvía a recognition para ACOTAR la búsqueda facial (indicio, no identidad).
        """
        if not frames:
            raise ValueError("Sin frames para enviar al scanner.")
        params: dict = {"id_puerta": id_puerta, "tipo_registro": tipo_registro}
        if id_dispositivo is not None:
            params["id_dispositivo"] = id_dispositivo
        if nombre_hint:
            params["nombre_hint"] = nombre_hint

        for intento in (1, 2):
            path, files = self._files(frames)  # rehacer files por intento (httpx los consume)
            token = self._asegurar_token()
            r = self._client.post(path, params=params, files=files,
                                  headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 401 and intento == 1:
                logger.info("scanner_client: 401, re-login y reintento.")
                self._invalidar()
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("scanner_client: no se pudo autenticar tras reintentar.")

    def cerrar(self) -> None:
        self._client.close()


# Singleton compartido por todos los hilos de cámara (httpx.Client es thread-safe).
scanner_client = ScannerClient()
