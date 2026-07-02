import logging

from sqlalchemy import cast, String
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from src.models.Rol_Usuario_Model import Rol
from src.schemas.Rol_Usuario_Schema import RolCreate, RolUpdate

logger = logging.getLogger(__name__)

PG_UNIQUE_VIOLATION = "23505"


class RolService:

    def registrar_rol(self, datos: RolCreate, db: Session) -> Rol:
        rol = Rol(
            nombre_rol=datos.nombre_rol,
            descripcion=datos.descripcion,
            permisos=datos.permisos.model_dump(),
            estado=datos.estado,
        )
        db.add(rol)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            pgcode = getattr(getattr(exc, "orig", None), "pgcode", None)
            if pgcode == PG_UNIQUE_VIOLATION:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Ya existe un rol con el nombre '{datos.nombre_rol}'.",
                )
            logger.error("Error de integridad al registrar rol: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo registrar el rol: {exc.orig}",
            )
        db.refresh(rol)
        return rol

    def listar_roles(self, db: Session, skip: int = 0, limit: int = 100) -> list[Rol]:
        return db.query(Rol).order_by(Rol.id_rol).offset(skip).limit(limit).all()

    def buscar_roles_por_id(
        self, db: Session, id_rol: str, skip: int = 0, limit: int = 100
    ) -> list[Rol]:
        """
        Busca roles por su id con coincidencia PARCIAL (el id se compara como texto)
        y paginación. Devuelve una LISTA (mismo formato que el listado del front).
        """
        return (
            db.query(Rol)
            .filter(cast(Rol.id_rol, String).ilike(f"%{id_rol}%"))
            .order_by(Rol.id_rol)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def obtener_rol(self, id_rol: int, db: Session) -> Rol:
        rol = db.query(Rol).filter(Rol.id_rol == id_rol).first()
        if not rol:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Rol {id_rol} no encontrado.",
            )
        return rol

    def actualizar_rol(self, id_rol: int, datos: RolUpdate, db: Session) -> Rol:
        rol = self.obtener_rol(id_rol, db)
        for campo, valor in datos.model_dump(exclude_unset=True).items():
            setattr(rol, campo, valor)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            pgcode = getattr(getattr(exc, "orig", None), "pgcode", None)
            if pgcode == PG_UNIQUE_VIOLATION:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Ya existe un rol con el nombre '{datos.nombre_rol}'.",
                )
            logger.error("Error de integridad al actualizar rol: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo actualizar el rol: {exc.orig}",
            )
        db.refresh(rol)
        return rol

    def eliminar_rol(self, id_rol: int, db: Session) -> Rol:
        rol = self.obtener_rol(id_rol, db)
        rol.estado = "inactivo"
        db.commit()
        db.refresh(rol)
        return rol


rol_service = RolService()
