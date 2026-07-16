# vigilancia/capture/event_poller.py
# Un hilo por cámara en modo EVENTO. En vez de RECIBIR el push del terminal (que en este
# Hikvision replica TODO su historial de 132k eventos en orden FIFO y sepulta los eventos
# en vivo, además de depender de que el terminal alcance nuestra IP y de su reloj),
# CONSULTAMOS su log de eventos (ISAPI AcsEvent) cada pocos segundos y actuamos solo sobre
# los NUEVOS (serialNo mayor al de la línea base fijada al arrancar).
#   Inmune a: backlog (arrancamos desde "ahora"), cambio de IP (consultamos nosotros
#   hacia el terminal, que ya funciona), y desfase de reloj (dedupe por serialNo).
# Cada evento de identificación (major=5, minor=38) trae el `name` que el terminal
# reconoció por huella/tarjeta → snapshot inmediato → scanner con nombre_hint (misma
# tubería que el sondeo). NO corre IA ni escribe asistencia (eso lo hace el scanner).
import json
import logging
import re
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from src.core.config import settings
from src.core.pgdb import SessionLocal
from src.models.Camara_Model import Camara
from src.services.Cifrado_Service import cifrado_service
from src.capture import scan

logger = logging.getLogger(__name__)


def _cargar_camara(id_camara: int) -> Camara | None:
    db = SessionLocal()
    try:
        return db.get(Camara, id_camara)
    finally:
        db.close()


def _opener(url: str, usuario: str | None, password: str | None):
    pm = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    pm.add_password(None, url, usuario or "", password or "")
    return urllib.request.build_opener(urllib.request.HTTPDigestAuthHandler(pm))


def _device_now(cam, usuario, password) -> datetime:
    """Hora ACTUAL del terminal (tz-aware). Los eventos se marcan con SU reloj, así que la
    ventana de búsqueda se construye contra la hora del terminal, no la nuestra."""
    url = f"http://{cam.host}:{cam.puerto}/ISAPI/System/time"
    with _opener(url, usuario, password).open(url, timeout=8) as resp:
        txt = resp.read().decode("utf-8", "ignore")
    m = re.search(r"<localTime>([^<]+)</localTime>", txt)
    if not m:
        raise RuntimeError("no se pudo leer <localTime> del terminal")
    return datetime.fromisoformat(m.group(1).strip())


def _buscar_38(cam, usuario, password, desde: datetime, hasta: datetime) -> list[dict]:
    """Eventos de identificación (major=5, minor=38) del terminal en [desde, hasta].
    Cada uno trae serialNo/name/time. Pagina (maxResults=30) hasta agotar."""
    url = f"http://{cam.host}:{cam.puerto}/ISAPI/AccessControl/AcsEvent?format=json"
    op = _opener(url, usuario, password)
    # El ISAPI exige la hora a SEGUNDOS (sin microsegundos) con offset ±HH:MM.
    desde_s = desde.replace(microsecond=0).isoformat()
    hasta_s = hasta.replace(microsecond=0).isoformat()
    out: list[dict] = []
    pos = 0
    for _ in range(15):  # tope de páginas por poll (holgado)
        cond = {"AcsEventCond": {"searchID": "vig-poll", "searchResultPosition": pos,
                                 "maxResults": 30, "major": 5, "minor": 38,
                                 "startTime": desde_s, "endTime": hasta_s}}
        req = urllib.request.Request(url, data=json.dumps(cond).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        with op.open(req, timeout=settings.CAP_SNAPSHOT_TIMEOUT) as resp:
            d = json.loads(resp.read().decode("utf-8", "ignore"))
        r = d.get("AcsEvent", {})
        lote = r.get("InfoList") or []
        out.extend(lote)
        if r.get("responseStatusStrg") != "MORE" or not lote:
            break
        pos += len(lote)
    return out


def correr_poller(id_camara: int, stop_event: threading.Event) -> None:
    cam = _cargar_camara(id_camara)
    if cam is None:
        logger.warning("poller[%s]: la cámara ya no existe; no arranca.", id_camara)
        return
    if cam.id_puerta is None:
        logger.warning("poller[%s] '%s': sin id_puerta (no se puede fichar); no arranca.",
                       id_camara, cam.nombre)
        return
    try:
        password = cifrado_service.descifrar(cam.credencial_cifrada)
    except Exception as exc:
        logger.error("poller[%s]: credencial no descifrable (%s); no arranca.", id_camara, exc)
        return
    usuario = cam.usuario
    lookback = timedelta(seconds=settings.CAP_POLL_LOOKBACK_SEG)

    # Sincronizar con el reloj del terminal y fijar la LÍNEA BASE: todo lo que ya existe
    # al arrancar se marca como visto (serialNo máximo) → solo actuamos de aquí en
    # adelante. Reintenta hasta lograrlo (o hasta que se pida parar).
    dev0 = None
    ultimo = 0
    skew = timedelta(0)
    while not stop_event.is_set() and dev0 is None:
        try:
            dev0 = _device_now(cam, usuario, password)
            skew = dev0 - datetime.now(timezone.utc)  # reloj del terminal - reloj real
            base = _buscar_38(cam, usuario, password, dev0 - lookback, dev0 + timedelta(seconds=5))
            ultimo = max((int(e.get("serialNo", 0)) for e in base), default=0)
        except Exception as exc:
            logger.warning("poller[%s]: no se pudo sincronizar con el terminal (%s); reintento en 5s.",
                           id_camara, exc)
            dev0 = None
            stop_event.wait(5)
    if dev0 is None:
        return  # se pidió parar durante la sincronización

    logger.info("poller[%s] '%s': consultando eventos del terminal (puerta %s); base serialNo=%s, skew=%.0fs.",
                id_camara, cam.nombre, cam.id_puerta, ultimo, skew.total_seconds())

    conectado = True
    while not stop_event.is_set():
        try:
            ahora_dev = datetime.now(timezone.utc).astimezone(dev0.tzinfo) + skew
            eventos = _buscar_38(cam, usuario, password,
                                 ahora_dev - lookback, ahora_dev + timedelta(seconds=5))
            if not conectado:
                conectado = True
                logger.info("poller[%s]: reconectado.", id_camara)
        except Exception as exc:
            if conectado:  # solo loguea al CAER
                conectado = False
                logger.warning("poller[%s]: sin conexión con el terminal: %s", id_camara, exc)
                scan.log_evento(cam, "sin_conexion", str(exc))
            stop_event.wait(max(settings.CAP_POLL_INTERVAL_SEG, 3.0))
            continue

        nuevos = sorted((e for e in eventos if int(e.get("serialNo", 0)) > ultimo),
                        key=lambda e: int(e.get("serialNo", 0)))
        for e in nuevos:
            ultimo = max(ultimo, int(e.get("serialNo", 0)))
            nombre = (e.get("name") or "").strip() or None
            logger.info("poller[%s]: evento nuevo serialNo=%s nombre=%r → captura inmediata",
                        id_camara, e.get("serialNo"), nombre)
            try:
                scan.escanear_camara(cam, password, nombre_hint=nombre, un_frame=True)
            except Exception as exc:
                logger.warning("poller[%s]: error escaneando: %s", id_camara, exc)

        stop_event.wait(settings.CAP_POLL_INTERVAL_SEG)

    logger.info("poller[%s]: detenido.", id_camara)
