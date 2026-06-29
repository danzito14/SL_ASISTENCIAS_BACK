# app/models/area_trabajo.py
from sqlalchemy import Column, Integer, String, Text, Time, Boolean, DateTime, ForeignKey, LargeBinary, UniqueConstraint
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography
from datetime import datetime, timezone
from src.core.pgdb import Base


class AreaTrabajo(Base):
    __tablename__ = "area_trabajo"

    id_area              = Column(Integer, primary_key=True, autoincrement=True)
    # MULTI-TENANT: nombre_area ya NO es único global, sino por empresa.
    nombre_area          = Column(String(100), nullable=False)
    descripcion          = Column(Text)
    ubicacion            = Column(Geography(geometry_type="POLYGON", srid=4326))
    id_empresa           = Column(Integer, ForeignKey("empresas.id_empresa", ondelete="CASCADE", onupdate="CASCADE"))
    hora_entrada         = Column(Time)
    estado               = Column(String(10), default="activo")
    inactivo_por_cascada = Column(Boolean, nullable=False, default=False)
    fecha_creacion       = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("id_empresa", "nombre_area", name="uq_area_empresa_nombre"),
    )

    empresa      = relationship("Empresa", back_populates="areas")
    trabajadores = relationship("Trabajador", back_populates="area")
    dispositivos = relationship("Dispositivo", back_populates="area")
    puertas      = relationship("PuertaAcceso", back_populates="area")


class Trabajador(Base):
    __tablename__ = "trabajadores"

    id_trabajador = Column(Integer, primary_key=True, autoincrement=True)
    # Identidad EXTERNA en la nómina SYS21 (la pobla employee_monitoring). Es lo que
    # el front muestra como "número de empleado". NULL en altas manuales; único solo
    # junto con origen_nomina.
    id_emp = Column(String(50), nullable=True, default=None)
    origen_nomina = Column(String(30), nullable=True, default=None)
    nombre = Column(String(100), nullable=False)
    apellido = Column(String(100), nullable=False)
    id_area = Column(Integer, ForeignKey("area_trabajo.id_area"), nullable=False)
    # id_empresa denormalizado (aislamiento multi-tenant sin joins). Se deriva del área.
    id_empresa = Column(Integer, ForeignKey("empresas.id_empresa", ondelete="CASCADE", onupdate="CASCADE"))
    # Dónde puede fichar: 'campo' | 'administrativo' | 'general' | 'super'.
    permiso_escaneo = Column(String(20), nullable=False, default="campo")
    # Acceso a zonas internas (puertas control_acceso): 'oficina' | 'empaque' | 'mixto'.
    # NULL = sin acceso interno (lo típico de los de campo).
    nivel_acceso_interno = Column(String(20), nullable=True, default=None)
    foto_perfil = Column(LargeBinary)
    estado = Column(String(15), default="activo")
    inactivo_por_cascada = Column(Boolean, nullable=False, default=False)
    fecha_creacion = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    fecha_actualizacion = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    area = relationship("AreaTrabajo", back_populates="trabajadores")
    empresa = relationship("Empresa")
    embedding = relationship("Embedding", back_populates="trabajador", uselist=False)
    asistencias = relationship("Asistencia", back_populates="trabajador")
