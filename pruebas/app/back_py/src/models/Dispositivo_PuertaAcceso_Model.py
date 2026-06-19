# app/models/dispositivo.py
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Date, ForeignKey
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography
from datetime import datetime, timezone
from src.core.pgdb import Base


class Dispositivo(Base):
    __tablename__ = "dispositivos"

    id_dispositivo     = Column(Integer, primary_key=True, autoincrement=True)
    nombre_dispositivo = Column(String(100), nullable=False)
    tipo_dispositivo   = Column(String(20), nullable=False)
    ip_dispositivo     = Column(String(45), unique=True)
    puerto             = Column(Integer, default=8080)
    ubicacion          = Column(Geography(geometry_type="POINT", srid=4326))
    id_area            = Column(Integer, ForeignKey("area_trabajo.id_area"))
    estado             = Column(String(15), default="activo")
    ultima_conexion    = Column(DateTime(timezone=True))
    fecha_instalacion  = Column(Date)
    fecha_creacion     = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    area       = relationship("AreaTrabajo", back_populates="dispositivos")
    puerta     = relationship("PuertaAcceso", back_populates="dispositivo", uselist=False)
    asistencias = relationship("Asistencia", back_populates="dispositivo")


class PuertaAcceso(Base):
    __tablename__ = "puertas_acceso"

    id_puerta = Column(Integer, primary_key=True, autoincrement=True)
    nombre_puerta = Column(String(100), nullable=False)
    ubicacion = Column(Geography(geometry_type="POINT", srid=4326))
    id_area = Column(Integer, ForeignKey("area_trabajo.id_area"))
    id_empresa = Column(Integer, ForeignKey("empresas.id_empresa", ondelete="CASCADE", onupdate="CASCADE"))
    id_dispositivo = Column(Integer, ForeignKey("dispositivos.id_dispositivo"), unique=True)
    tipo_acceso = Column(String(15), default="bidireccional")
    requiere_autorizacion = Column(Boolean, default=False)
    estado = Column(String(10), default="activo")
    fecha_creacion = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    empresa = relationship("Empresa", back_populates="puertas")
    area = relationship("AreaTrabajo", back_populates="puertas")
    dispositivo = relationship("Dispositivo", back_populates="puerta")
    asistencias = relationship("Asistencia", back_populates="puerta")