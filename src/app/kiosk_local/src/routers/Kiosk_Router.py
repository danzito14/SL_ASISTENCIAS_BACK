# kiosk_local/routers/Kiosk_Router.py
# API LOCAL del kiosko (localhost). Fase 1: bajar el roster de la nube → BD local.
# (Fase 2: POST /kiosk/acceso reconoce offline; Fase 3: loop de subida de eventos.)
import logging

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core.config import settings
from src.core.pgdb import get_db
from src.services.Cloud_Client import cloud_client
from src.services.Escaneo_Service import escaneo_service
from src.services.Recognition_Client import recognition_client
from src.services.Roster_Loader import roster_loader
from src.services.Sync_Service import sync_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/kiosk", tags=["Kiosk Local"])


@router.post(
    "/roster/sync",
    summary="Bajar el roster de la nube y cargarlo en la BD LOCAL",
    description="Login como el usuario kiosko (define la empresa) → GET /off_sync/roster "
                "→ UPSERT trabajadores+embeddings+áreas+puertas en el postgres local. "
                "Requiere internet SOLO en este paso; luego el kiosko reconoce offline.",
)
def sync_roster(
    tipo: str | None = Query(None, description="campo|oficina|empaque|mixto (default: KIOSK_TIPO)"),
    db: Session = Depends(get_db),
):
    t = (tipo or settings.KIOSK_TIPO).strip().lower()
    try:
        roster = cloud_client.bajar_roster(t, settings.KIOSK_EMPRESA)
    except Exception as exc:
        logger.error("sync_roster: no se pudo bajar el roster de la nube: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"no se pudo bajar el roster de la nube: {exc}")
    try:
        return roster_loader.cargar(db, roster)
    except Exception as exc:
        db.rollback()
        logger.error("sync_roster: error cargando el roster en la BD local: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=f"error cargando el roster local: {exc}")


@router.post(
    "/identificar",
    summary="Identificar un rostro contra el roster LOCAL (offline, sin registrar)",
    description="Manda la foto al recognition LOCAL → detecta + match pgvector contra el "
                "roster local. Devuelve el trabajador si hay match. NO registra asistencia.",
)
async def identificar(foto: UploadFile = File(..., description="Imagen del rostro (JPEG/PNG)")):
    data = await foto.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La imagen está vacía.")
    try:
        res = await run_in_threadpool(recognition_client.reconocer, data, settings.KIOSK_EMPRESA)
    except Exception as exc:
        logger.error("identificar: recognition local no disponible: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"recognition local no disponible: {exc}")
    res.pop("recorte_b64", None)   # no inflar la respuesta con el recorte b64
    return res


@router.post(
    "/acceso",
    summary="Fichar: reconoce LOCAL primero; si no hay match y hay internet, fallback a la NUBE",
    description="1) recognition local → match contra el roster local. Si hay match: REGISTRA "
                "el escaneo local (en cola para sync) y responde. 2) Si NO hay match local y "
                "hay internet: reenvía la foto al scanner de la nube (que reconoce contra toda "
                "la empresa y registra allá). 3) Sin internet: responde no reconocido.",
)
async def acceso(
    foto: UploadFile = File(..., description="Imagen del rostro (JPEG/PNG)"),
    id_puerta: int | None = Query(None, description="Puerta de fichaje (default: KIOSK_PUERTA / 1ª del roster)"),
    tipo_registro: str = Query("entrada"),
    db: Session = Depends(get_db),
):
    data = await foto.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La imagen está vacía.")
    try:
        res = await run_in_threadpool(recognition_client.reconocer, data, settings.KIOSK_EMPRESA)
    except Exception as exc:
        logger.error("acceso: recognition local no disponible: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"recognition local no disponible: {exc}")
    estado = res.get("estado")

    # 1) MATCH LOCAL → registrar escaneo local (offline, en cola).
    if estado == "match":
        trab = res["trabajador"]
        id_esc = await run_in_threadpool(escaneo_service.registrar_local, db,
                                         trab["id_trabajador"], trab.get("similitud"),
                                         id_puerta, tipo_registro)
        return {"acceso": True, "origen": "local", "trabajador": trab, "id_escaneo": id_esc,
                "mensaje": f"Bienvenido {trab['nombre']} {trab['apellido']}."}

    # 2) SIN match local + hay internet → fallback a la NUBE (reconoce y registra allá).
    if estado == "no_match":
        puerta = id_puerta if id_puerta is not None else settings.KIOSK_PUERTA
        if await run_in_threadpool(cloud_client.hay_conexion):
            try:
                nube = await run_in_threadpool(cloud_client.acceso_nube, data, puerta, tipo_registro)
                nube_out = {k: v for k, v in nube.items() if k != "recorte_b64"}
                return {"origen": "nube", **nube_out}
            except Exception as exc:
                logger.warning("acceso: fallback a la nube falló: %s", exc)
        return {"acceso": False, "origen": "local", "estado": "no_match",
                "mensaje": "Rostro no reconocido (sin match local ni en la nube)."}

    # 3) no_rostro / spoof.
    return {"acceso": False, "origen": "local", "estado": estado,
            "mensaje": "No se reconoció un rostro válido."}


@router.post(
    "/sync/eventos",
    summary="Subir YA la cola de escaneos a la nube (además del loop automático)",
    description="Fuerza un ciclo de subida: escaneos con sincronizado_en IS NULL → "
                "POST /off_sync/asistencias. El loop en background ya lo hace solo cada X seg.",
)
def sync_eventos():
    try:
        return sync_service.subir_pendientes()
    except Exception as exc:
        logger.error("sync_eventos: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"no se pudo subir la cola (¿sin internet?): {exc}")


@router.get("/estado", summary="Estado del roster local (conteos + versión)")
def estado(db: Session = Depends(get_db)):
    out: dict = {"trabajadores": 0, "embeddings_activos": 0, "meta": {}}
    try:
        out["trabajadores"] = db.execute(text("SELECT count(*) FROM trabajadores")).scalar()
        out["embeddings_activos"] = db.execute(
            text("SELECT count(*) FROM embeddings WHERE estado = 'activo'")).scalar()
        existe = db.execute(text("SELECT to_regclass('kiosk_meta')")).scalar()
        if existe:
            out["meta"] = {k: v for k, v in db.execute(text("SELECT clave, valor FROM kiosk_meta")).all()}
    except Exception as exc:
        logger.warning("estado: %s", exc)
    out["hay_conexion"] = cloud_client.hay_conexion()
    return out
