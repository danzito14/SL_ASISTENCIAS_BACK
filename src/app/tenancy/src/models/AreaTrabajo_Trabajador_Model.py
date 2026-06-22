# tenancy/models/area_trabajo.py
# Copia RECORTADA: tenancy es dueño de AreaTrabajo. La clase Trabajador y la
# relación 'trabajadores' viven en el dominio workers (otro servicio); aquí se
# omiten para no acoplar el mapper a un modelo de otro dominio.
from sqlalchemy import Column, Integer, String, Text, Time, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography
from datetime import datetime, timezone
from src.core.pgdb import Base


class AreaTrabajo(Base):
    __tablename__ = "area_trabajo"

    id_area              = Column(Integer, primary_key=True, autoincrement=True)
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
    dispositivos = relationship("Dispositivo", back_populates="area")
    puertas      = relationship("PuertaAcceso", back_populates="area")
