# vigilancia/capture/camera_worker.py
# Un hilo por cámara en modo SONDEO. Sondea el snapshot ISAPI, aplica el gate de
# movimiento y, dentro de la ventana activa, escanea (scan.escanear_camara). NO corre
# IA ni escribe asistencia (eso lo hace el scanner). Las cámaras modo 'evento' NO usan
# esto: las dispara el webhook.
import logging
import threading
import time

from src.core.config import settings
from src.core.pgdb import SessionLocal
from src.models.Camara_Model import Camara
from src.services import Snapshot_Service
from src.services.Cifrado_Service import cifrado_service
from src.capture.motion import MotionGate
from src.capture import scan

logger = logging.getLogger(__name__)


def _cargar_camara(id_camara: int) -> Camara | None:
    db = SessionLocal()
    try:
        return db.get(Camara, id_camara)
    finally:
        db.close()


def correr_worker(id_camara: int, stop_event: threading.Event) -> None:
    cam = _cargar_camara(id_camara)
    if cam is None:
        logger.warning("worker[%s]: la cámara ya no existe; no arranca.", id_camara)
        return
    if cam.id_puerta is None:
        logger.warning("worker[%s] '%s': sin id_puerta (no se puede fichar); no arranca.",
                       id_camara, cam.nombre)
        return
    try:
        password = cifrado_service.descifrar(cam.credencial_cifrada)
    except Exception as exc:
        logger.error("worker[%s]: credencial no descifrable (%s); no arranca.", id_camara, exc)
        return

    url = Snapshot_Service.construir_url(cam)
    usuario = cam.usuario
    gate = MotionGate(umbral=float(cam.umbral_movimiento or 2.5))
    gap = max(float(cam.gap_muestreo_seg or 0.7), 0.2)
    active_until = 0.0
    last_send = 0.0
    conectado = True
    logger.info("worker[%s] '%s': vigilando %s (puerta %s).", id_camara, cam.nombre, url, cam.id_puerta)

    while not stop_event.is_set():
        ahora = time.monotonic()
        try:
            snap = Snapshot_Service.obtener_snapshot(url, usuario, password,
                                                     timeout=settings.CAP_SNAPSHOT_TIMEOUT)
            if not conectado:
                conectado = True
                logger.info("worker[%s]: reconectado.", id_camara)
        except Exception as exc:
            if conectado:  # solo loguea al CAER (no en cada intento)
                conectado = False
                logger.warning("worker[%s]: sin conexión con la cámara: %s", id_camara, exc)
                scan.log_evento(cam, "sin_conexion", str(exc))
            stop_event.wait(max(gap, 2.0))
            continue

        if gate.hay_movimiento(snap):
            active_until = ahora + settings.CAP_VENTANA_ACTIVA_SEG

        if ahora < active_until and (ahora - last_send) >= settings.CAP_MIN_GAP_ENVIO_SEG:
            last_send = ahora
            try:
                resp = scan.escanear_camara(cam, password, primer_frame=snap)
            except Exception as exc:
                logger.warning("worker[%s]: error en el escaneo: %s", id_camara, exc)
                scan.log_evento(cam, "error", f"scanner: {exc}")
                stop_event.wait(gap)
                continue
            if resp and resp.get("acceso"):
                active_until = 0.0  # match → dormir hasta el próximo movimiento

        stop_event.wait(gap)

    logger.info("worker[%s]: detenido.", id_camara)
