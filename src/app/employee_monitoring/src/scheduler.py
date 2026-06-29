# employee_monitoring/scheduler.py
"""
Scheduler interno: dispara el sync por CRON, en hora local (SYNC_TZ), con dos jobs
ESCALONADOS — uno por origen:
  - agricola_com (comercial): horas SYNC_CRON_COM      (default 02:00 y 14:00)
  - agricola:                horas SYNC_CRON_AGRICOLA  (default 03:00 y 15:00)

El comercial corre 1h antes que el agrícola para que aguas abajo (p.ej. el
microservicio offline) tenga listos esos datos primero.

Como gunicorn corre con varios workers (y podría haber réplicas), cada job toma un
advisory lock de PostgreSQL por origen: solo la instancia que lo obtiene ejecuta.
"""
import functools
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import text

from src.core.config import settings
from src.core.pgdb import SessionLocal
from src.sync.Sync_Service import sync_service

logger = logging.getLogger(__name__)

# Advisory lock por origen (claves arbitrarias distintas).
_LOCK_KEYS = {"agricola_com": 728041, "agricola": 728042}

_scheduler = BackgroundScheduler(timezone=settings.SYNC_TZ)


def _job_sync_origen(origen: str) -> None:
    db = SessionLocal()
    key = _LOCK_KEYS.get(origen, 728040)
    try:
        obtenido = db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar()
        if not obtenido:
            logger.info("Scheduler[%s]: otra instancia tiene el lock; se omite esta corrida.", origen)
            return
        try:
            sync_service.ejecutar_sync(db, disparado_por="scheduler", origenes=[origen])
        finally:
            db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
            db.commit()
    except Exception:  # noqa: BLE001 — el scheduler nunca debe morir por una corrida
        logger.exception("Scheduler[%s]: la corrida de sync falló", origen)
    finally:
        db.close()


def iniciar_scheduler() -> None:
    """Arranca el scheduler si SYNC_ENABLED. Idempotente."""
    if not settings.SYNC_ENABLED:
        logger.info("Scheduler deshabilitado (SYNC_ENABLED=false).")
        return
    if _scheduler.running:
        return
    tz = settings.SYNC_TZ
    # Comercial: cron normal, o intervalo de prueba si SYNC_COM_TEST_INTERVAL_MIN > 0.
    if settings.SYNC_COM_TEST_INTERVAL_MIN > 0:
        trigger_com = IntervalTrigger(minutes=settings.SYNC_COM_TEST_INTERVAL_MIN)
        logger.warning("Scheduler PRUEBA: comercial corre cada %d min (intervalo).",
                       settings.SYNC_COM_TEST_INTERVAL_MIN)
    else:
        trigger_com = CronTrigger(hour=settings.SYNC_CRON_COM, minute=0, timezone=tz)
    _scheduler.add_job(
        functools.partial(_job_sync_origen, "agricola_com"),
        trigger_com,
        id="sync_agricola_com", max_instances=1, coalesce=True, misfire_grace_time=600,
        replace_existing=True,
    )
    _scheduler.add_job(
        functools.partial(_job_sync_origen, "agricola"),
        CronTrigger(hour=settings.SYNC_CRON_AGRICOLA, minute=0, timezone=tz),
        id="sync_agricola", max_instances=1, coalesce=True, misfire_grace_time=600,
        replace_existing=True,
    )
    _scheduler.start()
    logger.info(
        "Scheduler iniciado (%s): comercial horas [%s], agrícola horas [%s].",
        tz, settings.SYNC_CRON_COM, settings.SYNC_CRON_AGRICOLA,
    )
    if settings.SYNC_RUN_ON_STARTUP:
        _scheduler.add_job(functools.partial(_job_sync_origen, "agricola_com"),
                           "date", id="startup_com", replace_existing=True)
        _scheduler.add_job(functools.partial(_job_sync_origen, "agricola"),
                           "date", id="startup_agricola", replace_existing=True)
        logger.info("Scheduler: corridas iniciales programadas (SYNC_RUN_ON_STARTUP=true).")


def detener_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler detenido.")
