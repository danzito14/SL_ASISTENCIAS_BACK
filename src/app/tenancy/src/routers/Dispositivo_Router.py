from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from src.core.auth import exigir_empresa, resolver_empresa_scope, usuario_actual
from src.core.pgdb import get_db
from src.core.auth import Principal as Usuario
from src.schemas.Dispositivo_PuertaAcceso_Schema import DispositivoBase, DispositivoCreate, DispositivoResponse, DispositivoUpdate
from src.services.Dispositivos_Service import dispositivo_service

router = APIRouter(prefix="/dispositivos", tags=["Dispositivos de escaner"])

@router.post(
    "",
    response_model=DispositivoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un dispositivo como escaner",
    description="Registra un dispositivo para saber sus datos exactos en el sistema"
)
def registrar_dispositivo(
    datos: DispositivoCreate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # Encapsulación: solo puedes crear dispositivos en un área de TU empresa.
    exigir_empresa(usuario, dispositivo_service.empresa_de_area(datos.id_area, db))
    return dispositivo_service.registrar_dispositivo(datos=datos, db=db)


# ── Listar dispositivos ───────────────────────────────────────────────────────
@router.get(
    "",
    response_model=list[DispositivoResponse],
    summary="Listar dispositivos",
    description="Devuelve todos los dispositivos registrados (con paginación).",
)
def listar_dispositivos(
    id_empresa: int | None = Depends(resolver_empresa_scope),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    nombre: str | None = Query(None, description="Buscar por nombre (parcial, insensible a mayúsculas)."),
    db: Session = Depends(get_db),
):
    return dispositivo_service.listar_dispositivos(
        db=db, skip=skip, limit=limit, id_empresa=id_empresa, nombre=nombre
    )


# ── Obtener dispositivo por id ────────────────────────────────────────────────
@router.get(
    "/{id_dispositivo}",
    response_model=DispositivoResponse,
    summary="Obtener dispositivo",
    description="Devuelve un dispositivo por su id.",
)
def obtener_dispositivo(
    id_dispositivo: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    exigir_empresa(usuario, dispositivo_service.empresa_de_dispositivo(id_dispositivo, db))
    return dispositivo_service.obtener_dispositivo(id_dispositivo=id_dispositivo, db=db)


# ── Actualizar dispositivo ────────────────────────────────────────────────────
@router.put(
    "/{id_dispositivo}",
    response_model=DispositivoResponse,
    summary="Actualizar dispositivo",
    description="Actualiza los campos enviados de un dispositivo. Para cambiar la ubicación, envía 'latitud' y 'longitud'.",
)
def actualizar_dispositivo(
    id_dispositivo: int,
    datos: DispositivoUpdate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # El dispositivo debe ser de tu empresa...
    exigir_empresa(usuario, dispositivo_service.empresa_de_dispositivo(id_dispositivo, db))
    # ...y si lo cambias de área, la nueva área también debe ser de tu empresa.
    if datos.id_area is not None:
        exigir_empresa(usuario, dispositivo_service.empresa_de_area(datos.id_area, db))
    return dispositivo_service.actualizar_dispositivo(id_dispositivo=id_dispositivo, datos=datos, db=db)


# ── Eliminar dispositivo (baja lógica) ────────────────────────────────────────
@router.delete(
    "/{id_dispositivo}",
    response_model=DispositivoResponse,
    summary="Desactivar dispositivo",
    description="Baja lógica: marca el dispositivo como 'inactivo' (no borra la fila).",
)
def eliminar_dispositivo(
    id_dispositivo: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    exigir_empresa(usuario, dispositivo_service.empresa_de_dispositivo(id_dispositivo, db))
    return dispositivo_service.eliminar_dispositivo(id_dispositivo=id_dispositivo, db=db)