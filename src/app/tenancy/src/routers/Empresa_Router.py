# app/api/v1/endpoints/empresa.py
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from src.core.auth import es_admin, exigir_empresa, resolver_empresa_scope, usuario_actual
from src.core.pgdb import get_db
from src.core.auth import Principal as Usuario
from src.schemas.Empresa_Schema import EmpresaCreate, EmpresaResponse, EmpresaUpdate
from src.services.Empresa_Service import empresa_service

router = APIRouter(prefix="/empresas", tags=["Empresas"])


# ── Registrar empresa ─────────────────────────────────────────────────────────
@router.post(
    "",
    response_model=EmpresaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar empresa",
    description="Crea una empresa. La ubicación es una zona (polígono) definida por coordenadas [longitud, latitud].",
)
def registrar_empresa(
    datos: EmpresaCreate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # Gestión global: solo el super-admin puede crear empresas.
    if not es_admin(usuario):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el super-admin puede gestionar empresas.",
        )
    return empresa_service.registrar_empresa(datos=datos, db=db)


# ── Listar empresas ───────────────────────────────────────────────────────────
@router.get(
    "",
    response_model=list[EmpresaResponse],
    summary="Listar empresas",
    description="Devuelve todas las empresas registradas (con paginación).",
)
def listar_empresas(
    id_empresa: int | None = Depends(resolver_empresa_scope),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    nombre: str | None = Query(None, description="Buscar por nombre (parcial, insensible a mayúsculas)."),
    db: Session = Depends(get_db),
):
    return empresa_service.listar_empresas(db=db, skip=skip, limit=limit, id_empresa=id_empresa, nombre=nombre)


# ── Buscar empresas por id ────────────────────────────────────────────────────
# NOTA: el parámetro de búsqueda se llama "id" (no "id_empresa") porque
# resolver_empresa_scope ya consume el query param "id_empresa" (para que el
# super-admin elija empresa). Va ANTES de "/{id_empresa}".
@router.get(
    "/buscar",
    response_model=list[EmpresaResponse],
    summary="Buscar empresas por id",
    description=(
        "Búsqueda PARCIAL (contiene) por id de empresa, con paginación. "
        "Respeta el aislamiento por empresa."
    ),
)
def buscar_empresas(
    id: str = Query(..., min_length=1, description="Id de empresa (o parte) a buscar."),
    id_empresa: int | None = Depends(resolver_empresa_scope),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return empresa_service.buscar_empresas_por_id(
        db=db, id_buscar=id, skip=skip, limit=limit, id_empresa_scope=id_empresa
    )


# ── Obtener empresa por id ────────────────────────────────────────────────────
@router.get(
    "/{id_empresa}",
    response_model=EmpresaResponse,
    summary="Obtener empresa",
    description="Devuelve una empresa por su id.",
)
def obtener_empresa(
    id_empresa: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # Encapsulación: la empresa del path ES la empresa objetivo.
    exigir_empresa(usuario, id_empresa)
    return empresa_service.obtener_empresa(id_empresa=id_empresa, db=db)


# ── Actualizar empresa ────────────────────────────────────────────────────────
@router.put(
    "/{id_empresa}",
    response_model=EmpresaResponse,
    summary="Actualizar empresa",
    description="Actualiza los campos enviados de una empresa. Para cambiar la zona, envía 'coordenadas'.",
)
def actualizar_empresa(
    id_empresa: int,
    datos: EmpresaUpdate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # Encapsulación: la empresa del path ES la empresa objetivo.
    exigir_empresa(usuario, id_empresa)
    return empresa_service.actualizar_empresa(id_empresa=id_empresa, datos=datos, db=db)


# ── Eliminar empresa (baja lógica) ────────────────────────────────────────────
@router.delete(
    "/{id_empresa}",
    response_model=EmpresaResponse,
    summary="Desactivar empresa",
    description="Baja lógica: marca la empresa como 'inactivo' (no borra la fila).",
)
def eliminar_empresa(
    id_empresa: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # Gestión global: solo el super-admin puede eliminar empresas.
    if not es_admin(usuario):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el super-admin puede gestionar empresas.",
        )
    return empresa_service.eliminar_empresa(id_empresa=id_empresa, db=db)
