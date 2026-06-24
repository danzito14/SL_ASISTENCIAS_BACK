# employee_monitoring/scheduler.py
"""
Scheduler interno que dispara el sync periódicamente. Como gunicorn corre con
varios workers (y podría haber varias réplicas), el job toma un advisory lock de
PostgreSQL (pg_try_advisory_lock): solo la instancia que lo obtiene ejecuta; las
demás se saltan esa corrida. El lock es a nivel de SESIÓN, así que sobrevive a los
commits del sync y se libera al final.
"""
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import text

from src.core.config import settings
from src.core.pgdb import SessionLocal
from src.sync.Sync_Service import sync_service

logger = logging.getLogger(__name__)

# Clave arbitraria (única) del advisory lock de esta tarea.
_ADVISORY_LOCK_KEY = 728041
_JOB_ID = "sync_sys21"

_scheduler = BackgroundScheduler(timezone="UTC")


def _job_sync() -> None:
    db = SessionLocal()
    try:
        obtenido = db.execute(
            text("SELECT pg_try_advisory_lock(:k)"), {"k": _ADVISORY_LOCK_KEY}
        ).scalar()
        if not obtenido:
            logger.info("Scheduler: otra instancia tiene el lock; se omite esta corrida.")
            return
        try:
            sync_service.ejecutar_sync(db, disparado_por="scheduler")
        finally:
            db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": _ADVISORY_LOCK_KEY})
            db.commit()
    except Exception:  # noqa: BLE001 — el scheduler nunca debe morir por una corrida
        logger.exception("Scheduler: la corrida de sync falló")
    finally:
        db.close()


def iniciar_scheduler() -> None:
    """Arranca el scheduler si SYNC_ENABLED. Idempotente."""
    if not settings.SYNC_ENABLED:
        logger.info("Scheduler deshabilitado (SYNC_ENABLED=false).")
        return
    if _scheduler.running:
        return
    _scheduler.add_job(
        _job_sync, "interval",
        minutes=settings.SYNC_INTERVAL_MINUTES,
        id=_JOB_ID, max_instances=1, coalesce=True, misfire_grace_time=300,
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("Scheduler iniciado: sync cada %d min.", settings.SYNC_INTERVAL_MINUTES)
    if settings.SYNC_RUN_ON_STARTUP:
        _scheduler.add_job(_job_sync, "date", id="sync_startup", replace_existing=True)
        logger.info("Scheduler: corrida inicial programada (SYNC_RUN_ON_STARTUP=true).")


def detener_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler detenido.")
