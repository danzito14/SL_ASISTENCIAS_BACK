# app/api/v1/endpoints/puerta_acceso.py
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from src.core.auth import exigir_empresa, resolver_empresa_scope, usuario_actual
from src.core.pgdb import get_db
from src.core.auth import Principal as Usuario
from src.schemas.Dispositivo_PuertaAcceso_Schema import PuertaAccesoCreate, PuertaAccesoResponse, PuertaAccesoUpdate
from src.services.PuertaAcceso_Service import puertaacceso_service

router = APIRouter(prefix="/puertas", tags=["Puertas de acceso"])


# ── Registrar puerta de acceso ────────────────────────────────────────────────
@router.post(
    "",
    response_model=PuertaAccesoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar puerta de acceso",
    description="Crea una puerta de acceso usada al registrar la asistencia.",
)
def registrar_puerta(
    datos: PuertaAccesoCreate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # Encapsulación: solo puedes crear puertas en TU empresa.
    exigir_empresa(usuario, datos.id_empresa)
    return puertaacceso_service.registrar_puerta(datos=datos, db=db)


# ── Listar puertas de acceso ──────────────────────────────────────────────────
@router.get(
    "",
    response_model=list[PuertaAccesoResponse],
    summary="Listar puertas de acceso",
    description="Devuelve todas las puertas de acceso registradas (con paginación).",
)
def listar_puertas(
    id_empresa: int | None = Depends(resolver_empresa_scope),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    nombre: str | None = Query(None, description="Buscar por nombre (parcial, insensible a mayúsculas)."),
    db: Session = Depends(get_db),
):
    return puertaacceso_service.listar_puertas(db=db, skip=skip, limit=limit, id_empresa=id_empresa, nombre=nombre)


# ── Obtener puerta de acceso por id ───────────────────────────────────────────
@router.get(
    "/{id_puerta}",
    response_model=PuertaAccesoResponse,
    summary="Obtener puerta de acceso",
    description="Devuelve una puerta de acceso por su id.",
)
def obtener_puerta(
    id_puerta: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    exigir_empresa(usuario, puertaacceso_service.empresa_de_puerta(id_puerta, db))
    return puertaacceso_service.obtener_puerta(id_puerta=id_puerta, db=db)


# ── Actualizar puerta de acceso ───────────────────────────────────────────────
@router.put(
    "/{id_puerta}",
    response_model=PuertaAccesoResponse,
    summary="Actualizar puerta de acceso",
    description="Actualiza los campos enviados de una puerta. Para cambiar la ubicación, envía 'latitud' y 'longitud'.",
)
def actualizar_puerta(
    id_puerta: int,
    datos: PuertaAccesoUpdate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # La puerta debe ser de tu empresa...
    exigir_empresa(usuario, puertaacceso_service.empresa_de_puerta(id_puerta, db))
    # ...y si la mueves de empresa, la empresa destino también debe ser la tuya.
    if datos.id_empresa is not None:
        exigir_empresa(usuario, datos.id_empresa)
    return puertaacceso_service.actualizar_puerta(id_puerta=id_puerta, datos=datos, db=db)


# ── Eliminar puerta de acceso (baja lógica) ───────────────────────────────────
@router.delete(
    "/{id_puerta}",
    response_model=PuertaAccesoResponse,
    summary="Desactivar puerta de acceso",
    description="Baja lógica: marca la puerta como 'inactivo' (no borra la fila).",
)
def eliminar_puerta(
    id_puerta: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    exigir_empresa(usuario, puertaacceso_service.empresa_de_puerta(id_puerta, db))
    return puertaacceso_service.eliminar_puerta(id_puerta=id_puerta, db=db)
