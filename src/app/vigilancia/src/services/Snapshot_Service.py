# vigilancia/services/Snapshot_Service.py
# Captura por SNAPSHOT ISAPI HTTP (ffmpeg/RTSP NO decodifica el "HIK Media Server").
# Arma la URL por marca (o ruta_snapshot override), baja el JPEG con auth Digest
# (urllib, sin dependencias nuevas) y ofrece un lector de resolución JPEG en Python puro.
# Lo usan el API (test-conexion/snapshot) y el motor de captura (Fase 4).
import urllib.error
import urllib.request

# Plantillas de snapshot por marca. {canal} = id ISAPI del canal (101=cam1 main, etc.).
_PLANTILLAS = {
    "hikvision": "http://{host}:{puerto}/ISAPI/Streaming/channels/{canal}/picture",
    "generico":  "http://{host}:{puerto}/ISAPI/Streaming/channels/{canal}/picture",
    "dahua":     "http://{host}:{puerto}/cgi-bin/snapshot.cgi?channel={canal}",
}

# Marcadores SOF de JPEG que traen alto/ancho (excluye DHT/DAC/tablas).
_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def construir_url(cam, host: str | None = None) -> str:
    """URL de snapshot para una cámara (usa ruta_snapshot si viene, si no la plantilla).
    `host` permite pasar la IP EFECTIVA (la de la cámara o, si es NULL, la del grupo DVR)."""
    ip = host or cam.host
    if cam.ruta_snapshot:
        ruta = cam.ruta_snapshot
        if ruta.startswith("http://") or ruta.startswith("https://"):
            return ruta
        return f"http://{ip}:{cam.puerto}{ruta if ruta.startswith('/') else '/' + ruta}"
    plantilla = _PLANTILLAS.get((cam.marca or "hikvision").lower(), _PLANTILLAS["generico"])
    return plantilla.format(host=ip, puerto=cam.puerto, canal=cam.canal)


def obtener_snapshot(url: str, usuario: str | None, password: str | None, timeout: float = 8.0) -> bytes:
    """Baja el JPEG por HTTP con Digest. Lanza urllib.error.* si falla."""
    pm = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    pm.add_password(None, url, usuario or "", password or "")
    opener = urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(pm))
    with opener.open(url, timeout=timeout) as resp:
        return resp.read()


def es_jpeg(data: bytes) -> bool:
    return len(data) >= 2 and data[0] == 0xFF and data[1] == 0xD8


def dimensiones_jpeg(data: bytes) -> tuple[int, int] | None:
    """(ancho, alto) del JPEG leyendo el marcador SOF, sin Pillow/opencv. None si no aplica."""
    if not es_jpeg(data):
        return None
    i, n = 2, len(data)
    while i + 9 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in _SOF:
            alto = (data[i + 5] << 8) + data[i + 6]
            ancho = (data[i + 7] << 8) + data[i + 8]
            return (ancho, alto)
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2  # marcadores sin longitud
            continue
        seg_len = (data[i + 2] << 8) + data[i + 3]
        if seg_len < 2:
            break
        i += 2 + seg_len
    return None
