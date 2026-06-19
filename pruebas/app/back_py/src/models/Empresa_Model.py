# app/models/empresa.py
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography
from datetime import datetime, timezone
from src.core.pgdb import Base


class Empresa(Base):
    __tablename__ = "empresas"

    id_empresa     = Column(Integer, primary_key=True, autoincrement=True)
    nombre_empresa = Column(String(100), nullable=False)
    ubicacion      = Column(Geography(geometry_type="POLYGON", srid=4326), nullable=False)
    zona_horaria   = Column(Text, nullable=False)
    estado         = Column(Text, nullable=False)
    fecha_creacion = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    areas   = relationship("AreaTrabajo", back_populates="empresa")
    puertas = relationship("PuertaAcceso", back_populates="empresa")
