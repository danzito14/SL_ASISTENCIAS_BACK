# workers/models/area_trabajo.py
# workers es dueño de Trabajador (+ Embedding). AreaTrabajo pertenece a tenancy;
# aquí se incluye una copia MÍNIMA (solo lo que el facade Tenancy_Service lee:
# id_area/id_empresa/estado) y SIN relaciones cross-domain.
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, LargeBinary
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from src.core.pgdb import Base


class AreaTrabajo(Base):
    __tablename__ = "area_trabajo"

    id_area     = Column(Integer, primary_key=True, autoincrement=True)
    nombre_area = Column(String(100), nullable=False)
    id_empresa  = Column(Integer)
    # Clasificación del área para el sync: 'oficina' | 'empaque' | 'campo'.
    tipo_area   = Column(String(20), nullable=True, default=None)
    estado      = Column(String(10), default="activo")
    # (Otras columnas —ubicacion/hora_entrada/...— las maneja tenancy; aquí no se necesitan.)


class Trabajador(Base):
    __tablename__ = "trabajadores"

    id_trabajador = Column(Integer, primary_key=True, autoincrement=True)
    # Identidad EXTERNA en la nómina SYS21 (la sincroniza employee_monitoring).
    # NULL en trabajadores creados manualmente vía workers. (id_emp, origen_nomina)
    # es único (índice parcial) y es la clave de conflicto del upsert del sync.
    id_emp = Column(String(50), nullable=True, default=None)
    origen_nomina = Column(String(30), nullable=True, default=None)
    nombre = Column(String(100), nullable=False)
    apellido = Column(String(100), nullable=False)
    id_area = Column(Integer, ForeignKey("area_trabajo.id_area"), nullable=False)
    # id_empresa denormalizado (aislamiento multi-tenant sin joins).
    id_empresa = Column(Integer)
    permiso_escaneo = Column(String(20), nullable=False, default="campo")
    nivel_acceso_interno = Column(String(20), nullable=True, default=None)  # NULL = sin acceso interno (campo)
    foto_perfil = Column(LargeBinary)
    estado = Column(String(15), default="activo")
    inactivo_por_cascada = Column(Boolean, nullable=False, default=False)
    fecha_creacion = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    fecha_actualizacion = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Solo la relación intra-dominio con su embedding (1:1).
    embedding = relationship("Embedding", back_populates="trabajador", uselist=False)
