# app/models/area_trabajo.py
from sqlalchemy import Column, Integer, String, Text, Time, DateTime, ForeignKey, LargeBinary
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography
from datetime import datetime, timezone
from src.core.pgdb import Base


class AreaTrabajo(Base):
    __tablename__ = "area_trabajo"

    id_area        = Column(Integer, primary_key=True, autoincrement=True)
    nombre_area    = Column(String(100), unique=True, nullable=False)
    descripcion    = Column(Text)
    ubicacion      = Column(Geography(geometry_type="POLYGON", srid=4326))
    id_empresa     = Column(Integer, ForeignKey("empresas.id_empresa", ondelete="CASCADE", onupdate="CASCADE"))
    hora_entrada   = Column(Time)
    estado         = Column(String(10), default="activo")
    fecha_creacion = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    empresa      = relationship("Empresa", back_populates="areas")
    trabajadores = relationship("Trabajador", back_populates="area")
    dispositivos = relationship("Dispositivo", back_populates="area")
    puertas      = relationship("PuertaAcceso", back_populates="area")


class Trabajador(Base):
    __tablename__ = "trabajadores"

    id_trabajador = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(100), nullable=False)
    apellido = Column(String(100), nullable=False)
    id_area = Column(Integer, ForeignKey("area_trabajo.id_area"), nullable=False)
    foto_perfil = Column(LargeBinary)
    estado = Column(String(15), default="activo")
    fecha_creacion = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    fecha_actualizacion = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    area = relationship("AreaTrabajo", back_populates="trabajadores")
    embedding = relationship("Embedding", back_populates="trabajador", uselist=False)
    asistencias = relationship("Asistencia", back_populates="trabajador")