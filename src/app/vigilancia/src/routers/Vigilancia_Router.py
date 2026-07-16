# vigilancia/routers/Vigilancia_Router.py
# API de gestión de cámaras/terminales. La autorización por SCOPE la aplica el guard
# global (vigilancia:read en GET, vigilancia:write en POST/PATCH/DELETE, según la ruta);
# aquí se hace la autorización por EMPRESA (una empresa no ve/toca cámaras de otra).
import urllib.error

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from src.core.auth import Principal, exigir_empresa, resolver_empresa_scope, usuario_actual
from src.core.pgdb import get_db
from src.schemas.Camara_Schema import CamaraCreate, CamaraOut, CamaraUpdate
from src.services.Camara_Service import camara_service
from src.services.GrupoDvr_Service import grupo_dvr_service
from src.services import Snapshot_Service

router = APIRouter(prefix="/vigilancia", tags=["Vigilancia"])


# ── Estado ────────────────────────────────────────────────────────────────────
@router.get("/estado", summary="Estado del servicio + conteo de cámaras")
def estado(db: Session = Depends(get_db), id_empresa: int | None = Depends(resolver_empresa_scope)):
    total = db.execute(
        text("SELECT COUNT(*) FROM camaras WHERE (:emp IS NULL OR id_empresa = :emp)"),
        {"emp": id_empresa},
    ).scalar()
    habilitadas = db.execute(
        text("SELECT COUNT(*) FROM camaras WHERE habilitada = TRUE AND (:emp IS NULL OR id_empresa = :emp)"),
        {"emp": id_empresa},
    ).scalar()
    return {"service": "vigilancia", "empresa": id_empresa, "camaras": total, "habilitadas": habilitadas}


# ── Helper: trae la cámara y valida que sea de la empresa del principal ─────────
def _cam_de_empresa(db: Session, id_camara: int, principal: Principal):
    cam = camara_service.obtener(db, id_camara)
    if cam is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cámara no encontrada.")
    exigir_empresa(principal, cam.id_empresa)
    return cam


# ── Helper: datos de conexión (host + credenciales) para el snapshot ────────────
# El GRUPO DVR aporta la IP (host) y la contraseña; la cámara puede sobreescribir el
# host (IP directa) y/o traer su propia credencial. Precedencia: lo de la cámara si lo
# tiene, si no lo del grupo. Así una cámara "detrás de un DVR" solo pone su canal.
def _conexion_camara(db: Session, cam) -> tuple[str | None, str | None, str | None]:
    grupo = grupo_dvr_service.obtener(db, cam.id_grupo_dvr) if cam.id_grupo_dvr else None
    host = cam.host or (grupo.host if grupo is not None else None)
    if cam.credencial_cifrada:
        return host, cam.usuario, camara_service.credencial_clara(cam)
    if grupo is not None:
        return host, (cam.usuario or grupo.usuario), grupo_dvr_service.credencial_clara(grupo)
    return host, cam.usuario, camara_service.credencial_clara(cam)


# ── CRUD ──────────────────────────────────────────────────────────────────────
@router.post("/camaras", response_model=CamaraOut, status_code=status.HTTP_201_CREATED,
             summary="Crear cámara/terminal (cifra la credencial)")
def crear_camara(payload: CamaraCreate, db: Session = Depends(get_db),
                 principal: Principal = Depends(usuario_actual)):
    exigir_empresa(principal, payload.id_empresa)
    try:
        return camara_service.crear(db, payload)
    except (IntegrityError, DataError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"No se pudo crear la cámara (dato inválido o nombre/host duplicado): {exc.orig}")


@router.get("/camaras", response_model=list[CamaraOut], summary="Listar cámaras (por empresa)")
def listar_camaras(db: Session = Depends(get_db), id_empresa: int | None = Depends(resolver_empresa_scope)):
    return camara_service.listar(db, id_empresa)


@router.get("/camaras/{id_camara}", response_model=CamaraOut, summary="Detalle de una cámara")
def detalle_camara(id_camara: int, db: Session = Depends(get_db),
                   principal: Principal = Depends(usuario_actual)):
    return _cam_de_empresa(db, id_camara, principal)


@router.patch("/camaras/{id_camara}", response_model=CamaraOut, summary="Actualizar una cámara")
def actualizar_camara(id_camara: int, payload: CamaraUpdate, db: Session = Depends(get_db),
                      principal: Principal = Depends(usuario_actual)):
    cam = _cam_de_empresa(db, id_camara, principal)
    try:
        return camara_service.actualizar(db, cam, payload)
    except (IntegrityError, DataError) as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"No se pudo actualizar (dato inválido o duplicado): {exc.orig}")


@router.delete("/camaras/{id_camara}", status_code=status.HTTP_204_NO_CONTENT, summary="Eliminar una cámara")
def eliminar_camara(id_camara: int, db: Session = Depends(get_db),
                    principal: Principal = Depends(usuario_actual)):
    cam = _cam_de_empresa(db, id_camara, principal)
    camara_service.eliminar(db, cam)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Prueba de conexión / snapshot (usan la credencial descifrada en memoria) ────
@router.post("/camaras/{id_camara}/test-conexion", summary="Probar el snapshot ISAPI de la cámara")
def test_conexion(id_camara: int, db: Session = Depends(get_db),
                  principal: Principal = Depends(usuario_actual)):
    cam = _cam_de_empresa(db, id_camara, principal)
    host, usuario, password = _conexion_camara(db, cam)
    url = Snapshot_Service.construir_url(cam, host=host)
    try:
        data = Snapshot_Service.obtener_snapshot(url, usuario, password, timeout=8.0)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "url": url, "mensaje": f"HTTP {exc.code} — {exc.reason} (¿usuario/contraseña o canal?)."}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "url": url, "mensaje": f"No se pudo alcanzar la cámara: {exc}"}
    dim = Snapshot_Service.dimensiones_jpeg(data)
    return {
        "ok": True,
        "url": url,
        "bytes": len(data),
        "es_jpeg": Snapshot_Service.es_jpeg(data),
        "resolucion": (f"{dim[0]}x{dim[1]}" if dim else None),
        "mensaje": "Conexión OK: snapshot recibido.",
    }


@router.get("/camaras/{id_camara}/snapshot", summary="Devuelve un snapshot JPEG en vivo de la cámara")
def snapshot(id_camara: int, db: Session = Depends(get_db),
             principal: Principal = Depends(usuario_actual)):
    cam = _cam_de_empresa(db, id_camara, principal)
    host, usuario, password = _conexion_camara(db, cam)
    url = Snapshot_Service.construir_url(cam, host=host)
    try:
        data = Snapshot_Service.obtener_snapshot(url, usuario, password, timeout=8.0)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"No se pudo obtener el snapshot de la cámara: {exc}")
    return Response(content=data, media_type="image/jpeg")
