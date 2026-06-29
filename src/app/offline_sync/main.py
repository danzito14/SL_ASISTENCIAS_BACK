# offline_sync/main.py
# Entrega el roster al APK (kiosko offline) e ingiere por lotes lo que el APK
# capturó sin conexión: asistencias e intentos (CSV) y enrolamientos walk-in (JSON).
import logging
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

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # BD local (fatal si falla: sin ella el servicio no sirve).
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("offline_sync: conexión a la BD OK (%s como %s).", settings.DB_NAME, settings.DB_USER)
    except Exception as exc:
        logger.error("offline_sync: no se pudo conectar a la BD: %s", exc)
        raise RuntimeError("offline_sync: sin conexión a la base de datos.") from exc
    yield


app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
    dependencies=[Depends(oauth2_scheme), Depends(guard_scopes)],
)

app.add_middleware(
    CORSMiddleware,
    # El WebView del APK (Capacitor) usa origen https://localhost (Android) o
    # capacitor://localhost (iOS); si se activa CapacitorHttp el CORS ni aplica
    # (HTTP nativo), pero lo dejamos abierto a esos orígenes por si no se usa.
    allow_origin_regex=(
        r"^(https?|capacitor|ionic)://("
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
        logger.warning("offline_sync healthcheck: BD no disponible: %s", exc)
        db_ok = False
    payload = {"status": "ok" if db_ok else "degraded", "service": "offline_sync",
               "version": settings.APP_VERSION, "database": "ok" if db_ok else "down"}
    if not db_ok:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
    return payload
