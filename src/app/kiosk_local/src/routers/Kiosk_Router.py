# kiosk_local/routers/Kiosk_Router.py
# API LOCAL del kiosko (localhost). Fase 1: bajar el roster de la nube → BD local.
# (Fase 2: POST /kiosk/acceso reconoce offline; Fase 3: loop de subida de eventos.)
import logging

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.core import meta
from src.core.config import settings
from src.core.pgdb import get_db
from src.services.Cloud_Client import cloud_client
from src.services.Escaneo_Service import escaneo_service
from src.services.Intento_Service import intento_service
from src.services.Recognition_Client import recognition_client
from src.services.Roster_Loader import roster_loader
from src.services.Sync_Service import sync_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/kiosk", tags=["Kiosk Local"])


def _token_bearer(authorization: str | None) -> str | None:
    """Extrae el token de un header 'Authorization: Bearer <token>' (o None)."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


# Pistas para el front cuando un frame es de baja calidad (gate de recognition).
_PISTA_CALIDAD = {
    "borrosa": "Imagen borrosa: mantente quieto frente a la cámara.",
    "cara_parcial": "Ubica toda tu cara dentro del recuadro.",
    "muy_lejos": "Acércate un poco a la cámara.",
    "deteccion_debil": "Acomódate frente a la cámara con buena luz.",
}


def _resp_baja_calidad(res: dict) -> dict:
    return {"acceso": False, "origen": "local", "estado": "baja_calidad",
            "motivo": res.get("motivo"),
            "mensaje": _PISTA_CALIDAD.get(res.get("motivo"), "Acomódate frente a la cámara.")}


@router.post(
    "/roster/sync",
    summary="Bajar el roster de la nube y cargarlo en la BD LOCAL (reemplazo total)",
    description="Login como el usuario kiosko (define la empresa) → GET /off_sync/roster "
                "→ REEMPLAZA el padrón local (vacía trabajadores+embeddings y recarga) para "
                "que quede SOLO esa empresa/tipo (búsqueda más rápida; sin residuos al cambiar "
                "de empresa). La cola de fichajes pendientes se conserva. Se descarga PRIMERO: "
                "si no hay internet, no se borra nada. reemplazar=false = merge (UPSERT).",
)
def sync_roster(
    tipo: str | None = Query(None, description="campo|oficina|empaque|mixto (default: KIOSK_TIPO)"),
    reemplazar: bool = Query(True, description="true = reemplazo total (default); false = merge/UPSERT sin vaciar"),
    authorization: str | None = Header(None, description="Bearer <token> del usuario logueado en el front: la estación sigue SU empresa."),
    db: Session = Depends(get_db),
):
    t = (tipo or settings.KIOSK_TIPO).strip().lower()
    # Si el front reenvía el token del usuario logueado, la estación SIGUE a ese usuario:
    # el roster (y la subida) salen de SU empresa. Se persiste en kiosk_meta para el loop de
    # subida y para sobrevivir reinicios. Sin token → cae al KIOSK_USER de respaldo (empresa fija).
    token = _token_bearer(authorization)
    id_empresa = settings.KIOSK_EMPRESA
    if token:
        cloud_client.set_token(token)
        meta.escribir(db, "cloud_token", token)
        db.commit()
        id_empresa = None  # la empresa la define el token (server-side), no un id fijo
    try:
        # Descarga PRIMERO (fuera de la transacción de carga): si falla, se aborta ANTES
        # de tocar/vaciar el padrón local → la estación sigue con sus datos previos.
        roster = cloud_client.bajar_roster(t, id_empresa)
    except Exception as exc:
        logger.error("sync_roster: no se pudo bajar el roster de la nube: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"no se pudo bajar el roster de la nube: {exc}")
    try:
        return roster_loader.cargar(db, roster, reemplazar=reemplazar)
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
async def identificar(foto: UploadFile = File(..., description="Imagen del rostro (JPEG/PNG)"),
                      db: Session = Depends(get_db)):
    data = await foto.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La imagen está vacía.")
    id_empresa = meta.empresa_actual(db) or settings.KIOSK_EMPRESA
    try:
        res = await run_in_threadpool(recognition_client.reconocer, data, id_empresa)
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
    # Empresa ACTIVA = la del último sync (sigue al usuario logueado). Tras el reemplazo
    # total el padrón local es de UNA empresa; acotar el match a ella evita cualquier cruce.
    id_empresa = meta.empresa_actual(db) or settings.KIOSK_EMPRESA
    try:
        res = await run_in_threadpool(recognition_client.reconocer, data, id_empresa)
    except Exception as exc:
        logger.error("acceso: recognition local no disponible: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"recognition local no disponible: {exc}")
    estado = res.get("estado")

    # 0) FRAME DE BAJA CALIDAD (borroso, cara cortada, muy lejos): NO registrar, NO subir
    # a la cola y NO gastar el fallback a la nube. La webcam captura en continuo, así que
    # el próximo frame bueno pasa solo; solo devolvemos una pista para el front.
    if estado == "baja_calidad":
        return _resp_baja_calidad(res)

    # 1) MATCH LOCAL → registrar escaneo local (offline, en cola).
    if estado == "match":
        trab = res["trabajador"]
        id_esc = await run_in_threadpool(escaneo_service.registrar_local, db,
                                         trab["id_trabajador"], trab.get("similitud"),
                                         id_puerta, tipo_registro, id_empresa)
        return {"acceso": True, "origen": "local", "trabajador": trab, "id_escaneo": id_esc,
                "mensaje": f"Bienvenido {trab['nombre']} {trab['apellido']}."}

    # 2) SIN match local + hay internet → fallback a la NUBE (que ya registra el intento allá).
    #    Solo si NO hubo fallback exitoso se registra el intento LOCAL → evita el doble registro.
    if estado == "no_match":
        puerta = id_puerta if id_puerta is not None else settings.KIOSK_PUERTA
        if await run_in_threadpool(cloud_client.hay_conexion):
            try:
                nube = await run_in_threadpool(cloud_client.acceso_nube, data, puerta, tipo_registro)
                nube_out = {k: v for k, v in nube.items() if k != "recorte_b64"}
                return {"origen": "nube", **nube_out}   # la nube ya registró el intento
            except Exception as exc:
                logger.warning("acceso: fallback a la nube falló: %s", exc)
        # Sin internet o fallback falló → encolar el intento local (desconocido).
        sim = (res.get("candidato_global") or {}).get("similitud")
        await run_in_threadpool(intento_service.registrar_fallido, db, "no_match", id_empresa,
                                id_puerta, sim, res.get("recorte_b64"))
        return {"acceso": False, "origen": "local", "estado": "no_match",
                "mensaje": "Rostro no reconocido (sin match local ni en la nube)."}

    # 3) no_rostro / spoof → encolar el intento local (estos no tienen fallback a la nube).
    await run_in_threadpool(intento_service.registrar_fallido, db, estado, id_empresa,
                            id_puerta, None, res.get("recorte_b64"))
    return {"acceso": False, "origen": "local", "estado": estado,
            "mensaje": "No se reconoció un rostro válido."}


@router.post(
    "/acceso/liveness",
    summary="Fichar con PRUEBA DE VIDA (3-5 frames): reconoce LOCAL; fallback a la NUBE",
    description="Igual que /acceso pero con liveness multi-frame (como la web): manda la "
                "ráfaga a /reconocer-liveness, que valida MOVIMIENTO entre frames (una foto "
                "estática se rechaza como 'no_vivo') + anti-spoof pasivo, antes del match. "
                "Match local → registra local; sin match + internet → fallback a la nube.",
)
async def acceso_liveness(
    fotos: list[UploadFile] = File(..., description="3 a 5 imágenes del rostro (JPEG/PNG)"),
    id_puerta: int | None = Query(None, description="Puerta de fichaje (default: KIOSK_PUERTA / 1ª del roster)"),
    tipo_registro: str = Query("entrada"),
    db: Session = Depends(get_db),
):
    if len(fotos) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Envía al menos 2 fotos (recomendado 3-5) para la prueba de vida.")
    datos = [d for d in [await f.read() for f in fotos] if d]
    if len(datos) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fotos vacías o inválidas.")

    id_empresa = meta.empresa_actual(db) or settings.KIOSK_EMPRESA
    try:
        res = await run_in_threadpool(recognition_client.reconocer_liveness, datos, id_empresa)
    except Exception as exc:
        logger.error("acceso_liveness: recognition local no disponible: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"recognition local no disponible: {exc}")
    estado = res.get("estado")

    # Frames malos / pocos rostros → sigue intentando (la webcam captura en continuo).
    if estado == "baja_calidad":
        return _resp_baja_calidad(res)
    if estado == "pocos_rostros":
        return {"acceso": False, "origen": "local", "estado": "pocos_rostros",
                "mensaje": "Mantén la cara en cuadro un momento."}

    # PRUEBA DE VIDA fallida (foto estática, sin movimiento) → encolar intento + rechazar.
    if estado == "no_vivo":
        await run_in_threadpool(intento_service.registrar_fallido, db, "no_vivo", id_empresa,
                                id_puerta, None, res.get("recorte_b64"))
        return {"acceso": False, "origen": "local", "estado": "no_vivo", "motivo": res.get("motivo"),
                "mensaje": "Prueba de vida fallida (¿una foto?). Mira a la cámara y muévete un poco."}
    # Anti-spoof pasivo (foto/pantalla) → encolar intento + rechazar.
    if estado == "spoof":
        await run_in_threadpool(intento_service.registrar_fallido, db, "spoof", id_empresa,
                                id_puerta, None, res.get("recorte_b64"))
        return {"acceso": False, "origen": "local", "estado": "spoof",
                "mensaje": "Se detectó una foto o pantalla, no una persona real."}

    # MATCH LOCAL → registrar escaneo local (en cola).
    if estado == "match":
        trab = res["trabajador"]
        id_esc = await run_in_threadpool(escaneo_service.registrar_local, db,
                                         trab["id_trabajador"], trab.get("similitud"),
                                         id_puerta, tipo_registro, id_empresa)
        return {"acceso": True, "origen": "local", "trabajador": trab, "id_escaneo": id_esc,
                "mensaje": f"Bienvenido {trab['nombre']} {trab['apellido']}."}

    # SIN match local + internet → fallback a la NUBE (también con liveness). Solo si NO
    # hubo fallback exitoso se encola el intento LOCAL → evita el doble registro.
    if estado == "no_match":
        puerta = id_puerta if id_puerta is not None else settings.KIOSK_PUERTA
        if await run_in_threadpool(cloud_client.hay_conexion):
            try:
                nube = await run_in_threadpool(cloud_client.acceso_nube_liveness, datos, puerta, tipo_registro)
                nube_out = {k: v for k, v in nube.items() if k != "recorte_b64"}
                return {"origen": "nube", **nube_out}   # la nube ya registró el intento
            except Exception as exc:
                logger.warning("acceso_liveness: fallback a la nube falló: %s", exc)
        sim = (res.get("candidato_global") or {}).get("similitud")
        await run_in_threadpool(intento_service.registrar_fallido, db, "no_match", id_empresa,
                                id_puerta, sim, res.get("recorte_b64"))
        return {"acceso": False, "origen": "local", "estado": "no_match",
                "mensaje": "Rostro no reconocido (sin match local ni en la nube)."}

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
        asistencias = sync_service.subir_pendientes()
        intentos = sync_service.subir_intentos_pendientes()
        fotos = sync_service.subir_fotos_pendientes()
        return {"asistencias": asistencias, "intentos": intentos, "fotos": fotos}
    except Exception as exc:
        logger.error("sync_eventos: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"no se pudo subir la cola (¿sin internet?): {exc}")


@router.get("/estado", summary="Estado del roster local (conteos + versión)")
def estado(db: Session = Depends(get_db)):
    out: dict = {"trabajadores": 0, "embeddings_activos": 0, "pendientes_asistencias": 0,
                 "pendientes_intentos": 0, "pendientes_fotos": 0, "meta": {}}
    try:
        out["trabajadores"] = db.execute(text("SELECT count(*) FROM trabajadores")).scalar()
        out["embeddings_activos"] = db.execute(
            text("SELECT count(*) FROM embeddings WHERE estado = 'activo'")).scalar()
        # Colas pendientes de subir (para mostrarlas en Configuración del front).
        out["pendientes_asistencias"] = db.execute(
            text("SELECT count(*) FROM escaneos WHERE sincronizado_en IS NULL")).scalar()
        out["pendientes_intentos"] = db.execute(text(
            "SELECT count(*) FROM intentos_acceso WHERE sincronizado_en IS NULL AND NOT sync_rechazado")).scalar()
        out["pendientes_fotos"] = db.execute(text(
            "SELECT count(*) FROM intentos_acceso WHERE foto_bytes IS NOT NULL")).scalar()
        existe = db.execute(text("SELECT to_regclass('kiosk_meta')")).scalar()
        if existe:
            out["meta"] = {k: v for k, v in db.execute(text("SELECT clave, valor FROM kiosk_meta")).all()}
    except Exception as exc:
        logger.warning("estado: %s", exc)
    out["hay_conexion"] = cloud_client.hay_conexion()
    return out
