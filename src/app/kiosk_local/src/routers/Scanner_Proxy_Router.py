# kiosk_local/routers/Scanner_Proxy_Router.py
"""
/scanner/* con el MISMO contrato que la nube, servido por el back LOCAL.

Antes había dos escáneres: el de la nube (`/scanner/...` en el micro `back`) y uno
paralelo en el kiosko (`/kiosk/acceso`), con rutas y respuestas distintas. El front
tenía que saber en cuál estaba. Aquí se fusionan: el kiosko levanta el MISMO `back`
(con MODO_KIOSKO=true, contra la BD de la estación) y este router le reenvía las
peticiones tal cual. Resultado: **las mismas rutas y el mismo ScanResponse online y
offline**; lo único que cambia es a qué host apunta el front (o ni eso, si apunta
siempre a localhost).

kiosk_local hace de GATEWAY del back local. El back no valida el JWT: confía en los
headers X-* que en prod inyecta Traefik tras el ForwardAuth a identity. Aquí los pone
este proxy, con la empresa del último sync (la del usuario logueado), y BACKEND_GATEWAY_TOKEN
prueba que la petición vino de aquí y no de alguien hablándole directo al contenedor.

El cuerpo se reenvía SIN parsear: el multipart pasa intacto, así que este proxy no se
tiene que enterar de si el endpoint recibe `foto` o una ráfaga `fotos`, ni romperse
cuando la nube agregue parámetros nuevos.
"""
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from src.core import meta
from src.core.config import settings
from src.core.pgdb import get_db
from src.services.Cloud_Client import cloud_client
from src.services.Escaneo_Service import escaneo_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scanner", tags=["Scanner (contrato de la nube)"])

# Rutas de FICHAJE: son las que necesitan id_puerta y las únicas con fallback a la nube.
RUTAS_ACCESO = frozenset({"acceso/foto", "acceso/liveness"})

# Cliente reusado: abrir uno por request agregaría handshake a cada frame del kiosko.
_cliente = httpx.AsyncClient(base_url=settings.BACKEND_LOCAL_URL, timeout=settings.BACKEND_TIMEOUT)


async def cerrar_cliente() -> None:
    """La cierra el lifespan de main.py al apagar el servicio."""
    await _cliente.aclose()


def _empresa_activa(db: Session) -> int:
    """Empresa del último sync (sigue al usuario logueado); si no hay, la del .env."""
    empresa = meta.empresa_actual(db) or settings.KIOSK_EMPRESA
    if empresa is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La estación todavía no tiene empresa. Baja el roster primero (POST /kiosk/roster/sync).",
        )
    return int(empresa)


def _cabeceras_gateway(db: Session, content_type: str) -> dict[str, str]:
    cabeceras = {
        "Content-Type": content_type,
        # Identidad que el back espera del gateway (auth.py::_principal_desde_headers).
        "X-Empresa": str(_empresa_activa(db)),
        "X-Scopes": "scanner:use",
        "X-Rol": "escaneador",
        "X-Nombre-Usuario": settings.KIOSK_USER or "kiosko",
    }
    if settings.BACKEND_GATEWAY_TOKEN:
        cabeceras["X-Gateway-Token"] = settings.BACKEND_GATEWAY_TOKEN
    return cabeceras


def _no_reconocido(datos) -> bool:
    """True si el back local respondió 'no reconocido' (el único caso que la nube podría
    resolver: alguien enrolado después del último sync del roster)."""
    if not isinstance(datos, dict) or datos.get("acceso") is not False:
        return False
    return "no reconocido" in (datos.get("mensaje") or "").lower()


def _respuesta(r: httpx.Response) -> Response:
    return Response(content=r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type"))


@router.post(
    "/{resto:path}",
    summary="Escáner con el contrato de la nube, resuelto en LOCAL",
    description="Reenvía /scanner/* al back local (MODO_KIOSKO). Mismas rutas, mismos "
                "parámetros y mismo ScanResponse que la nube: /scanner/identificar/foto, "
                "/scanner/acceso/foto, /scanner/acceso/liveness. `id_puerta` es opcional "
                "aquí (si falta se usa la puerta de la estación).",
)
async def proxy_scanner(resto: str, request: Request, db: Session = Depends(get_db)):
    cuerpo = await request.body()
    params = dict(request.query_params)
    content_type = request.headers.get("content-type", "application/octet-stream")

    # En la nube id_puerta es obligatorio; en la estación se conoce sola (kiosk_meta →
    # KIOSK_PUERTA → 1ª puerta activa del roster), así el front no la tiene que mandar.
    if resto in RUTAS_ACCESO and not params.get("id_puerta"):
        try:
            params["id_puerta"] = str(await run_in_threadpool(escaneo_service.puerta_estacion, db, None))
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    cabeceras = _cabeceras_gateway(db, content_type)
    try:
        r = await _cliente.post(f"/scanner/{resto}", params=params, content=cuerpo, headers=cabeceras)
    except httpx.HTTPError as exc:
        logger.error("scanner: el back local no responde: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"Back local no disponible: {exc}")

    if not (settings.KIOSK_SCANNER_FALLBACK_NUBE and resto in RUTAS_ACCESO):
        return _respuesta(r)

    try:
        datos = r.json()
    except ValueError:
        return _respuesta(r)
    if not _no_reconocido(datos):
        return _respuesta(r)

    # Fallback a la nube (apagado por default). hay_conexion_cache evita pagar un sondeo
    # de red en CADA frame no reconocido, que es lo que hacía lento al escáner local.
    if not await run_in_threadpool(cloud_client.hay_conexion_cache):
        return _respuesta(r)
    try:
        rn = await run_in_threadpool(cloud_client.reenviar_scanner,
                                     f"/scanner/{resto}", params, cuerpo, content_type)
        if rn.status_code < 400:
            return _respuesta(rn)
        logger.warning("scanner: fallback a la nube respondió %s", rn.status_code)
    except Exception as exc:
        logger.warning("scanner: fallback a la nube falló: %s", exc)
    return _respuesta(r)
