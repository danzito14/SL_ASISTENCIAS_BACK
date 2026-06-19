# app/models/intento_acceso.py
from sqlalchemy import Column, Integer, String, Numeric, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography
from datetime import datetime, timezone
from src.core.pgdb import Base


class IntentoAcceso(Base):
    """
    Intentos de acceso RECHAZADOS en una puerta (spoofing, desconocido, otra
    empresa). A diferencia de las incidencias, NO requieren trabajador: son
    eventos de la PUERTA, scopeados por la empresa de la puerta (id_empresa).
    """
    __tablename__ = "intentos_acceso"

    id_intento    = Column(Integer, primary_key=True, autoincrement=True)
    id_puerta     = Column(Integer, ForeignKey("puertas_acceso.id_puerta"))
    id_empresa    = Column(Integer, ForeignKey("empresas.id_empresa"))
    tipo          = Column(String(20), nullable=False)   # 'spoofing' | 'desconocido' | 'otra_empresa'
    id_trabajador = Column(Integer, ForeignKey("trabajadores.id_trabajador"))  # solo en 'otra_empresa'
    similitud     = Column(Numeric(4, 3))
    ruta_foto     = Column(Text)
    ubicacion     = Column(Geography(geometry_type="POINT", srid=4326))
    fecha         = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    trabajador = relationship("Trabajador")
    puerta     = relationship("PuertaAcceso")
