# app/api/v1/endpoints/area_trabajo.py
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from src.core.auth import exigir_empresa, resolver_empresa_scope, usuario_actual
from src.core.pgdb import get_db
from src.core.auth import Principal as Usuario
from src.schemas.AreaTrabajo_Trabajador import AreaTrabajoCreate, AreaTrabajoResponse, AreaTrabajoUpdate
from src.services.AreaTrabajo_Service import areatrabajo_service

router = APIRouter(prefix="/areas", tags=["Áreas de trabajo"])


# ── Registrar área de trabajo ─────────────────────────────────────────────────
@router.post(
    "",
    response_model=AreaTrabajoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar área de trabajo",
    description="Crea un área de trabajo a la que luego se podrán asignar trabajadores.",
)
def registrar_area(
    datos: AreaTrabajoCreate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # Encapsulación: solo puedes crear áreas en TU empresa.
    exigir_empresa(usuario, datos.id_empresa)
    return areatrabajo_service.registrar_areatrabajo(datos=datos, db=db)


# ── Listar áreas de trabajo ───────────────────────────────────────────────────
@router.get(
    "",
    response_model=list[AreaTrabajoResponse],
    summary="Listar áreas de trabajo",
    description="Devuelve todas las áreas de trabajo registradas (con paginación).",
)
def listar_areas(
    id_empresa: int | None = Depends(resolver_empresa_scope),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    nombre: str | None = Query(None, description="Buscar por nombre (parcial, insensible a mayúsculas)."),
    db: Session = Depends(get_db),
):
    return areatrabajo_service.listar_areas(db=db, skip=skip, limit=limit, id_empresa=id_empresa, nombre=nombre)


# ── Obtener área de trabajo por id ────────────────────────────────────────────
@router.get(
    "/{id_area}",
    response_model=AreaTrabajoResponse,
    summary="Obtener área de trabajo",
    description="Devuelve un área de trabajo por su id.",
)
def obtener_area(
    id_area: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    exigir_empresa(usuario, areatrabajo_service.empresa_de_area(id_area, db))
    return areatrabajo_service.obtener_area(id_area=id_area, db=db)


# ── Actualizar área de trabajo ────────────────────────────────────────────────
@router.put(
    "/{id_area}",
    response_model=AreaTrabajoResponse,
    summary="Actualizar área de trabajo",
    description="Actualiza los campos enviados de un área. Para cambiar la zona, envía 'coordenadas'.",
)
def actualizar_area(
    id_area: int,
    datos: AreaTrabajoUpdate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # El área debe ser de tu empresa...
    exigir_empresa(usuario, areatrabajo_service.empresa_de_area(id_area, db))
    # ...y si la mueves de empresa, la empresa destino también debe ser la tuya.
    if datos.id_empresa is not None:
        exigir_empresa(usuario, datos.id_empresa)
    return areatrabajo_service.actualizar_area(id_area=id_area, datos=datos, db=db)


# ── Eliminar área de trabajo (baja lógica) ────────────────────────────────────
@router.delete(
    "/{id_area}",
    response_model=AreaTrabajoResponse,
    summary="Desactivar área de trabajo",
    description="Baja lógica: marca el área como 'inactivo' (no borra la fila).",
)
def eliminar_area(
    id_area: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    exigir_empresa(usuario, areatrabajo_service.empresa_de_area(id_area, db))
    return areatrabajo_service.eliminar_area(id_area=id_area, db=db)
