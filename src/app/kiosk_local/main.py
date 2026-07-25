# kiosk_local/main.py
# Backend LOCAL del kiosko de escritorio (corre en la PC, escucha en localhost). Fase 1:
# baja el roster de la nube a la BD local. Fases siguientes: reconocer offline + subir
# eventos solo. NO usa el gateway/JWT (es local); el front Electron le pega a localhost.
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.core import meta
from src.core.config import settings
from src.core.pgdb import SessionLocal, engine
from src.routers.Kiosk_Router import router as Router_Kiosk
from src.services.Cloud_Client import cloud_client
from src.services.Sync_Service import sync_service

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("kiosk_local: BD local OK (%s como %s).", settings.DB_NAME, settings.DB_USER)
    except Exception as exc:
        logger.error("kiosk_local: sin conexión a la BD local: %s", exc)
        raise RuntimeError("kiosk_local: sin conexión a la base de datos local.") from exc
    # Restaura el token del último usuario logueado (persistido en kiosk_meta) para que el
    # loop de subida siga con SU identidad/empresa tras un reinicio. Sin token → el loop cae
    # al KIOSK_USER de respaldo hasta el próximo sync desde el front.
    db = SessionLocal()
    try:
        # Migración kiosk-only (idempotente, NO toca prod): columna para marcar los intentos
        # que la nube rechazó fila-por-fila, y así NO reintentarlos en bucle en cada ciclo.
        db.execute(text("ALTER TABLE intentos_acceso ADD COLUMN IF NOT EXISTS "
                        "sync_rechazado BOOLEAN NOT NULL DEFAULT FALSE"))
        db.commit()
    except Exception as exc:
        logger.warning("kiosk_local: no se pudo asegurar la columna sync_rechazado: %s", exc)
    try:
        tok = meta.leer(db, "cloud_token")
        if tok:
            cloud_client.set_token(tok)
            logger.info("kiosk_local: token de sesión restaurado (empresa=%s).",
                        meta.empresa_actual(db))
    except Exception as exc:
        logger.warning("kiosk_local: no se pudo restaurar el token de sesión: %s", exc)
    finally:
        db.close()
    # Loop de auto-sync: sube la cola de escaneos a la nube cuando hay internet.
    stop = threading.Event()
    hilo = threading.Thread(target=sync_service.correr_loop, args=(stop,), name="sync", daemon=True)
    hilo.start()
    try:
        yield
    finally:
        stop.set()
        hilo.join(timeout=5)


app = FastAPI(title=settings.APP_TITLE, version=settings.APP_VERSION, debug=settings.DEBUG, lifespan=lifespan)

# El front Electron carga desde file:// / http://localhost → CORS abierto a localhost.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^(https?|file|capacitor)://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

app.include_router(Router_Kiosk)


@app.get("/health", tags=["Health"])
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        logger.warning("kiosk_local healthcheck: BD no disponible: %s", exc)
        db_ok = False
    payload = {"status": "ok" if db_ok else "degraded", "service": "kiosk_local",
               "version": settings.APP_VERSION, "database": "ok" if db_ok else "down"}
    if not db_ok:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
    return payload
