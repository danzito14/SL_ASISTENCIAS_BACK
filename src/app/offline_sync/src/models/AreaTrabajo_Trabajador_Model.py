# offline_sync/models/area_trabajo_trabajador.py
# Copia MÍNIMA de las tablas compartidas (dueño real: workers/tenancy). Sin
# relaciones cross-domain para no arrastrar mappers de otros dominios.
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import relationship

from src.core.pgdb import Base


class AreaTrabajo(Base):
    __tablename__ = "area_trabajo"

    id_area     = Column(Integer, primary_key=True, autoincrement=True)
    nombre_area = Column(String(100), nullable=False)
    id_empresa  = Column(Integer)
    # Clasificación del área: 'oficina' | 'empaque' | 'campo'. Define el alcance del roster.
    tipo_area   = Column(String(20), nullable=True, default=None)
    estado      = Column(String(10), default="activo")


class Trabajador(Base):
    __tablename__ = "trabajadores"

    id_trabajador = Column(Integer, primary_key=True, autoincrement=True)
    # Identidad EXTERNA: SYS21 (origen 'agricola'/'agricola_com') o walk-in del APK
    # (origen 'apk', con id_emp = UUID del dispositivo). (id_emp, origen_nomina) es
    # único (índice parcial) y es la clave de conflicto del upsert.
    id_emp = Column(String(50), nullable=True, default=None)
    origen_nomina = Column(String(30), nullable=True, default=None)
    nombre = Column(String(100), nullable=False)
    apellido = Column(String(100), nullable=False)
    id_area = Column(Integer, ForeignKey("area_trabajo.id_area"), nullable=False)
    id_empresa = Column(Integer)
    permiso_escaneo = Column(String(20), nullable=False, default="campo")
    nivel_acceso_interno = Column(String(20), nullable=True, default=None)
    foto_perfil = Column(LargeBinary)
    estado = Column(String(15), default="activo")
    inactivo_por_cascada = Column(Boolean, nullable=False, default=False)
    fecha_creacion = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    fecha_actualizacion = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    embedding = relationship("Embedding", back_populates="trabajador", uselist=False)
