import logging

from sqlalchemy import cast, String
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from src.models.AreaTrabajo_Trabajador_Model import AreaTrabajo
from src.schemas.AreaTrabajo_Trabajador import AreaTrabajoCreate, AreaTrabajoUpdate
from src.schemas._geo import poligono_desde_coords

logger = logging.getLogger(__name__)

# Código SQLSTATE de Postgres para violación de UNIQUE
PG_UNIQUE_VIOLATION = "23505"

class AreaTrabajoService:

    def registrar_areatrabajo(self, datos: AreaTrabajoCreate, db: Session) -> AreaTrabajo:
        """
            Registra un area de trabajo para poder asignarle empleados

            Args:
                datos: Datos del area de trabajo (nombre_area, descripcion, ubicacion, estado)
                db: Sesión de BD
            Returns:
                Area de trabajo creada
        """
        areatrabajo = AreaTrabajo(
            nombre_area = datos.nombre_area,
            descripcion = datos.descripcion,
            ubicacion = poligono_desde_coords(datos.coordenadas),
            id_empresa = datos.id_empresa,
            hora_entrada = datos.hora_entrada,
            estado = datos.estado,
        )
        db.add(areatrabajo)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()

            # Solo es 409 si fue una violación de UNIQUE (nombre_area repetido).
            pgcode = getattr(getattr(exc, "orig", None), "pgcode", None)
            if pgcode == PG_UNIQUE_VIOLATION:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Ya existe un área de trabajo con el nombre '{datos.nombre_area}'.",
                )

            # Cualquier otra violación de integridad (FK, NOT NULL, etc.) es un error real.
            logger.error("Error de integridad al registrar área de trabajo: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo registrar el área de trabajo: {exc.orig}",
            )
        db.refresh(areatrabajo)

        return areatrabajo

    def empresa_de_area(self, id_area: int, db: Session) -> int | None:
        """Devuelve el id_empresa del área indicada, o None si no existe."""
        fila = (
            db.query(AreaTrabajo.id_empresa)
            .filter(AreaTrabajo.id_area == id_area)
            .first()
        )
        return fila[0] if fila else None

    def listar_areas(
        self, db: Session, skip: int = 0, limit: int = 100, id_empresa: int | None = None,
        nombre: str | None = None,
    ) -> list[AreaTrabajo]:
        """
        Devuelve las áreas de trabajo registradas, ordenadas por id.

        Args:
            db:         Sesión de BD
            skip:       Cuántos registros saltar (paginación)
            limit:      Máximo de registros a devolver
            id_empresa: Si no es None, filtra por esa empresa. None = todas.
        Returns:
            Lista de áreas de trabajo.
        """
        query = db.query(AreaTrabajo)
        if id_empresa is not None:
            query = query.filter(AreaTrabajo.id_empresa == id_empresa)
        if nombre is not None:
            query = query.filter(AreaTrabajo.nombre_area.ilike(f"%{nombre}%"))
        return (
            query
            .order_by(AreaTrabajo.id_area)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def buscar_areas_por_id(
        self,
        db: Session,
        id_area: str,
        skip: int = 0,
        limit: int = 100,
        id_empresa: int | None = None,
    ) -> list[AreaTrabajo]:
        """
        Busca áreas por su id con coincidencia PARCIAL (el id se compara como texto)
        y paginación. Si id_empresa no es None, acota a esa empresa.
        """
        query = db.query(AreaTrabajo).filter(
            cast(AreaTrabajo.id_area, String).ilike(f"%{id_area}%")
        )
        if id_empresa is not None:
            query = query.filter(AreaTrabajo.id_empresa == id_empresa)
        return (
            query
            .order_by(AreaTrabajo.id_area)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def obtener_area(self, id_area: int, db: Session) -> AreaTrabajo:
        """
        Devuelve un área de trabajo por su id o lanza 404 si no existe.

        Args:
            id_area: Id del área de trabajo
            db:      Sesión de BD
        Returns:
            El área de trabajo encontrada.
        """
        area = db.query(AreaTrabajo).filter(AreaTrabajo.id_area == id_area).first()
        if not area:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Área de trabajo {id_area} no encontrada.",
            )
        return area

    def actualizar_area(self, id_area: int, datos: AreaTrabajoUpdate, db: Session) -> AreaTrabajo:
        """
        Actualiza parcialmente un área (solo los campos enviados). Si llegan
        coordenadas, reemplaza la zona (geography POLYGON,4326).
        """
        area = self.obtener_area(id_area, db)

        cambios = datos.model_dump(exclude_unset=True)
        coords = cambios.pop("coordenadas", None)
        if coords is not None:
            area.ubicacion = poligono_desde_coords(coords)
        for campo, valor in cambios.items():
            setattr(area, campo, valor)

        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            pgcode = getattr(getattr(exc, "orig", None), "pgcode", None)
            if pgcode == PG_UNIQUE_VIOLATION:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Ya existe un área de trabajo con el nombre '{cambios.get('nombre_area')}'.",
                )
            logger.error("Error de integridad al actualizar área: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo actualizar el área: {exc.orig}",
            )
        db.refresh(area)
        return area

    def eliminar_area(self, id_area: int, db: Session) -> AreaTrabajo:
        """
        Baja lógica (soft delete): marca el área como 'inactivo'. No borra la fila
        para conservar trabajadores/puertas/dispositivos y el historial asociado.
        """
        area = self.obtener_area(id_area, db)
        area.estado = "inactivo"
        db.commit()
        db.refresh(area)
        return area

areatrabajo_service = AreaTrabajoService()