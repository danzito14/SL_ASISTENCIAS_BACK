# vigilancia/capture/supervisor.py
# Proceso ÚNICO de captura: toma un pg_try_advisory_lock (si otro capturador ya lo
# tiene, sale) y mantiene UN hilo por cámara habilitada, reconciliando cada
# CAP_RECONCILE_SEG (arranca las nuevas, detiene las deshabilitadas/borradas).
import logging
import signal
import threading

from sqlalchemy import text

from src.core.config import settings
from src.core.pgdb import SessionLocal, engine
from src.models.Camara_Model import Camara
from src.capture.camera_worker import correr_worker
from src.capture.event_poller import correr_poller

logger = logging.getLogger(__name__)

# Clave del lock de "supervisor único" (bigint). Constante fija del microservicio.
_ADVISORY_KEY = 0x7669670001  # 'vig'


class Supervisor:
    def __init__(self) -> None:
        self._workers: dict[int, tuple[threading.Thread, threading.Event]] = {}
        self._parar = threading.Event()

    def _camaras_activas(self) -> dict[int, str]:
        """{id_camara: modo_captura} de las cámaras de asistencia activas. 'sondeo' usa el
        worker (snapshot+movimiento); 'evento' usa el poller del log del terminal."""
        db = SessionLocal()
        try:
            filas = (
                db.query(Camara.id_camara, Camara.modo_captura)
                .filter(Camara.habilitada.is_(True),
                        Camara.tipo_camara == "asistencia",
                        Camara.estado == "activo",
                        Camara.modo_captura.in_(("sondeo", "evento")))
                .all()
            )
            return {f[0]: f[1] for f in filas}
        finally:
            db.close()

    def _reconciliar(self) -> None:
        activas = self._camaras_activas()  # {id: modo}
        # Arrancar hilos nuevos (worker para sondeo, poller para evento).
        for cid, modo in activas.items():
            if cid in self._workers:
                continue
            ev = threading.Event()
            target = correr_poller if modo == "evento" else correr_worker
            th = threading.Thread(target=target, args=(cid, ev), name=f"cam-{cid}-{modo}", daemon=True)
            th.start()
            self._workers[cid] = (th, ev)
            logger.info("supervisor: %s cámara %s arrancado (modo %s).",
                        "poller" if modo == "evento" else "worker", cid, modo)
        # Detener las que ya no están habilitadas.
        for cid in set(self._workers) - set(activas):
            _, ev = self._workers.pop(cid)
            ev.set()
            logger.info("supervisor: hilo cámara %s detenido (deshabilitada/borrada).", cid)
        # Limpiar hilos que terminaron solos (p.ej. sin id_puerta o credencial mala).
        for cid in [c for c, (th, _) in self._workers.items() if not th.is_alive()]:
            self._workers.pop(cid, None)

    def run(self) -> None:
        conn = engine.connect()
        try:
            adquirido = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": _ADVISORY_KEY}).scalar()
            if not adquirido:
                logger.warning("supervisor: otro capturador ya tiene el lock; saliendo.")
                return
            logger.info("supervisor: lock adquirido; arrancando captura.")
            # Las cámaras modo 'evento' se atienden con el poller del log del terminal
            # (ver event_poller); ya NO se usa el webhook push (replicaba el backlog FIFO).
            while not self._parar.is_set():
                try:
                    self._reconciliar()
                except Exception as exc:
                    logger.error("supervisor: error en reconciliación: %s", exc)
                self._parar.wait(settings.CAP_RECONCILE_SEG)
        finally:
            logger.info("supervisor: deteniendo %d hilo(s)...", len(self._workers))
            for _, ev in self._workers.values():
                ev.set()
            for th, _ in self._workers.values():
                th.join(timeout=5)
            try:
                conn.close()  # cerrar la conexión libera el advisory lock
            except Exception:
                # Si postgres ya se cayó (p.ej. un restart simultáneo del stack), la
                # conexión estará muerta; el lock se libera igual al morir la sesión.
                pass

    def detener(self, *_args) -> None:
        logger.info("supervisor: señal de parada recibida.")
        self._parar.set()


def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    sup = Supervisor()
    signal.signal(signal.SIGTERM, sup.detener)
    signal.signal(signal.SIGINT, sup.detener)
    sup.run()
