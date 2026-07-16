# vigilancia/routers/GruposDvr_Router.py
# API de grupos_dvr (agrupan cámaras de SEGUIMIENTO por DVR) + el endpoint INTERNO que
# le entrega al supervisor reid su config (grupos con credenciales DESCIFRADAS + cámaras
# de seguimiento). Así el reid NO toca la BD ni la llave Fernet: pide su config por HTTP.
#
# - CRUD /vigilancia/grupos_dvr : protegido por scope (vigilancia:read/write) + empresa,
#   igual que /vigilancia/camaras (el guard global calcula el scope desde el 1er segmento).
# - GET  /vigilancia/reid/config : ruta PÚBLICA para el guard de scopes (no la consume el
#   front), pero exige el token interno X-Reid-Token → entrega credenciales en claro SOLO
#   al supervisor reid, nunca a un usuario del gateway.
import urllib.error

from fastapi import (APIRouter, Depends, File, Form, HTTPException, Request, Response,
                     UploadFile, status)
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from src.core.auth import Principal, exigir_empresa, resolver_empresa_scope, usuario_actual
from src.core.config import settings
from src.core.pgdb import get_db
from src.models.Camara_Model import Camara
from src.models.GrupoDvr_Model import GrupoDvr
from src.schemas.GrupoDvr_Schema import GrupoDvrCreate, GrupoDvrOut, GrupoDvrUpdate
from src.schemas.Reid_Schema import AvistamientoIn
from src.services import Snapshot_Service
from src.services.Dvr_Service import listar_canales
from src.services.GrupoDvr_Service import grupo_dvr_service
from src.services.Recognition_Client import recognition_client
from src.services.Reid_Service import UMBRAL_DEFAULT, reid_service

router = APIRouter(prefix="/vigilancia", tags=["Vigilancia — Grupos DVR / Reid"])


# ── Helper: trae el grupo y valida que sea de la empresa del principal ──────────
def _grupo_de_empresa(db: Session, id_grupo_dvr: int, principal: Principal) -> GrupoDvr:
    grupo = grupo_dvr_service.obtener(db, id_grupo_dvr)
    if grupo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Grupo DVR no encontrado.")
    exigir_empresa(principal, grupo.id_empresa)
    return grupo


# ── CRUD de grupos_dvr ──────────────────────────────────────────────────────────
@router.post("/grupos_dvr", response_model=GrupoDvrOut, status_code=status.HTTP_201_CREATED,
             summary="Crear grupo DVR (cifra la credencial)")
def crear_grupo(payload: GrupoDvrCreate, db: Session = Depends(get_db),
                principal: Principal = Depends(usuario_actual)):
    exigir_empresa(principal, payload.id_empresa)
    try:
        return grupo_dvr_service.crear(db, payload)
    except (IntegrityError, DataError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"No se pudo crear el grupo DVR (dato inválido o nombre duplicado): {exc.orig}")


@router.get("/grupos_dvr", response_model=list[GrupoDvrOut], summary="Listar grupos DVR (por empresa)")
def listar_grupos(db: Session = Depends(get_db), id_empresa: int | None = Depends(resolver_empresa_scope)):
    return grupo_dvr_service.listar(db, id_empresa)


@router.get("/grupos_dvr/{id_grupo_dvr}", response_model=GrupoDvrOut, summary="Detalle de un grupo DVR")
def detalle_grupo(id_grupo_dvr: int, db: Session = Depends(get_db),
                  principal: Principal = Depends(usuario_actual)):
    return _grupo_de_empresa(db, id_grupo_dvr, principal)


@router.patch("/grupos_dvr/{id_grupo_dvr}", response_model=GrupoDvrOut, summary="Actualizar un grupo DVR")
def actualizar_grupo(id_grupo_dvr: int, payload: GrupoDvrUpdate, db: Session = Depends(get_db),
                     principal: Principal = Depends(usuario_actual)):
    grupo = _grupo_de_empresa(db, id_grupo_dvr, principal)
    try:
        return grupo_dvr_service.actualizar(db, grupo, payload)
    except (IntegrityError, DataError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"No se pudo actualizar (dato inválido o duplicado): {exc.orig}")


@router.delete("/grupos_dvr/{id_grupo_dvr}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Eliminar un grupo DVR")
def eliminar_grupo(id_grupo_dvr: int, db: Session = Depends(get_db),
                   principal: Principal = Depends(usuario_actual)):
    grupo = _grupo_de_empresa(db, id_grupo_dvr, principal)
    grupo_dvr_service.eliminar(db, grupo)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Descubrimiento de canales del DVR (para configurar cámaras desde el front) ──
# El front pide los canales del DVR (con nombre + preview) y el admin elige cuál asignar
# a cada cámara, sin adivinar. Usan el host + credencial del grupo (el DVR).
def _grupo_con_host(db: Session, id_grupo_dvr: int, principal: Principal) -> GrupoDvr:
    grupo = _grupo_de_empresa(db, id_grupo_dvr, principal)
    if not grupo.host:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="El grupo no tiene host (IP del DVR) configurado.")
    return grupo


@router.get("/grupos_dvr/{id_grupo_dvr}/canales",
            summary="Descubrir los canales/cámaras de un DVR (nombre + IP) para configurar")
def dvr_canales(id_grupo_dvr: int, db: Session = Depends(get_db),
                principal: Principal = Depends(usuario_actual)):
    grupo = _grupo_con_host(db, id_grupo_dvr, principal)
    password = grupo_dvr_service.credencial_clara(grupo)
    try:
        canales = listar_canales(grupo.host, grupo.usuario, password)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=(f"La credencial del grupo no sirve para el DVR {grupo.host}. Para "
                        "descubrir canales se necesita la contraseña DEL DVR (no la de cámara)."))
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"El DVR {grupo.host} respondió HTTP {exc.code}: {exc.reason}.")
    except Exception as exc:  # ISAPI caído, XML raro, timeout…
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"No se pudieron leer los canales del DVR {grupo.host}: {exc}")
    # URL lista para pedir el snapshot de cada canal (el front solo la usa al seleccionar).
    # Para canales IP añade ?ip= → el snapshot cae a la IP directa si el DVR no da imagen.
    base = f"/vigilancia/grupos_dvr/{id_grupo_dvr}/canales"
    for c in canales:
        url = f"{base}/{c['canal_rtsp']}/snapshot"
        if c["tipo"] == "ip" and c["ip_camara"]:
            url += f"?ip={c['ip_camara']}"
        c["snapshot_url"] = url
    return canales


@router.get("/grupos_dvr/{id_grupo_dvr}/canales/{canal}/snapshot",
            summary="Snapshot (JPEG) de un canal del DVR — preview para elegir la cámara")
def dvr_canal_snapshot(id_grupo_dvr: int, canal: int, ip: str | None = None,
                       db: Session = Depends(get_db),
                       principal: Principal = Depends(usuario_actual)):
    grupo = _grupo_con_host(db, id_grupo_dvr, principal)
    password = grupo_dvr_service.credencial_clara(grupo)
    from src.services.Rtsp_Service import frame_jpeg   # import perezoso (cv2 solo aquí)

    def _isapi(host: str, canal_pic: int, pwd: str | None) -> bytes | None:
        try:
            data = Snapshot_Service.obtener_snapshot(
                f"http://{host}/ISAPI/Streaming/channels/{canal_pic}/picture",
                grupo.usuario, pwd, timeout=8.0)
            return data if Snapshot_Service.es_jpeg(data) else None
        except Exception:
            return None

    def _rtsp(host: str, canal_rtsp: int, pwd: str | None) -> bytes | None:
        return frame_jpeg(f"rtsp://{grupo.usuario}:{pwd}@{host}:554/Streaming/Channels/{canal_rtsp}")

    cam_pwd = grupo_dvr_service.credencial_camaras_clara(grupo) or password

    # 1) Si es cámara IP (viene ?ip=): su IP DIRECTA da el JPEG MÁS LIMPIO (ISAPI del propio
    #    equipo). Se prefiere sobre el RTSP del DVR, que suele venir con artefactos.
    data = _isapi(ip, 101, cam_pwd) if ip else None

    # 2) POR EL DVR: ISAPI (analógicas dan JPEG limpio) → RTSP main→sub (IP en DVR limpio).
    if data is None:
        data = _isapi(grupo.host, canal, password) or _rtsp(grupo.host, canal, password)
        if data is None and canal % 100 == 1:
            data = _rtsp(grupo.host, canal + 1, password)

    # 3) Última red: RTSP directo de la cámara IP (main→sub).
    if data is None and ip:
        data = _rtsp(ip, 101, cam_pwd) or _rtsp(ip, 102, cam_pwd)

    if data is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"No se pudo obtener imagen del canal {canal} del DVR {grupo.host}.")
    return Response(content=data, media_type="image/jpeg")


# ── Config INTERNA del supervisor reid ──────────────────────────────────────────
# El supervisor reid pide su config por HTTP (REID_CONFIG_URL) en vez de leer un JSON
# a mano → NO toca BD ni la llave Fernet. Devuelve la MISMA forma que reid_config.json:
#   grupos_dvr: [{id, nombre, usuario, password}]   ← credenciales DESCIFRADAS
#   camaras:    [{id, nombre, grupo, host, canal, roi, habilitada, min_alto, sim_umbral, ...}]
# Como expone contraseñas en claro, es SOLO INTERNO: se protege con X-Reid-Token.
def _verificar_reid_token(request: Request) -> None:
    esperado = settings.REID_INTERNAL_TOKEN
    # Fail-closed: si hay token configurado, DEBE venir y coincidir. Vacío = no se exige
    # (dev), siguiendo la convención de GATEWAY_INTERNAL_TOKEN.
    if esperado and request.headers.get("X-Reid-Token") != esperado:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Token interno del reid ausente o inválido.")


@router.get("/reid/config", summary="[INTERNO] Config del supervisor reid (credenciales descifradas)")
def reid_config(request: Request, db: Session = Depends(get_db), id_empresa: int | None = None):
    _verificar_reid_token(request)

    grupos_q = db.query(GrupoDvr).filter(GrupoDvr.estado == "activo")
    cams_q = db.query(Camara).filter(Camara.tipo_camara == "seguimiento")
    if id_empresa is not None:
        grupos_q = grupos_q.filter(GrupoDvr.id_empresa == id_empresa)
        cams_q = cams_q.filter(Camara.id_empresa == id_empresa)

    grupos_rows = grupos_q.order_by(GrupoDvr.id_grupo_dvr).all()
    grupo_host = {g.id_grupo_dvr: g.host for g in grupos_rows}   # IP del DVR por grupo
    grupos = [
        {
            "id": g.id_grupo_dvr,
            "nombre": g.nombre,
            "usuario": g.usuario or "",
            "password": grupo_dvr_service.credencial_clara(g) or "",
        }
        for g in grupos_rows
    ]

    camaras = []
    for c in cams_q.order_by(Camara.id_camara).all():
        # Host EFECTIVO: el de la cámara (IP directa) gana; si va vacío, hereda el del grupo (DVR).
        host = c.host or grupo_host.get(c.id_grupo_dvr)
        cam = {
            **(c.params_reid or {}),          # min_alto, sim_umbral, ... (los canónicos ganan abajo)
            "id": c.id_camara,
            "nombre": c.nombre,
            "grupo": c.id_grupo_dvr,
            "host": host,
            "canal": c.canal,
            "roi": c.roi_poligono or "",
            "habilitada": c.habilitada,
            "tipo_conexion": c.tipo_conexion,
        }
        camaras.append(cam)

    return {"grupos_dvr": grupos, "camaras": camaras}


# ── Seguimiento corporal (reid) — galería compartida ────────────────────────────
# INTERNO: el motor de seguimiento manda la firma OSNet de una detección nueva y aquí
# se resuelve su persona GLOBAL (misma persona = mismo id entre cámaras) + se registra
# el avistamiento. Ruta PÚBLICA para el guard de scopes, protegida por X-Reid-Token.
@router.post("/reid/avistamiento",
             summary="[INTERNO] Registrar avistamiento y resolver la persona global")
def reid_avistamiento(payload: AvistamientoIn, request: Request, db: Session = Depends(get_db)):
    _verificar_reid_token(request)
    if len(payload.embedding) != 512:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"embedding debe tener 512 floats (llegaron {len(payload.embedding)}).")
    id_empresa, tipo = reid_service.empresa_de_camara(db, payload.id_camara)
    if id_empresa is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Cámara {payload.id_camara} no existe.")
    umbral = payload.umbral if payload.umbral is not None else UMBRAL_DEFAULT
    return reid_service.procesar_avistamiento(
        db, id_empresa=id_empresa, id_camara=payload.id_camara, embedding=payload.embedding,
        bbox=payload.bbox, ruta_crop=payload.ruta_crop, umbral=umbral,
    )


# ── Paso del ROSTRO: anclar identidad a una persona ─────────────────────────────
# El motor manda el recorte de una detección FRONTAL de una persona AÚN SIN identidad;
# aquí se pasa a recognition /identificar (mismo motor de asistencia, sin registrar) y,
# si reconoce, se ANCLA reid_personas.id_trabajador → sus avistamientos por cuerpo (en
# cámaras cenitales, sin cara) heredan el NOMBRE. Una persona por llamada (un recorte = una
# cara); varias personas = varias llamadas. INTERNO (X-Reid-Token).
@router.post("/reid/identificar",
             summary="[INTERNO] Identificar por rostro y anclar la identidad a una persona")
def reid_identificar(request: Request, id_persona: int = Form(...), foto: UploadFile = File(...),
                     db: Session = Depends(get_db)):
    _verificar_reid_token(request)
    persona = reid_service.obtener_persona(db, id_persona)
    if persona is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Persona {id_persona} no existe.")
    if persona["id_trabajador"]:   # ya identificada → idempotente, no re-consulta recognition
        return {"reconocido": True, "id_trabajador": persona["id_trabajador"],
                "nombre": persona["etiqueta"], "ya_identificada": True}

    contenido = foto.file.read()
    try:
        res = recognition_client.identificar(contenido, id_empresa=persona["id_empresa"])
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"recognition no disponible: {exc}")
    if not res.get("reconocido"):
        return {"reconocido": False, "estado": res.get("estado"), "det_score": res.get("det_score")}

    t = res["trabajador"]
    etiqueta = f"{t.get('nombre', '')} {t.get('apellido', '')}".strip() or f"trab-{t['id_trabajador']}"
    reid_service.anclar_identidad(db, id_persona, t["id_trabajador"], etiqueta)
    return {"reconocido": True, "id_trabajador": t["id_trabajador"], "nombre": etiqueta,
            "similitud": res.get("similitud")}


# ── Consulta (front) — personas y avistamientos. Protegidos por scope vigilancia:read.
@router.get("/reid/personas", summary="Personas (clusters de apariencia) detectadas por reid")
def reid_personas(db: Session = Depends(get_db), id_empresa: int | None = Depends(resolver_empresa_scope)):
    return reid_service.listar_personas(db, id_empresa)


@router.get("/reid/avistamientos", summary="Log de avistamientos (dónde/cuándo se vio a cada persona)")
def reid_avistamientos(
    id_persona: int | None = None,
    desde: str | None = None,   # ISO8601, ej. 2026-07-13T00:00:00
    hasta: str | None = None,
    db: Session = Depends(get_db),
    id_empresa: int | None = Depends(resolver_empresa_scope),
):
    return reid_service.listar_avistamientos(
        db, id_empresa, id_persona=id_persona, desde=desde, hasta=hasta,
    )
