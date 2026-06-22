# reports/models/intento_acceso.py — modelo de SOLO LECTURA (sin relaciones).
from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.dialects.postgresql import UUID
from src.core.pgdb import Base


class IntentoAcceso(Base):
    __tablename__ = "intentos_acceso"
    id_intento    = Column(UUID(as_uuid=True), primary_key=True)
    id_puerta     = Column(Integer)
    id_empresa    = Column(Integer)
    tipo          = Column(String(20))
    id_trabajador = Column(Integer)
    similitud     = Column(Float)
    fecha         = Column(DateTime(timezone=True))
