# employee_monitoring/main.py — sincroniza la nómina SYS21 → trabajadores/embeddings.
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.core.config import settings
from src.core.pgdb import engine
from src.core.auth import guard_scopes, oauth2_scheme
import src.models  # noqa: F401 — registra los modelos en el registry de Base
from src.routers.Sync_Router import router as Router_Sync
from src.scheduler import detener_scheduler, iniciar_scheduler
from src.sources.sys21_engines import probar_conexiones

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. BD local (fatal si falla: sin ella el servicio no sirve).
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("employee_monitoring: conexión a la BD OK (%s como %s).", settings.DB_NAME, settings.DB_USER)
    except Exception as exc:
        logger.error("employee_monitoring: no se pudo conectar a la BD: %s", exc)
        raise RuntimeError("employee_monitoring: sin conexión a la base de datos.") from exc

    # 2. Nómina SYS21 (no fatal: se loguea OK/degradado por origen).
    for origen, ok in probar_conexiones().items():
        logger.info("employee_monitoring: SYS21[%s] %s.", origen, "OK" if ok else "DEGRADADO")

    # 3. Llave SFTP (no fatal: solo aviso si no está).
    if settings.FOTOS_SFTP_KEY_PATH and not os.path.exists(settings.FOTOS_SFTP_KEY_PATH):
        logger.warning("employee_monitoring: llave SFTP no encontrada en %s (las fotos fallarán).",
                       settings.FOTOS_SFTP_KEY_PATH)

    # 4. Scheduler interno.
    iniciar_scheduler()
    try:
        yield
    finally:
        detener_scheduler()


app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
    dependencies=[Depends(oauth2_scheme), Depends(guard_scopes)],
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=(
        r"^http://("
        r"localhost"
        r"|127\.0\.0\.1"
        r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
        r"|192\.168\.\d{1,3}\.\d{1,3}"
        r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
        r")(:\d+)?$"
    ),
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(Router_Sync)


@app.get("/health", tags=["Health"])
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        logger.warning("employee_monitoring healthcheck: BD no disponible: %s", exc)
        db_ok = False
    payload = {"status": "ok" if db_ok else "degraded", "service": "employee_monitoring",
               "version": settings.APP_VERSION, "database": "ok" if db_ok else "down"}
    if not db_ok:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
    return payload
