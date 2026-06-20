import logging
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload
from fastapi import HTTPException, status

from src.models.Asistencia_HistorialAuditoria_Model import Asistencia
from src.models.AreaTrabajo_Trabajador_Model import AreaTrabajo, Trabajador

logger = logging.getLogger(__name__)

# Ventana por defecto cuando no se indica un rango de fechas.
DIAS_RANGO_POR_DEFECTO = 7


def resolver_rango_fechas(
    fecha_inicio: date | None,
    fecha_fin: date | None,
    dias_por_defecto: int = DIAS_RANGO_POR_DEFECTO,
) -> tuple[date, date]:
    """
    Resuelve el rango de fechas a consultar:
      - fecha_fin sin valor → hoy.
      - fecha_inicio sin valor → fecha_fin menos `dias_por_defecto` días.
    Así, sin parámetros, devuelve los últimos `dias_por_defecto` días.
    Lanza 400 si fecha_inicio queda después de fecha_fin.
    """
    if fecha_fin is None:
        fecha_fin = date.today()
    if fecha_inicio is None:
        fecha_inicio = fecha_fin - timedelta(days=dias_por_defecto)
    if fecha_inicio > fecha_fin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="fecha_inicio no puede ser posterior a fecha_fin.",
        )
    return fecha_inicio, fecha_fin


class AsistenciaService:

    def _eager(self, query):
        """Carga por adelantado (JOIN) las relaciones necesarias para resolver los
        nombres, evitando N+1. Todas son many-to-one, así que no multiplican filas."""
        return query.options(
            joinedload(Asistencia.trabajador).joinedload(Trabajador.area).joinedload(AreaTrabajo.empresa),
            joinedload(Asistencia.puerta),
            joinedload(Asistencia.dispositivo),
        )

    def _enriquecer(self, a: Asistencia) -> Asistencia:
        """Rellena los nombres resueltos (transitorios) que lee AsistenciaResponse."""
        trab = a.trabajador
        area = trab.area if trab else None
        a.trabajador_nombre  = f"{trab.nombre} {trab.apellido}" if trab else None
        a.puerta_nombre      = a.puerta.nombre_puerta if a.puerta else None
        a.dispositivo_nombre = a.dispositivo.nombre_dispositivo if a.dispositivo else None
        a.area_nombre        = area.nombre_area if area else None
        a.empresa_nombre     = area.empresa.nombre_empresa if (area and area.empresa) else None
        return a

    def listar_asistencias(
        self,
        db: Session,
        skip: int = 0,
        limit: int = 100,
        id_trabajador: int | None = None,
        id_empresa: int | None = None,
        nombre: str | None = None,
        fecha_inicio: date | None = None,
        fecha_fin: date | None = None,
    ) -> list[Asistencia]:
        """
        Devuelve los registros de asistencia, ordenados de más reciente a más
        antiguo. Opcionalmente se pueden filtrar por trabajador y/o empresa
        (vía Trabajador->Área).

        Args:
            db:            Sesión de BD
            skip:          Cuántos registros saltar (paginación)
            limit:         Máximo de registros a devolver
            id_trabajador: Si se indica, filtra por ese trabajador
            id_empresa:    Si se indica, solo asistencias de esa empresa
            nombre:        Si se indica, filtra por nombre/apellido del trabajador
                           (parcial, insensible a mayúsculas)
            fecha_inicio:  Inicio del rango (sobre fecha_hora). Por defecto, hace 7 días.
            fecha_fin:     Fin del rango, inclusivo (todo el día). Por defecto, hoy.
        Returns:
            Lista de asistencias.
        """
        fecha_inicio, fecha_fin = resolver_rango_fechas(fecha_inicio, fecha_fin)

        query = self._eager(db.query(Asistencia))
        # fecha_hora es timestamp: el límite superior es el día siguiente
        # (exclusivo) para incluir todas las horas de fecha_fin.
        query = query.filter(
            Asistencia.fecha_hora >= fecha_inicio,
            Asistencia.fecha_hora < fecha_fin + timedelta(days=1),
        )
        # Empresa: filtro directo por id_empresa denormalizado (sin joins).
        if id_empresa is not None:
            query = query.filter(Asistencia.id_empresa == id_empresa)
        # Nombre: requiere unir Trabajador para buscar por nombre/apellido.
        if nombre is not None:
            query = query.join(
                Trabajador, Trabajador.id_trabajador == Asistencia.id_trabajador
            ).filter(
                or_(
                    Trabajador.nombre.ilike(f"%{nombre}%"),
                    Trabajador.apellido.ilike(f"%{nombre}%"),
                )
            )
        if id_trabajador is not None:
            query = query.filter(Asistencia.id_trabajador == id_trabajador)
        asistencias = (
            query.order_by(Asistencia.fecha_hora.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )
        return [self._enriquecer(a) for a in asistencias]

    def obtener_asistencia(self, id_asistencia: UUID, db: Session) -> Asistencia:
        """
        Devuelve un registro de asistencia por su id o lanza 404 si no existe.

        Args:
            id_asistencia: Id de la asistencia
            db:            Sesión de BD
        Returns:
            La asistencia encontrada.
        """
        asistencia = self._eager(db.query(Asistencia)).filter(
            Asistencia.id_asistencia == id_asistencia
        ).first()
        if not asistencia:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Asistencia {id_asistencia} no encontrada.",
            )
        return self._enriquecer(asistencia)

    # ── Derivación de empresa (para la encapsulación por empresa) ──────────────
    def empresa_de_trabajador(self, id_trabajador: int, db: Session) -> int | None:
        """Empresa de un trabajador (id_empresa denormalizado), o None si no existe."""
        fila = (
            db.query(Trabajador.id_empresa)
            .filter(Trabajador.id_trabajador == id_trabajador)
            .first()
        )
        return fila[0] if fila else None

    def empresa_de_asistencia(self, id_asistencia: UUID, db: Session) -> int | None:
        """Empresa de una asistencia (id_empresa denormalizado), o None si no existe."""
        fila = (
            db.query(Asistencia.id_empresa)
            .filter(Asistencia.id_asistencia == id_asistencia)
            .first()
        )
        return fila[0] if fila else None


asistencia_service = AsistenciaService()
