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
        # True = el token lo puso el front (usuario logueado); False = login de respaldo
        # con KIOSK_USER. Si un token EXTERNO da 401, NO se cae al login de respaldo (sería
        # otra empresa): mejor fallar y que el front vuelva a iniciar sesión.
        self._token_externo = False
        self._lock = threading.Lock()
        self._client = httpx.Client(base_url=settings.CLOUD_BASE_URL, timeout=settings.HTTP_TIMEOUT)

    def set_token(self, token: str) -> None:
        """Fija el token del usuario logueado en el front (reenviado por /kiosk/roster/sync).
        Con esto la estación SIGUE al usuario: el roster y la subida salen de SU empresa.
        El rol escaneador emite token sin expiración → sirve para el loop de subida y
        sobrevive reinicios (se persiste en kiosk_meta y se recarga al arrancar)."""
        with self._lock:
            self._token = token
            self._token_externo = True

    def token_actual(self) -> str | None:
        with self._lock:
            return self._token

    def _login(self) -> None:
        r = self._client.post("/usuarios/login", json={
            "nombre_usuario": settings.KIOSK_USER,
            "contrasena": settings.KIOSK_PASSWORD,
        })
        r.raise_for_status()
        self._token = r.json()["access_token"]
        self._token_externo = False
        logger.info("cloud: login OK como %s (respaldo)", settings.KIOSK_USER)

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
            if r.status_code == 401 and intento == 1 and not self._token_externo:
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
            if r.status_code == 401 and intento == 1 and not self._token_externo:
                self._invalidar()
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("cloud: no se pudo autenticar para el fallback.")

    def acceso_nube_liveness(self, fotos: list[bytes], id_puerta: int, tipo_registro: str = "entrada") -> dict:
        """FALLBACK liveness: sin match LOCAL y con internet, reenvía la RÁFAGA al scanner
        de la nube (POST /scanner/acceso/liveness), que valida liveness + reconoce contra
        TODA la empresa y registra allá. Devuelve el ScanResponse de la nube."""
        params = {"id_puerta": id_puerta, "tipo_registro": tipo_registro}
        files = [("fotos", (f"f{i}.jpg", b, "image/jpeg")) for i, b in enumerate(fotos)]
        for intento in (1, 2):
            token = self._token_asegurar()
            r = self._client.post("/scanner/acceso/liveness", params=params, files=files,
                                  headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 401 and intento == 1 and not self._token_externo:
                self._invalidar()
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("cloud: no se pudo autenticar para el fallback liveness.")

    def subir_asistencias(self, csv_bytes: bytes) -> dict:
        """Sube la cola de escaneos a la nube (POST /off_sync/asistencias, CSV). La nube
        inserta escaneos (idempotente por UUID) + deriva entrada/salida + consolida.
        Devuelve IngestaResponse {insertados, duplicados, rechazados[]}."""
        for intento in (1, 2):
            token = self._token_asegurar()
            r = self._client.post("/off_sync/asistencias",
                                  files={"archivo": ("asistencias.csv", csv_bytes, "text/csv")},
                                  headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 401 and intento == 1 and not self._token_externo:
                self._invalidar()
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("cloud: no se pudo autenticar para subir la cola.")

    def subir_intentos(self, csv_bytes: bytes) -> dict:
        """Sube la cola de intentos fallidos a la nube (POST /off_sync/intentos, CSV,
        campo 'archivo'). Idempotente por id_intento (UUID). Devuelve IngestaResponse
        {recibidos, insertados, duplicados, rechazados:[{linea,id,motivo}]}."""
        for intento in (1, 2):
            token = self._token_asegurar()
            r = self._client.post("/off_sync/intentos",
                                  files={"archivo": ("intentos.csv", csv_bytes, "text/csv")},
                                  headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 401 and intento == 1 and not self._token_externo:
                self._invalidar()
                continue
            r.raise_for_status()
            return r.json()
        raise RuntimeError("cloud: no se pudo autenticar para subir la cola de intentos.")

    def hay_conexion(self) -> bool:
        try:
            self._client.get("/off_sync/estado",
                             headers={"Authorization": f"Bearer {self._token_asegurar()}"},
                             timeout=5.0).raise_for_status()
            return True
        except Exception:
            return False


cloud_client = CloudClient()
