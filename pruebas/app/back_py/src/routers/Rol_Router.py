# app/api/v1/endpoints/rol.py
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from src.core.pgdb import get_db
from src.schemas.Rol_Usuario_Schema import RolCreate, RolResponse, RolUpdate
from src.services.Rol_Service import rol_service

router = APIRouter(prefix="/roles", tags=["Roles"])


@router.post(
    "",
    response_model=RolResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar rol",
    description="Crea un rol con sus permisos.",
)
def registrar_rol(datos: RolCreate, db: Session = Depends(get_db)):
    return rol_service.registrar_rol(datos=datos, db=db)


@router.get(
    "",
    response_model=list[RolResponse],
    summary="Listar roles",
    description="Devuelve todos los roles registrados (con paginación).",
)
def listar_roles(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return rol_service.listar_roles(db=db, skip=skip, limit=limit)


@router.get(
    "/{id_rol}",
    response_model=RolResponse,
    summary="Obtener rol",
    description="Devuelve un rol por su id.",
)
def obtener_rol(id_rol: int, db: Session = Depends(get_db)):
    return rol_service.obtener_rol(id_rol=id_rol, db=db)


@router.put(
    "/{id_rol}",
    response_model=RolResponse,
    summary="Actualizar rol",
    description="Actualiza los campos enviados de un rol.",
)
def actualizar_rol(id_rol: int, datos: RolUpdate, db: Session = Depends(get_db)):
    return rol_service.actualizar_rol(id_rol=id_rol, datos=datos, db=db)


@router.delete(
    "/{id_rol}",
    response_model=RolResponse,
    summary="Desactivar rol",
    description="Baja lógica: marca el rol como 'inactivo' (no borra la fila).",
)
def eliminar_rol(id_rol: int, db: Session = Depends(get_db)):
    return rol_service.eliminar_rol(id_rol=id_rol, db=db)
