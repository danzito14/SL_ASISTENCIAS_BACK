# app/routers/incidencia.py
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from src.core.auth import exigir_empresa, resolver_empresa_scope, usuario_actual
from src.core.pgdb import get_db
from src.models.Rol_Usuario_Model import Usuario
from src.schemas.Incidencia_Schema import (
    EstadoIncidencia,
    EventoResponse,
    IncidenciaCreate,
    IncidenciaResponse,
    IncidenciaUpdate,
    TipoIncidencia,
)
from src.services.Incidencia_Service import incidencia_service

router = APIRouter(prefix="/incidencias", tags=["Incidencias"])


# ── Registrar incidencia ──────────────────────────────────────────────────────
@router.post(
    "",
    response_model=IncidenciaResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar incidencia",
    description="Crea una incidencia para un trabajador (falta, retardo, fuera de área, etc.).",
)
def registrar_incidencia(
    datos: IncidenciaCreate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # Encapsulación: solo puedes crear incidencias para trabajadores de TU empresa.
    exigir_empresa(usuario, incidencia_service.empresa_de_trabajador(datos.id_trabajador, db))
    return incidencia_service.registrar_incidencia(datos=datos, db=db)


# ── Listar incidencias ────────────────────────────────────────────────────────
@router.get(
    "",
    response_model=list[IncidenciaResponse],
    summary="Listar incidencias",
    description="Devuelve las incidencias registradas (con paginación y filtros opcionales). Por defecto, los últimos 7 días.",
)
def listar_incidencias(
    id_empresa: int | None = Depends(resolver_empresa_scope),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    id_trabajador: int | None = Query(None, description="Filtrar por trabajador."),
    tipo_incidencia: TipoIncidencia | None = Query(None, description="Filtrar por tipo."),
    estado: EstadoIncidencia | None = Query(None, description="Filtrar por estado."),
    nombre: str | None = Query(None, description="Buscar por nombre/apellido del trabajador (parcial, insensible a mayúsculas)."),
    fecha_inicio: date | None = Query(None, description="Inicio del rango (YYYY-MM-DD). Por defecto, hace 7 días."),
    fecha_fin: date | None = Query(None, description="Fin del rango (YYYY-MM-DD), inclusivo. Por defecto, hoy."),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # Si se filtra por trabajador, debe pertenecer a la empresa del usuario.
    if id_trabajador is not None:
        exigir_empresa(usuario, incidencia_service.empresa_de_trabajador(id_trabajador, db))
    return incidencia_service.listar_incidencias(
        db=db,
        skip=skip,
        limit=limit,
        id_trabajador=id_trabajador,
        tipo_incidencia=tipo_incidencia,
        estado=estado,
        id_empresa=id_empresa,
        nombre=nombre,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
    )


# ── Vista combinada: incidencias + intentos de acceso ─────────────────────────
@router.get(
    "/combinado",
    response_model=list[EventoResponse],
    summary="Incidencias + intentos de acceso (vista unificada)",
    description="Lista combinada de incidencias e intentos de acceso (spoofing, "
                "desconocido, otra empresa) en un solo feed ordenado por fecha. "
                "Cada fila indica su 'origen' y la 'foto_url' del endpoint correcto.",
)
def listar_combinado(
    id_empresa: int | None = Depends(resolver_empresa_scope),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    tipo: str | None = Query(None, description="Filtrar por tipo (de cualquiera de las dos tablas)."),
    origen: Literal["incidencia", "intento"] | None = Query(None, description="Solo un origen, o ambos si se omite."),
    fecha_inicio: date | None = Query(None, description="Inicio del rango (YYYY-MM-DD)."),
    fecha_fin: date | None = Query(None, description="Fin del rango (YYYY-MM-DD), inclusivo."),
    db: Session = Depends(get_db),
):
    return incidencia_service.listar_combinado(
        db=db, id_empresa=id_empresa, skip=skip, limit=limit,
        tipo=tipo, origen=origen, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
    )


# ── Obtener incidencia por id ─────────────────────────────────────────────────
@router.get(
    "/{id_incidencia}",
    response_model=IncidenciaResponse,
    summary="Obtener incidencia",
    description="Devuelve una incidencia por su id.",
)
def obtener_incidencia(
    id_incidencia: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    exigir_empresa(usuario, incidencia_service.empresa_de_incidencia(id_incidencia, db))
    return incidencia_service.obtener_incidencia(id_incidencia=id_incidencia, db=db)


# ── Foto de la incidencia (protegida) ─────────────────────────────────────────
@router.get(
    "/{id_incidencia}/foto",
    summary="Foto de la incidencia",
    description="Devuelve la imagen del rostro asociada a la incidencia (JPEG). "
                "Requiere permiso de lectura y que la incidencia sea de tu empresa.",
    responses={
        200: {"content": {"image/jpeg": {}}, "description": "Imagen JPEG."},
        404: {"description": "La incidencia no existe o no tiene foto."},
    },
)
def foto_incidencia(
    id_incidencia: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # Encapsulación: la incidencia debe ser de tu empresa (403 si no).
    exigir_empresa(usuario, incidencia_service.empresa_de_incidencia(id_incidencia, db))

    ruta = incidencia_service.ruta_archivo_foto(id_incidencia, db)
    if ruta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Esta incidencia no tiene foto.",
        )
    return FileResponse(ruta, media_type="image/jpeg")


# ── Actualizar incidencia ─────────────────────────────────────────────────────
@router.put(
    "/{id_incidencia}",
    response_model=IncidenciaResponse,
    summary="Actualizar incidencia",
    description="Actualiza los campos enviados de una incidencia (estado, descripción, etc.).",
)
def actualizar_incidencia(
    id_incidencia: int,
    datos: IncidenciaUpdate,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # La incidencia debe ser de tu empresa...
    exigir_empresa(usuario, incidencia_service.empresa_de_incidencia(id_incidencia, db))
    # ...y si la reasignas a otro trabajador, ese también debe ser de tu empresa.
    if datos.id_trabajador is not None:
        exigir_empresa(usuario, incidencia_service.empresa_de_trabajador(datos.id_trabajador, db))
    return incidencia_service.actualizar_incidencia(
        id_incidencia=id_incidencia, datos=datos, db=db
    )
