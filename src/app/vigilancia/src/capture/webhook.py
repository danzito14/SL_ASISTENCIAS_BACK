# vigilancia/capture/webhook.py
# Servidor HTTP que recibe los eventos PUSH del terminal (Hikvision httpHosts) y, en los
# subEventType de "cara" configurados, dispara el escaneo (snapshot → scanner → asistencia).
# Reemplaza el sondeo para las cámaras con modo_captura='evento'. Sin dependencias nuevas.
import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from src.core.config import settings
from src.core.pgdb import SessionLocal
from src.models.Camara_Model import Camara
from src.services.Cifrado_Service import cifrado_service
from src.capture import scan

logger = logging.getLogger(__name__)

_pool = ThreadPoolExecutor(max_workers=3)      # escaneos concurrentes (no bloquear el HTTP)
_ultimo_scan: dict[int, float] = {}            # id_camara -> monotonic del último escaneo (cooldown)
_lock = threading.Lock()

# Frescura: el terminal, al suscribirnos, REPLICA todo su historial (132k+ eventos viejos).
# Su reloj está correcto, así que solo actuamos en eventos RECIENTES (en vivo) y descartamos
# el backlog por antigüedad. Tuneable por env sin rebuild.
_MAX_EDAD_SEG = float(os.getenv("WEBHOOK_EVENTO_MAX_EDAD_SEG", "120"))


def _camara_por_ip(ip: str):
    db = SessionLocal()
    try:
        return (db.query(Camara)
                .filter(Camara.host == ip, Camara.modo_captura == "evento",
                        Camara.habilitada.is_(True))
                .first())
    finally:
        db.close()


def _tag_xml(txt: str, tag: str) -> str | None:
    """Primer <tag>valor</tag> (case-insensitive, multi-línea). Para el push XML del terminal."""
    m = re.search(rf"<{tag}>(.*?)</{tag}>", txt, re.DOTALL | re.IGNORECASE)
    return m.group(1).strip() if m else None


def _extraer(body: bytes) -> tuple[str | None, str | None, str | None, str | None]:
    """Saca (ipAddress, subEventType, name, dateTime) del POST del terminal (AccessControllerEvent).

    El terminal puede empujar en JSON o en XML (parameterFormatType). Se soportan ambos.
    'name' es el nombre 'sucio' que el terminal identificó (huella/tarjeta, p.ej.
    "Uriel Alonso Caro Diaz"). Es solo un INDICIO para acotar la búsqueda facial.
    'dateTime' es la hora del evento (ISO con offset) → se usa para descartar el backlog.
    """
    txt = body.decode("utf-8", "ignore")
    # 1) JSON (parameterFormatType=JSON o multipart con JSON embebido)
    m = re.search(r"\{.*\}", txt, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            ace = data.get("AccessControllerEvent") or {}
            ip = data.get("ipAddress")
            sub = ace.get("subEventType")
            nombre = ace.get("name")
            dt = data.get("dateTime")
            if ip or sub or nombre:
                return (ip, (str(sub) if sub is not None else None),
                        (str(nombre).strip() or None) if nombre else None, dt)
        except Exception:
            pass
    # 2) XML (parameterFormatType=XML) — EventNotificationAlert/AccessControllerEvent
    if "<" in txt:
        ip = _tag_xml(txt, "ipAddress")
        sub = _tag_xml(txt, "subEventType")
        nombre = _tag_xml(txt, "name")
        dt = _tag_xml(txt, "dateTime")
        return ip, sub, (nombre or None), dt
    return None, None, None, None


def _es_reciente(dt_str: str | None) -> bool:
    """True si el evento es RECIENTE (en vivo). El terminal replica su historial completo
    al suscribirse (eventos de 2025); su reloj está correcto, así que descartamos por edad.
    Sin dateTime o si no se puede parsear → se deja pasar (no bloquear por un formato raro)."""
    if not dt_str:
        return True
    try:
        t = datetime.fromisoformat(dt_str)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return abs((datetime.now(timezone.utc) - t).total_seconds()) <= _MAX_EDAD_SEG
    except Exception:
        return True


def _procesar_evento(ip: str, sub: str | None, nombre: str | None = None) -> None:
    cam = _camara_por_ip(ip)
    if cam is None:
        return
    if sub is None:
        return  # heartbeat / evento sin sub-tipo de acceso → no dispara escaneo
    trig = settings.webhook_trigger_set
    if "*" not in trig and sub not in trig:
        return  # no es un subEventType configurado ("*" = cualquiera de acceso, para tuning)
    ahora = time.monotonic()
    with _lock:
        if ahora - _ultimo_scan.get(cam.id_camara, 0.0) < settings.WEBHOOK_COOLDOWN_SEG:
            return  # cooldown por cámara (dedupe)
        _ultimo_scan[cam.id_camara] = ahora
    if cam.id_puerta is None:
        logger.warning("webhook: cam %s sin id_puerta; no se puede fichar.", cam.id_camara)
        return
    try:
        password = cifrado_service.descifrar(cam.credencial_cifrada)
    except Exception as exc:
        logger.error("webhook: cam %s credencial no descifrable: %s", cam.id_camara, exc)
        return
    logger.info("webhook: evento sub=%s de cam %s (%s) nombre=%r → captura inmediata",
                sub, cam.id_camara, ip, nombre)
    try:
        scan.escanear_camara(cam, password, nombre_hint=nombre, un_frame=True)
    except Exception as exc:
        logger.warning("webhook: error escaneando cam %s: %s", cam.id_camara, exc)


class _Handler(BaseHTTPRequestHandler):
    def _responder_ok(self):
        self.send_response(200)
        self.end_headers()
        try:
            self.wfile.write(b"OK")
        except Exception:
            pass

    def do_POST(self):
        # Token opcional en el path (si WEBHOOK_TOKEN != "").
        if settings.WEBHOOK_TOKEN and settings.WEBHOOK_TOKEN not in self.path:
            self.send_response(403); self.end_headers(); return
        n = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(n) if n else b""
        self._responder_ok()  # responder rápido; el terminal no espera el escaneo
        ip, sub, nombre, dt = _extraer(body)
        logger.debug("webhook: rx sub=%s nombre=%r dt=%s (%d bytes)", sub, nombre, dt, n)
        if ip and _es_reciente(dt):  # descarta el backlog histórico del terminal
            _pool.submit(_procesar_evento, ip, sub, nombre)

    do_GET = do_POST  # heartbeats / prueba

    def log_message(self, *a):
        pass


def correr_webhook(stop_event: threading.Event) -> None:
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", settings.WEBHOOK_PORT), _Handler)
    except Exception as exc:
        logger.error("webhook: no se pudo abrir el puerto %s: %s", settings.WEBHOOK_PORT, exc)
        return
    logger.info("webhook: escuchando en 0.0.0.0:%s (dispara en subEventType %s, cooldown %ss)",
                settings.WEBHOOK_PORT, sorted(settings.webhook_trigger_set), settings.WEBHOOK_COOLDOWN_SEG)
    hilo = threading.Thread(target=srv.serve_forever, name="webhook-http", daemon=True)
    hilo.start()
    stop_event.wait()
    srv.shutdown()
    srv.server_close()
    logger.info("webhook: detenido.")
