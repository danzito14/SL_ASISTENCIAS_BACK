import logging

from sqlalchemy import cast, String
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException, status

from src.models.Rol_Usuario_Model import Rol, Usuario
from src.schemas.Rol_Usuario_Schema import UsuarioCreate, UsuarioUpdate, UsuarioLogin
from src.core.security import hash_password, verify_password

logger = logging.getLogger(__name__)

PG_UNIQUE_VIOLATION = "23505"


class UsuarioService:

    def _validar_rol(self, id_rol: int, db: Session) -> None:
        rol = db.query(Rol).filter(Rol.id_rol == id_rol, Rol.estado == "activo").first()
        if not rol:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Rol {id_rol} no encontrado o inactivo.",
            )

    def registrar_usuario(self, datos: UsuarioCreate, db: Session) -> Usuario:
        self._validar_rol(datos.id_rol, db)

        usuario = Usuario(
            nombre_usuario=datos.nombre_usuario,
            contrasena=hash_password(datos.contrasena),
            id_rol=datos.id_rol,
            estado=datos.estado,
            empresa=datos.empresa,
        )
        db.add(usuario)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            pgcode = getattr(getattr(exc, "orig", None), "pgcode", None)
            if pgcode == PG_UNIQUE_VIOLATION:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Ya existe un usuario con el nombre '{datos.nombre_usuario}'.",
                )
            logger.error("Error de integridad al registrar usuario: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo registrar el usuario: {exc.orig}",
            )
        db.refresh(usuario)
        return usuario

    def listar_usuarios(
        self, db: Session, skip: int = 0, limit: int = 100, nombre: str | None = None
    ) -> list[Usuario]:
        query = db.query(Usuario)
        if nombre is not None:
            query = query.filter(Usuario.nombre_usuario.ilike(f"%{nombre}%"))
        return query.order_by(Usuario.id_usuario).offset(skip).limit(limit).all()

    def buscar_usuarios_por_id(
        self, db: Session, id_usuario: str, skip: int = 0, limit: int = 100
    ) -> list[Usuario]:
        """
        Busca usuarios por su id con coincidencia PARCIAL (el id se compara como
        texto, así "1" trae 1, 10, 11, ...) y paginación. Devuelve una LISTA para
        conservar el mismo formato que el listado del front.
        """
        return (
            db.query(Usuario)
            .filter(cast(Usuario.id_usuario, String).ilike(f"%{id_usuario}%"))
            .order_by(Usuario.id_usuario)
            .offset(skip)
            .limit(limit)
            .all()
        )

    def obtener_usuario(self, id_usuario: int, db: Session) -> Usuario:
        usuario = db.query(Usuario).filter(Usuario.id_usuario == id_usuario).first()
        if not usuario:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Usuario {id_usuario} no encontrado.",
            )
        return usuario

    def actualizar_usuario(self, id_usuario: int, datos: UsuarioUpdate, db: Session) -> Usuario:
        usuario = self.obtener_usuario(id_usuario, db)
        cambios = datos.model_dump(exclude_unset=True)

        if "id_rol" in cambios and cambios["id_rol"] is not None:
            self._validar_rol(cambios["id_rol"], db)

        if "contrasena" in cambios:
            if not cambios["contrasena"]:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="La contraseña no puede estar vacía.",
                )
            cambios["contrasena"] = hash_password(cambios["contrasena"])

        for campo, valor in cambios.items():
            setattr(usuario, campo, valor)

        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            pgcode = getattr(getattr(exc, "orig", None), "pgcode", None)
            if pgcode == PG_UNIQUE_VIOLATION:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Ya existe un usuario con el nombre '{datos.nombre_usuario}'.",
                )
            logger.error("Error de integridad al actualizar usuario: %s", exc.orig)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No se pudo actualizar el usuario: {exc.orig}",
            )
        db.refresh(usuario)
        return usuario

    def eliminar_usuario(self, id_usuario: int, db: Session) -> Usuario:
        usuario = self.obtener_usuario(id_usuario, db)
        usuario.estado = "inactivo"
        db.commit()
        db.refresh(usuario)
        return usuario

    def login(self, datos: UsuarioLogin, db: Session) -> Usuario:
        usuario = db.query(Usuario).filter(
            Usuario.nombre_usuario == datos.nombre_usuario
        ).first()

        credenciales_ok = (
            usuario is not None
            and usuario.estado == "activo"
            and verify_password(datos.contrasena, usuario.contrasena)
        )
        if not credenciales_ok:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Usuario o contraseña incorrectos.",
            )
        return usuario


usuario_service = UsuarioService()
