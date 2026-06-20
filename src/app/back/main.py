# main.py
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.core.config import settings
from src.core.pgdb import engine
from src.core.auth import guard_scopes, oauth2_scheme
import src.models  # noqa: F401 — registra todos los modelos en el registry de Base
from src.routers.Rol_Router import router as Router_Rol
from src.routers.Usuario_Router import router as Router_Usuario
from src.routers.Empresa_Router import router as Router_Empresa
from src.routers.AreaTrabajo_Router import router as Router_AreaTrabajo
from src.routers.PuertaAcceso_Router import router as Router_PuertaAcceso
from src.routers.Trabajadores_Router import router as Router_Trabajador
from src.routers.Asistencia_Router import router as Router_Asistencia
from src.routers.Escaneo_Router import router as Router_Escaneo
from src.routers.Scanner_Router import router as Router_Scanner
from src.routers.Dispositivo_Router import router as Router_Dispositivo
from src.routers.Incidencia_Router import router as Router_Incidencia
from src.routers.Embedding_Router import router as Router_Embedding
from src.routers.IntentoAcceso_Router import router as Router_IntentoAcceso
from src.routers.Reporte_Router import router as Router_Reporte

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Verificar conexión a la BD al arrancar ────────────────────────────────
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Conexión a la base de datos establecida (%s).", settings.DB_NAME)
    except Exception as exc:
        logger.error("No se pudo conectar a la base de datos: %s", exc)
        raise RuntimeError(
            f"No se pudo conectar a la base de datos en "
            f"{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}."
        ) from exc

    # ── Precargar el modelo facial (opcional) ─────────────────────────────────
    # Descarga/carga buffalo_l una sola vez al arrancar en lugar de en el primer
    # request. Apagado por defecto para que los reloads de desarrollo sean rápidos.
    # Actívalo en producción con PRELOAD_FACE_MODEL=true en el .env.
    if getattr(settings, "PRELOAD_FACE_MODEL", False):
        from src.services.scanner_service import facial_service
        logger.info("Precargando modelo facial...")
        facial_service.precargar()

    yield


app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
    # Guard global: protege todas las rutas por scopes de rol (salvo las públicas).
    # oauth2_scheme va primero solo para que /docs muestre el botón "Authorize".
    dependencies=[Depends(oauth2_scheme), Depends(guard_scopes)],
)

# ── CORS ──────────────────────────────────────────────────────────────────
# Permite que el frontend de Angular consuma la API desde:
#   - localhost / 127.0.0.1 (mismo equipo)
#   - cualquier dispositivo en la red local (192.168.x.x, 10.x.x.x, 172.16-31.x.x)
# en cualquier puerto. Se usa allow_origin_regex porque con allow_credentials=True
# no se permite el comodín "*".
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
    allow_origins=settings.cors_origins_list,  # dominios del front en producción (CORS_ORIGINS)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(Router_Rol)
app.include_router(Router_Usuario)
app.include_router(Router_Empresa)
app.include_router(Router_AreaTrabajo)
app.include_router(Router_PuertaAcceso)
app.include_router(Router_Trabajador)
app.include_router(Router_Asistencia)
app.include_router(Router_Escaneo)
app.include_router(Router_Scanner)
app.include_router(Router_Dispositivo)
app.include_router(Router_Incidencia)
app.include_router(Router_Embedding)
app.include_router(Router_IntentoAcceso)
app.include_router(Router_Reporte)


@app.get("/health", tags=["Health"])
def health():
    # Verifica la conexión a la BD en vivo (útil para el healthcheck de Docker).
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        logger.warning("Healthcheck: BD no disponible: %s", exc)
        db_ok = False

    payload = {
        "status": "ok" if db_ok else "degraded",
        "version": settings.APP_VERSION,
        "database": "ok" if db_ok else "down",
    }

    if not db_ok:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=payload,
        )
    return payload
