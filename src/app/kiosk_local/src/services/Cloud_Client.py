# kiosk_local/services/Cloud_Client.py
# Cliente de la NUBE (gateway de prod). Hace login como el usuario kiosko (define la
# empresa) y baja el roster de offline_sync. Cachea el token (el rol escaneador emite
# token SIN expiración). Es la ÚNICA parte que necesita internet; una vez bajado el
# roster, el kiosko opera offline.
import logging
import threading

import httpx

from src.core.config import settings

logger = logging.getLogger(__name__)


class CloudClient:
    def __init__(self) -> None:
        self._token: str | None = None
        self._lock = threading.Lock()
        self._client = httpx.Client(base_url=settings.CLOUD_BASE_URL, timeout=settings.HTTP_TIMEOUT)

    def _login(self) -> None:
        r = self._client.post("/usuarios/login", json={
            "nombre_usuario": settings.KIOSK_USER,
            "contrasena": settings.KIOSK_PASSWORD,
        })
        r.raise_for_status()
        self._token = r.json()["access_token"]
        logger.info("cloud: login OK como %s", settings.KIOSK_USER)

    def _token_asegurar(self) -> str:
        with self._lock:
            if self._token is None:
                self._login()
            return self._token

    def _invalidar(self) -> None:
        with self._lock:
            self._token = None

    def _get(self, path: str, params: dict | None = None) -> dict:
        for intento in (1, 2):
            token = self._token_asegurar()
            r = self._client.get(path, params=params or {},
                                 headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 401 and intento == 1:
                self._invalidar()
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("cloud: no se pudo autenticar tras reintentar.")

    def bajar_roster(self, tipo: str, id_empresa: int | None = None) -> dict:
        """GET /off_sync/roster?tipo=&id_empresa= → dict con trabajadores+embeddings+áreas+puertas."""
        params: dict = {"tipo": tipo}
        if id_empresa is not None:
            params["id_empresa"] = id_empresa
        return self._get("/off_sync/roster", params)

    def acceso_nube(self, foto: bytes, id_puerta: int, tipo_registro: str = "entrada") -> dict:
        """FALLBACK: cuando no hay match LOCAL y hay internet, se reenvía la foto al scanner
        de la NUBE (POST /scanner/acceso/foto), que reconoce contra TODO el roster de la
        empresa y REGISTRA allá. Devuelve el ScanResponse de la nube."""
        params = {"id_puerta": id_puerta, "tipo_registro": tipo_registro}
        for intento in (1, 2):
            token = self._token_asegurar()
            r = self._client.post("/scanner/acceso/foto", params=params,
                                  files={"foto": ("foto.jpg", foto, "image/jpeg")},
                                  headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 401 and intento == 1:
                self._invalidar()
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("cloud: no se pudo autenticar para el fallback.")

    def subir_asistencias(self, csv_bytes: bytes) -> dict:
        """Sube la cola de escaneos a la nube (POST /off_sync/asistencias, CSV). La nube
        inserta escaneos (idempotente por UUID) + deriva entrada/salida + consolida.
        Devuelve IngestaResponse {insertados, duplicados, rechazados[]}."""
        for intento in (1, 2):
            token = self._token_asegurar()
            r = self._client.post("/off_sync/asistencias",
                                  files={"archivo": ("asistencias.csv", csv_bytes, "text/csv")},
                                  headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 401 and intento == 1:
                self._invalidar()
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("cloud: no se pudo autenticar para subir la cola.")

    def hay_conexion(self) -> bool:
        try:
            self._client.get("/off_sync/estado",
                             headers={"Authorization": f"Bearer {self._token_asegurar()}"},
                             timeout=5.0).raise_for_status()
            return True
        except Exception:
            return False


cloud_client = CloudClient()
