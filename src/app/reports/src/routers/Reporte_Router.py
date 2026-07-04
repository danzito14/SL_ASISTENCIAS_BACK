# app/routers/reporte.py
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.core.auth import es_admin, resolver_empresa_scope, usuario_actual
from src.core.pgdb import get_db
from src.schemas.Incidencia_Schema import TipoIncidencia
from src.services.Reporte_Service import reporte_service

router = APIRouter(prefix="/reportes", tags=["Reportes"])

Formato = Literal["xlsx", "csv"]


# ── Dashboard (JSON con los números del día) ──────────────────────────────────
@router.get(
    "/dashboard",
    summary="Panel del día (presentes/total, por tipo de área, retardos, intentos…)",
    description="Números en vivo para el panel: presentes/total del día (global y por "
                "oficina/empaque/campo), ausentes, retardos, intentos, incidencias "
                "pendientes y padrón con/sin rostro. Acotado a tu empresa.",
)
def dashboard(
    request: Request,
    fecha: date | None = Query(None, description="Día a consultar (YYYY-MM-DD). Vacío = hoy."),
    id_empresa: int | None = Query(
        None,
        description="Solo admin: empresa a ver. Vacío = empresa 1 (default); 0 = TODAS. "
                    "Un usuario normal siempre ve su propia empresa (este parámetro se ignora)."),
    db: Session = Depends(get_db),
):
    principal = usuario_actual(request)
    if es_admin(principal):
        # Admin: sin valor → empresa 1 (default); 0 → todas; otro → esa empresa.
        emp = 1 if id_empresa is None else (None if id_empresa == 0 else id_empresa)
    else:
        emp = principal.empresa      # usuario normal: siempre su empresa
    return reporte_service.dashboard(db, emp, fecha)

# Respuestas binarias (archivo descargable) — se documentan así en Swagger.
_FILE_RESPONSES = {
    200: {
        "content": {
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {},
            "text/csv": {},
        },
        "description": "Archivo descargable (XLSX o CSV).",
    }
}


# ── Reporte de asistencias ────────────────────────────────────────────────────
@router.get(
    "/asistencias",
    summary="Reporte de asistencias (XLSX/CSV)",
    description="Descarga las asistencias de tu empresa en el rango de fechas dado.",
    responses=_FILE_RESPONSES,
)
def reporte_asistencias(
    formato: Formato = Query("xlsx"),
    fecha_inicio: date | None = Query(None, description="YYYY-MM-DD"),
    fecha_fin: date | None = Query(None, description="YYYY-MM-DD (inclusivo)"),
    id_trabajador: int | None = Query(None, description="Asistencias de un empleado específico."),
    id_empresa: int | None = Depends(resolver_empresa_scope),
    db: Session = Depends(get_db),
):
    return reporte_service.asistencias(
        db, id_empresa, fecha_inicio, fecha_fin, formato, id_trabajador=id_trabajador
    )


# ── Reporte de incidencias ────────────────────────────────────────────────────
@router.get(
    "/incidencias",
    summary="Reporte de incidencias (XLSX/CSV)",
    description="Descarga las incidencias de tu empresa en el rango de fechas dado.",
    responses=_FILE_RESPONSES,
)
def reporte_incidencias(
    formato: Formato = Query("xlsx"),
    tipo: TipoIncidencia | None = Query(None, description="Filtrar por tipo (retardo, falta, fuera_de_area, ...)."),
    fecha_inicio: date | None = Query(None, description="YYYY-MM-DD"),
    fecha_fin: date | None = Query(None, description="YYYY-MM-DD (inclusivo)"),
    id_trabajador: int | None = Query(None, description="Incidencias de un empleado específico."),
    id_empresa: int | None = Depends(resolver_empresa_scope),
    db: Session = Depends(get_db),
):
    return reporte_service.incidencias(
        db, id_empresa, fecha_inicio, fecha_fin, formato, tipo=tipo, id_trabajador=id_trabajador
    )


# ── Atajos: retardos / faltas / fuera de área (incidencias por tipo) ──────────
@router.get(
    "/retardos",
    summary="Reporte de retardos (XLSX/CSV)",
    description="Retardo CALCULADO: entradas cuya hora local supera la hora de entrada "
                "del área del trabajador (más una tolerancia opcional), con los minutos "
                "de retraso. Solo áreas con hora de entrada definida.",
    responses=_FILE_RESPONSES,
)
def reporte_retardos(
    formato: Formato = Query("xlsx"),
    fecha_inicio: date | None = Query(None, description="YYYY-MM-DD"),
    fecha_fin: date | None = Query(None, description="YYYY-MM-DD (inclusivo)"),
    id_trabajador: int | None = Query(None, description="De un empleado específico."),
    tolerancia_min: int = Query(0, ge=0, description="Minutos de tolerancia antes de contar como retardo."),
    id_empresa: int | None = Depends(resolver_empresa_scope),
    db: Session = Depends(get_db),
):
    return reporte_service.retardos(
        db, id_empresa, fecha_inicio, fecha_fin, formato,
        id_trabajador=id_trabajador, tolerancia_min=tolerancia_min,
    )


@router.get(
    "/faltas",
    summary="Reporte de faltas (XLSX/CSV)",
    description="Incidencias de tipo 'falta' de tu empresa.",
    responses=_FILE_RESPONSES,
)
def reporte_faltas(
    formato: Formato = Query("xlsx"),
    fecha_inicio: date | None = Query(None, description="YYYY-MM-DD"),
    fecha_fin: date | None = Query(None, description="YYYY-MM-DD (inclusivo)"),
    id_trabajador: int | None = Query(None, description="De un empleado específico."),
    id_empresa: int | None = Depends(resolver_empresa_scope),
    db: Session = Depends(get_db),
):
    return reporte_service.incidencias(
        db, id_empresa, fecha_inicio, fecha_fin, formato, tipo="falta", id_trabajador=id_trabajador
    )


@router.get(
    "/fuera-de-area",
    summary="Reporte de escaneos fuera de área (XLSX/CSV)",
    description="Incidencias de tipo 'fuera_de_area' de tu empresa.",
    responses=_FILE_RESPONSES,
)
def reporte_fuera_de_area(
    formato: Formato = Query("xlsx"),
    fecha_inicio: date | None = Query(None, description="YYYY-MM-DD"),
    fecha_fin: date | None = Query(None, description="YYYY-MM-DD (inclusivo)"),
    id_trabajador: int | None = Query(None, description="De un empleado específico."),
    id_empresa: int | None = Depends(resolver_empresa_scope),
    db: Session = Depends(get_db),
):
    return reporte_service.incidencias(
        db, id_empresa, fecha_inicio, fecha_fin, formato, tipo="fuera_de_area", id_trabajador=id_trabajador
    )


# ── Reporte de intentos de acceso ─────────────────────────────────────────────
@router.get(
    "/intentos",
    summary="Reporte de intentos de acceso (XLSX/CSV)",
    description="Descarga los intentos rechazados (spoofing, desconocido, otra empresa).",
    responses=_FILE_RESPONSES,
)
def reporte_intentos(
    formato: Formato = Query("xlsx"),
    fecha_inicio: date | None = Query(None, description="YYYY-MM-DD"),
    fecha_fin: date | None = Query(None, description="YYYY-MM-DD (inclusivo)"),
    id_empresa: int | None = Depends(resolver_empresa_scope),
    db: Session = Depends(get_db),
):
    return reporte_service.intentos(db, id_empresa, fecha_inicio, fecha_fin, formato)


# ── Reporte de trabajadores ───────────────────────────────────────────────────
@router.get(
    "/trabajadores",
    summary="Reporte de trabajadores (XLSX/CSV)",
    description="Descarga el padrón de trabajadores de tu empresa.",
    responses=_FILE_RESPONSES,
)
def reporte_trabajadores(
    formato: Formato = Query("xlsx"),
    id_empresa: int | None = Depends(resolver_empresa_scope),
    db: Session = Depends(get_db),
):
    return reporte_service.trabajadores(db, id_empresa, formato)
