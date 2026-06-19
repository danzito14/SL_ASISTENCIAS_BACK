# app/api/v1/endpoints/escaneo.py
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from src.core.auth import exigir_empresa, resolver_empresa_scope, usuario_actual
from src.core.pgdb import get_db
from src.models.Rol_Usuario_Model import Usuario
from src.schemas.Escaneo_Schema import EscaneoCreate, EscaneoResponse, EscaneoUpdate
from src.services.Escaneo_Service import escaneo_service

router = APIRouter(prefix="/escaneos", tags=["Escaneos"])


# ── Registrar escaneo (manual) ────────────────────────────────────────────────
@router.post(
    "",
    response_model=EscaneoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar escaneo",
    description="Crea un escaneo manualmente. La ubicación (opcional) se envía como latitud/longitud.",
)
def registrar_escaneo(
    datos: EscaneoCreate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # Encapsulación: solo puedes registrar escaneos de trabajadores de TU empresa.
    exigir_empresa(usuario, escaneo_service.empresa_de_trabajador(datos.id_trabajador, db))
    return escaneo_service.registrar_escaneo(datos=datos, db=db)


# ── Listar escaneos ───────────────────────────────────────────────────────────
@router.get(
    "",
    response_model=list[EscaneoResponse],
    summary="Listar escaneos",
    description="Devuelve los escaneos (más recientes primero, con paginación).",
)
def listar_escaneos(
    id_empresa: int | None = Depends(resolver_empresa_scope),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    id_trabajador: int | None = Query(None, description="Filtrar por trabajador"),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # Si filtras por trabajador, debe ser de tu empresa.
    if id_trabajador is not None:
        exigir_empresa(usuario, escaneo_service.empresa_de_trabajador(id_trabajador, db))
    return escaneo_service.listar_escaneos(
        db=db, skip=skip, limit=limit, id_trabajador=id_trabajador, id_empresa=id_empresa
    )


# ── Obtener escaneo por id ────────────────────────────────────────────────────
@router.get(
    "/{id_escaneo}",
    response_model=EscaneoResponse,
    summary="Obtener escaneo",
    description="Devuelve un escaneo por su id.",
)
def obtener_escaneo(
    id_escaneo: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    exigir_empresa(usuario, escaneo_service.empresa_de_escaneo(id_escaneo, db))
    return escaneo_service.obtener_escaneo(id_escaneo=id_escaneo, db=db)


# ── Actualizar escaneo ────────────────────────────────────────────────────────
@router.put(
    "/{id_escaneo}",
    response_model=EscaneoResponse,
    summary="Actualizar escaneo",
    description="Actualiza los campos enviados de un escaneo. Para cambiar la ubicación, envía 'latitud' y 'longitud'.",
)
def actualizar_escaneo(
    id_escaneo: int,
    datos: EscaneoUpdate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    exigir_empresa(usuario, escaneo_service.empresa_de_escaneo(id_escaneo, db))
    return escaneo_service.actualizar_escaneo(id_escaneo=id_escaneo, datos=datos, db=db)


# ── Eliminar escaneo (baja lógica) ────────────────────────────────────────────
@router.delete(
    "/{id_escaneo}",
    response_model=EscaneoResponse,
    summary="Cancelar escaneo",
    description="Baja lógica: marca el escaneo como 'cancelado' (no borra la fila).",
)
def eliminar_escaneo(
    id_escaneo: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    exigir_empresa(usuario, escaneo_service.empresa_de_escaneo(id_escaneo, db))
    return escaneo_service.eliminar_escaneo(id_escaneo=id_escaneo, db=db)
