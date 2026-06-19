# app/services/trabajador_service.py
"""
Servicio para registrar trabajadores (solo datos).

Flujo:
  1. Valida que el área exista y esté activa
  2. Crea el trabajador SIN embedding
  3. Retorna el trabajador creado

El embedding facial se registra por separado mediante el endpoint
POST /trabajadores/{id_trabajador}/embedding.
"""

import logging

from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from src.models.AreaTrabajo_Trabajador_Model import AreaTrabajo, Trabajador
from src.models.Embedding_Model import Embedding
from src.schemas.AreaTrabajo_Trabajador import TrabajadorCreate, TrabajadorUpdate

logger = logging.getLogger(__name__)


class TrabajadorService:

    def registrar_trabajador(
        self,
        datos: TrabajadorCreate,
        db: Session,
    ) -> Trabajador:
        """
        Registra un trabajador con sus datos básicos (sin embedding).

        Args:
            datos: Datos del trabajador (nombre, apellido, id_area, estado)
            db:    Sesión de BD

        Returns:
            El trabajador creado.
        """
        # 1. Validar que el área exista y esté activa
        area = db.query(AreaTrabajo).filter(
            AreaTrabajo.id_area == datos.id_area,
            AreaTrabajo.estado == "activo",
        ).first()

        if not area:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Área {datos.id_area} no encontrada o inactiva.",
            )

        # 2. Crear trabajador (solo datos)
        trabajador = Trabajador(
            nombre=datos.nombre,
            apellido=datos.apellido,
            id_area=datos.id_area,
            estado=datos.estado,
        )
        db.add(trabajador)
        db.commit()
        db.refresh(trabajador)

        return trabajador

    def listar_trabajadores(
        self,
        db: Session,
        skip: int = 0,
        limit: int = 100,
        id_empresa: int | None = None,
        id_area: int | None = None,
        nombre: str | None = None,
    ) -> list[Trabajador]:
        """
        Devuelve los trabajadores registrados, ordenados por id.

        Args:
            db:         Sesión de BD
            skip:       Cuántos registros saltar (paginación)
            limit:      Máximo de registros a devolver
            id_empresa: Si se indica, solo trabajadores de esa empresa (vía su área).
            id_area:    Si se indica, solo trabajadores de esa área.

        Returns:
            Lista de trabajadores.
        """
        query = db.query(Trabajador)
        if id_area is not None:
            query = query.filter(Trabajador.id_area == id_area)
        if id_empresa is not None:
            query = query.join(AreaTrabajo).filter(AreaTrabajo.id_empresa == id_empresa)
        if nombre is not None:
            query = query.filter(
                or_(
                    Trabajador.nombre.ilike(f"%{nombre}%"),
                    Trabajador.apellido.ilike(f"%{nombre}%"),
                )
            )

        trabajadores = (
            query
            .order_by(Trabajador.id_trabajador)
            .offset(skip)
            .limit(limit)
            .all()
        )

        # Marcar qué trabajadores tienen embedding facial (una sola consulta, sin N+1)
        ids = [t.id_trabajador for t in trabajadores]
        ids_con_embedding = {
            id_trab
            for (id_trab,) in db.query(Embedding.id_trabajador)
            .filter(Embedding.id_trabajador.in_(ids))
            .distinct()
            .all()
        } if ids else set()

        for t in trabajadores:
            t.tiene_embedding = t.id_trabajador in ids_con_embedding

        return trabajadores

    def obtener_trabajador(self, id_trabajador: int, db: Session) -> Trabajador:
        """
        Devuelve un trabajador por su id o lanza 404 si no existe.

        Args:
            id_trabajador: Id del trabajador
            db:            Sesión de BD

        Returns:
            El trabajador encontrado.
        """
        trabajador = db.query(Trabajador).filter(
            Trabajador.id_trabajador == id_trabajador
        ).first()
        if not trabajador:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Trabajador {id_trabajador} no encontrado.",
            )

        trabajador.tiene_embedding = (
            db.query(Embedding.id_embedding)
            .filter(Embedding.id_trabajador == id_trabajador)
            .first()
            is not None
        )
        return trabajador

    def actualizar_trabajador(
        self,
        id_trabajador: int,
        datos: TrabajadorUpdate,
        db: Session,
    ) -> Trabajador:
        """
        Actualiza parcialmente un trabajador (solo los campos enviados). Si se
        cambia el área, valida que exista y esté activa.
        """
        trabajador = self.obtener_trabajador(id_trabajador, db)

        cambios = datos.model_dump(exclude_unset=True)

        if "id_area" in cambios and cambios["id_area"] is not None:
            area = db.query(AreaTrabajo).filter(
                AreaTrabajo.id_area == cambios["id_area"],
                AreaTrabajo.estado == "activo",
            ).first()
            if not area:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Área {cambios['id_area']} no encontrada o inactiva.",
                )

        for campo, valor in cambios.items():
            setattr(trabajador, campo, valor)

        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            logger.error("Error de integridad al actualizar trabajador: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo actualizar el trabajador: {exc.orig}",
            )
        db.refresh(trabajador)
        return trabajador

    def eliminar_trabajador(self, id_trabajador: int, db: Session) -> Trabajador:
        """
        Baja lógica (soft delete): marca el trabajador como 'inactivo'. No borra
        la fila para conservar sus asistencias y embedding.
        """
        trabajador = self.obtener_trabajador(id_trabajador, db)
        trabajador.estado = "inactivo"
        db.commit()
        db.refresh(trabajador)
        return trabajador

    # ── Derivación de empresa (para la encapsulación por empresa) ──────────────
    def empresa_de_area(self, id_area: int, db: Session) -> int | None:
        """Empresa a la que pertenece un área, o None si el área no existe."""
        fila = db.query(AreaTrabajo.id_empresa).filter(AreaTrabajo.id_area == id_area).first()
        return fila[0] if fila else None

    def empresa_de_trabajador(self, id_trabajador: int, db: Session) -> int | None:
        """Empresa de un trabajador (vía su área), o None si no existe."""
        fila = (
            db.query(AreaTrabajo.id_empresa)
            .join(Trabajador, Trabajador.id_area == AreaTrabajo.id_area)
            .filter(Trabajador.id_trabajador == id_trabajador)
            .first()
        )
        return fila[0] if fila else None


trabajador_service = TrabajadorService()
