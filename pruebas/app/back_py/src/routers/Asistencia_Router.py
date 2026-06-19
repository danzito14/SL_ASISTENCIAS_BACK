# app/api/v1/endpoints/asistencia.py
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.core.auth import exigir_empresa, resolver_empresa_scope, usuario_actual
from src.core.pgdb import get_db
from src.models.Rol_Usuario_Model import Usuario
from src.schemas.Asistencia_HistorialAuditoria import AsistenciaResponse
from src.services.Asistencia_Service import asistencia_service

router = APIRouter(prefix="/asistencias", tags=["Asistencias"])


# ── Listar asistencias ────────────────────────────────────────────────────────
@router.get(
    "",
    response_model=list[AsistenciaResponse],
    summary="Listar asistencias",
    description="Devuelve los registros de asistencia (más recientes primero, con paginación). Por defecto, los últimos 7 días.",
)
def listar_asistencias(
    id_empresa: int | None = Depends(resolver_empresa_scope),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    id_trabajador: int | None = Query(None, description="Filtrar por trabajador"),
    nombre: str | None = Query(None, description="Buscar por nombre/apellido del trabajador (parcial, insensible a mayúsculas)."),
    fecha_inicio: date | None = Query(None, description="Inicio del rango (YYYY-MM-DD). Por defecto, hace 7 días."),
    fecha_fin: date | None = Query(None, description="Fin del rango (YYYY-MM-DD), inclusivo. Por defecto, hoy."),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    # Si filtras por trabajador, debe ser de tu empresa.
    if id_trabajador is not None:
        exigir_empresa(usuario, asistencia_service.empresa_de_trabajador(id_trabajador, db))
    return asistencia_service.listar_asistencias(
        db=db, skip=skip, limit=limit, id_trabajador=id_trabajador, id_empresa=id_empresa,
        nombre=nombre, fecha_inicio=fecha_inicio, fecha_fin=fecha_fin,
    )


# ── Obtener asistencia por id ─────────────────────────────────────────────────
@router.get(
    "/{id_asistencia}",
    response_model=AsistenciaResponse,
    summary="Obtener asistencia",
    description="Devuelve un registro de asistencia por su id.",
)
def obtener_asistencia(
    id_asistencia: int,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(usuario_actual),
):
    exigir_empresa(usuario, asistencia_service.empresa_de_asistencia(id_asistencia, db))
    return asistencia_service.obtener_asistencia(id_asistencia=id_asistencia, db=db)
