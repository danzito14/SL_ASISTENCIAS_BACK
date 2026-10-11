# employee_monitoring/models/regla_clasificacion.py
# Regla del clasificador del sync: puesto (agrícola) / departamento (comercial) de
# la nómina SYS21 → grupo local (oficina/empaque/campo), con reemplazos opcionales
# del permiso/nivel por defecto del grupo. Se administra por API (/emp_sync/reglas).
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint

from src.core.pgdb import Base


class ReglaClasificacion(Base):
    __tablename__ = "reglas_clasificacion"
    __table_args__ = (UniqueConstraint("origen_nomina", "clave", name="uq_regla_origen_clave"),)

    id_regla             = Column(Integer, primary_key=True, autoincrement=True)
    origen_nomina        = Column(String(30), nullable=False)   # 'agricola' | 'agricola_com'
    clave                = Column(String(150), nullable=False)  # puesto/depto NORMALIZADO (empate)
    nombre               = Column(String(150), nullable=False)  # como se capturó (para mostrar)
    grupo                = Column(String(20), nullable=False)   # 'oficina' | 'empaque' | 'campo'
    permiso_escaneo      = Column(String(20), nullable=True)    # NULL = default del grupo
    nivel_acceso_interno = Column(String(20), nullable=True)    # NULL = default del grupo
    actualizado_por      = Column(String(100), nullable=True)
    fecha_creacion       = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    fecha_actualizacion  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                                  onupdate=lambda: datetime.now(timezone.utc))
