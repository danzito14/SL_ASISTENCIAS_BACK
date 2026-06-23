# identity/main.py — microservicio de identidad (login, JWT, usuarios, roles)
import logging
from contextlib import asynccontextmanager

import jwt
from fastapi import Depends, FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.core.config import settings
from src.core.pgdb import engine
from src.core.auth import guard_scopes, oauth2_scheme
from src.core.security import decode_access_token
import src.models  # noqa: F401 — registra los modelos en el registry de Base
from src.routers.Usuario_Router import router as Router_Usuario
from src.routers.Rol_Router import router as Router_Rol

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
        logger.info("identity: conexión a la BD OK (%s como %s).", settings.DB_NAME, settings.DB_USER)
    except Exception as exc:
        logger.error("identity: no se pudo conectar a la BD: %s", exc)
        raise RuntimeError(
            f"No se pudo conectar a la base de datos en "
            f"{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}."
        ) from exc
    yield


app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    debug=settings.DEBUG,
    lifespan=lifespan,
    # Guard global: token + scope del rol (salvo rutas públicas: login/token/health/docs).
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

app.include_router(Router_Usuario)
app.include_router(Router_Rol)


# Rutas que el gateway deja pasar sin token (igual que el guard de cada servicio).
_GW_PUBLICAS = {"/", "/health", "/openapi.json", "/redoc", "/docs/oauth2-redirect"}


@app.api_route(
    "/validate",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"],
    include_in_schema=False,
)
def validate(request: Request):
    """
    Endpoint del ForwardAuth de Traefik: AUTENTICACIÓN centralizada del sistema.
    Valida la firma/expiración del JWT UNA sola vez en el borde y devuelve la
    identidad en headers X-* (204) o rechaza (401). Los demás microservicios
    confían en esos headers en vez de revalidar el token.
    """
    # Preflight CORS: el OPTIONS nunca trae token. Se deja pasar para que el servicio
    # destino responda los headers CORS (la petición real GET/POST sí se valida).
    if request.headers.get("X-Forwarded-Method", "").upper() == "OPTIONS":
        return Response(status_code=204)

    # Path ORIGINAL que pidió el cliente (Traefik lo reenvía en X-Forwarded-Uri).
    path = request.headers.get("X-Forwarded-Uri", "").split("?", 1)[0]
    if path in _GW_PUBLICAS or path.startswith("/docs"):
        return Response(status_code=204)  # ruta pública: pasa sin exigir token

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
    token = auth.removeprefix("Bearer ").strip()
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        return Response(status_code=401, headers={"X-Auth-Error": "expired"})
    except jwt.InvalidTokenError:
        return Response(status_code=401, headers={"X-Auth-Error": "invalid"})

    sub = payload.get("sub")
    empresa = payload.get("empresa")
    id_rol = payload.get("id_rol")
    scopes = payload.get("scopes")
    return Response(
        status_code=204,
        headers={
            "X-User-Id": str(sub) if sub is not None else "",
            "X-Empresa": str(empresa) if empresa is not None else "",
            "X-Scopes": " ".join(scopes) if isinstance(scopes, list) else "",
            "X-Rol": payload.get("rol") or "",
            "X-Id-Rol": str(id_rol) if id_rol is not None else "",
            "X-Nombre-Usuario": payload.get("nombre_usuario") or "",
        },
    )


@app.get("/health", tags=["Health"])
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:
        logger.warning("identity healthcheck: BD no disponible: %s", exc)
        db_ok = False

    payload = {"status": "ok" if db_ok else "degraded", "version": settings.APP_VERSION,
               "service": "identity", "database": "ok" if db_ok else "down"}
    if not db_ok:
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)
    return payload
