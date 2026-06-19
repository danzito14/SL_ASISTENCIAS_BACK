import logging

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from src.models.Empresa_Model import Empresa
from src.schemas.Empresa_Schema import EmpresaCreate, EmpresaUpdate
from src.schemas._geo import poligono_desde_coords

logger = logging.getLogger(__name__)


class EmpresaService:

    def registrar_empresa(self, datos: EmpresaCreate, db: Session) -> Empresa:
        """
        Registra una empresa. La ubicación llega como lista de coordenadas
        [longitud, latitud] y se guarda como geography(POLYGON,4326).

        Args:
            datos: Datos de la empresa (nombre_empresa, zona_horaria, estado, coordenadas)
            db:    Sesión de BD
        Returns:
            La empresa creada.
        """
        empresa = Empresa(
            nombre_empresa=datos.nombre_empresa,
            ubicacion=poligono_desde_coords(datos.coordenadas),
            zona_horaria=datos.zona_horaria,
            estado=datos.estado,
        )
        db.add(empresa)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            logger.error("Error de integridad al registrar empresa: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo registrar la empresa: {exc.orig}",
            )
        db.refresh(empresa)

        return empresa

    def listar_empresas(
        self,
        db: Session,
        skip: int = 0,
        limit: int = 100,
        id_empresa: int | None = None,
        nombre: str | None = None,
    ) -> list[Empresa]:
        """
        Devuelve las empresas registradas, ordenadas por id.

        Encapsulación: si id_empresa is not None, un usuario normal solo ve SU
        empresa. None = super-admin = todas las empresas.

        Args:
            db:         Sesión de BD
            skip:       Cuántos registros saltar (paginación)
            limit:      Máximo de registros a devolver
            id_empresa: Empresa efectiva a la que se acota el listado (None = todas)
        Returns:
            Lista de empresas.
        """
        query = db.query(Empresa)
        if id_empresa is not None:
            query = query.filter(Empresa.id_empresa == id_empresa)
        if nombre is not None:
            query = query.filter(Empresa.nombre_empresa.ilike(f"%{nombre}%"))
        return (
            query
            .order_by(Empresa.id_empresa)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def obtener_empresa(self, id_empresa: int, db: Session) -> Empresa:
        """
        Devuelve una empresa por su id o lanza 404 si no existe.

        Args:
            id_empresa: Id de la empresa
            db:         Sesión de BD
        Returns:
            La empresa encontrada.
        """
        empresa = db.query(Empresa).filter(Empresa.id_empresa == id_empresa).first()
        if not empresa:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Empresa {id_empresa} no encontrada.",
            )
        return empresa

    def actualizar_empresa(self, id_empresa: int, datos: EmpresaUpdate, db: Session) -> Empresa:
        """
        Actualiza parcialmente una empresa (solo los campos enviados). Si llegan
        coordenadas, reemplaza la zona (geography POLYGON,4326).
        """
        empresa = self.obtener_empresa(id_empresa, db)

        cambios = datos.model_dump(exclude_unset=True)
        coords = cambios.pop("coordenadas", None)
        if coords is not None:
            empresa.ubicacion = poligono_desde_coords(coords)
        for campo, valor in cambios.items():
            setattr(empresa, campo, valor)

        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            logger.error("Error de integridad al actualizar empresa: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo actualizar la empresa: {exc.orig}",
            )
        db.refresh(empresa)
        return empresa

    def eliminar_empresa(self, id_empresa: int, db: Session) -> Empresa:
        """
        Baja lógica (soft delete): marca la empresa como 'inactivo'. No borra la
        fila para conservar las áreas/puertas y el historial asociado.
        """
        empresa = self.obtener_empresa(id_empresa, db)
        empresa.estado = "inactivo"
        db.commit()
        db.refresh(empresa)
        return empresa


empresa_service = EmpresaService()
