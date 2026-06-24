# employee_monitoring/sources/foto_sftp_client.py
"""
Cliente SFTP (paramiko) del servidor de fotos. Las fotos viven en una carpeta
remota y el archivo se llama como el id_emp (ej. 12345.jpg). El acceso es por
SSH con llave privada (configurada en .env).

Uso (una sola conexión por corrida de sync):

    with FotoSFTPClient() as sftp:
        meta = sftp.stat_por_id_emp("12345")     # (existe, mtime, size) sin descargar
        data = sftp.descargar_por_id_emp("12345")  # bytes o None
"""
import io
import logging
import posixpath

import paramiko

from src.core.config import settings

logger = logging.getLogger(__name__)


class FotoSFTPClient:
    def __init__(self) -> None:
        self._transport: paramiko.Transport | None = None
        self._sftp: paramiko.SFTPClient | None = None

    # ── Ciclo de vida (context manager) ───────────────────────────────────────
    def __enter__(self) -> "FotoSFTPClient":
        self.conectar()
        return self

    def __exit__(self, *exc) -> None:
        self.cerrar()

    def conectar(self) -> None:
        pkey = self._cargar_llave()
        self._transport = paramiko.Transport((settings.FOTOS_SFTP_HOST, settings.FOTOS_SFTP_PORT))
        self._transport.connect(username=settings.FOTOS_SFTP_USER, pkey=pkey)
        self._sftp = paramiko.SFTPClient.from_transport(self._transport)
        logger.info("SFTP fotos: conectado a %s:%s", settings.FOTOS_SFTP_HOST, settings.FOTOS_SFTP_PORT)

    def cerrar(self) -> None:
        try:
            if self._sftp is not None:
                self._sftp.close()
        finally:
            if self._transport is not None:
                self._transport.close()
            self._sftp = None
            self._transport = None

    # ── Operaciones por id_emp ────────────────────────────────────────────────
    def stat_por_id_emp(self, id_emp: str) -> tuple[bool, int | None, int | None]:
        """(existe, mtime, size) de la foto del empleado SIN descargarla. Prueba
        cada extensión configurada; devuelve la primera que exista."""
        for ruta in self._rutas_candidatas(id_emp):
            try:
                st = self._cliente().stat(ruta)
                return True, getattr(st, "st_mtime", None), getattr(st, "st_size", None)
            except IOError:
                continue
        return False, None, None

    def descargar_por_id_emp(self, id_emp: str) -> bytes | None:
        """Descarga el binario de la foto del empleado, o None si no existe."""
        for ruta in self._rutas_candidatas(id_emp):
            try:
                buffer = io.BytesIO()
                self._cliente().getfo(ruta, buffer)
                return buffer.getvalue()
            except IOError:
                continue
        return None

    # ── Internos ──────────────────────────────────────────────────────────────
    def _cliente(self) -> paramiko.SFTPClient:
        if self._sftp is None:
            self.conectar()
        assert self._sftp is not None
        return self._sftp

    def _rutas_candidatas(self, id_emp: str) -> list[str]:
        base = settings.FOTOS_SFTP_BASE_DIR
        return [posixpath.join(base, f"{id_emp}.{ext}") for ext in settings.foto_extensiones_list]

    @staticmethod
    def _cargar_llave() -> paramiko.PKey:
        """Carga la llave privada probando los tipos comunes (Ed25519, RSA, ECDSA)."""
        ruta = settings.FOTOS_SFTP_KEY_PATH
        passphrase = settings.FOTOS_SFTP_KEY_PASSPHRASE or None
        ultimo_error: Exception | None = None
        for cls in (paramiko.Ed25519Key, paramiko.RSAKey, paramiko.ECDSAKey):
            try:
                return cls.from_private_key_file(ruta, password=passphrase)
            except paramiko.SSHException as exc:
                ultimo_error = exc
        raise RuntimeError(f"SFTP fotos: no se pudo cargar la llave {ruta}: {ultimo_error}")
