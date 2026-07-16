# vigilancia/capture/scan.py
# Lógica COMPARTIDA de "escanear una cámara": baja N frames del snapshot ISAPI, los
# manda al scanner del back y loguea eventos_camara. La usan el worker (modo sondeo) y
# el webhook (modo evento).
import logging
import time
from uuid import UUID

from src.core.config import settings
from src.core.pgdb import SessionLocal
from src.services import Evento_Service, Snapshot_Service
from src.capture.scanner_client import scanner_client

logger = logging.getLogger(__name__)


def log_evento(cam, tipo: str, mensaje: str | None, **kw) -> None:
    db = SessionLocal()
    try:
        Evento_Service.registrar(db, id_camara=cam.id_camara, id_empresa=cam.id_empresa,
                                 id_puerta=cam.id_puerta, tipo_evento=tipo, mensaje=mensaje, **kw)
    except Exception as exc:
        logger.error("cam[%s]: no se pudo loguear evento: %s", cam.id_camara, exc)
    finally:
        db.close()


def procesar_scan(cam, resp: dict) -> dict:
    """Loguea el desenlace del ScanResponse (solo se persisten match/spoof por defecto)."""
    tipo = Evento_Service.tipo_desde_scan(resp)
    trab = resp.get("trabajador") or {}
    id_esc = resp.get("id_escaneo")
    if resp.get("acceso"):
        logger.info("cam[%s]: FICHADO %s %s (escaneo %s).",
                    cam.id_camara, trab.get("nombre"), trab.get("apellido"), id_esc)
    if tipo in settings.eventos_scan_set:
        log_evento(cam, tipo, resp.get("mensaje"),
                   id_escaneo=(UUID(id_esc) if id_esc else None),
                   id_trabajador=trab.get("id_trabajador"))
    return resp


def reunir_frames(url: str, usuario, password, n: int, primer: bytes | None = None) -> list[bytes]:
    """El primer frame (dado o bajado) + hasta completar n snapshots espaciados (liveness)."""
    frames = [primer] if primer is not None else []
    for _ in range(max(0, n - len(frames))):
        if frames:
            time.sleep(0.25)
        try:
            frames.append(Snapshot_Service.obtener_snapshot(url, usuario, password,
                                                            timeout=settings.CAP_SNAPSHOT_TIMEOUT))
        except Exception:
            break
    return frames


def escanear_camara(cam, password, primer_frame: bytes | None = None,
                    nombre_hint: str | None = None, un_frame: bool = False) -> dict | None:
    """Baja N frames de la cámara, los manda al scanner y procesa. Devuelve ScanResponse|None.

    nombre_hint: nombre que el terminal detectó en el evento (modo evento). Acota la
    búsqueda facial en recognition. En modo sondeo va None (búsqueda total).
    un_frame: si True, toma UN solo snapshot INMEDIATO (→ /scanner/acceso/foto, sin
    liveness). Se usa en modo EVENTO: la persona acaba de autenticar y está pegada al
    lector, así que hay que capturar ya, sin la demora de los 3 frames de liveness.
    """
    url = Snapshot_Service.construir_url(cam)
    n = 1 if un_frame else (settings.CAP_FRAMES_LIVENESS if settings.SCANNER_USAR_LIVENESS else 1)
    frames = reunir_frames(url, cam.usuario, password, n, primer_frame)
    if not frames:
        return None
    resp = scanner_client.enviar(frames, cam.id_puerta, cam.tipo_registro, cam.id_dispositivo,
                                 nombre_hint=nombre_hint)
    procesar_scan(cam, resp)
    return resp
