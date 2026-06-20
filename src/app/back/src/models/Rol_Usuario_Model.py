# app/models/rol.py
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from src.core.pgdb import Base


class Rol(Base):
    __tablename__ = "roles"

    id_rol         = Column(Integer, primary_key=True, autoincrement=True)
    nombre_rol     = Column(String(50), unique=True, nullable=False)
    descripcion    = Column(Text)
    permisos       = Column(JSONB)
    estado         = Column(String(10), default="activo")
    fecha_creacion = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    usuarios = relationship("Usuario", back_populates="rol")


class Usuario(Base):
    __tablename__ = "usuarios"

    id_usuario = Column(Integer, primary_key=True, autoincrement=True)
    nombre_usuario = Column(String(50), unique=True, nullable=False)
    contrasena = Column(String(255), nullable=False)
    id_rol = Column(Integer, ForeignKey("roles.id_rol"), nullable=False)
    estado = Column(String(10), default="activo")
    inactivo_por_cascada = Column(Boolean, nullable=False, default=False)
    # Empresa a la que pertenece el usuario. El valor EMPRESA_ADMIN (99) es un
    # comodín: el usuario puede ver/operar TODAS las empresas (super-admin).
    empresa = Column(Integer, ForeignKey("empresas.id_empresa"), default=1)
    fecha_creacion = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    fecha_actualizacion = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    rol = relationship("Rol", back_populates="usuarios")
    historial = relationship("HistorialAuditoria", back_populates="usuario")