# reports/models/incidencia.py — modelo de SOLO LECTURA (sin relaciones).
from sqlalchemy import Column, Integer, String, Text, Date
from sqlalchemy.dialects.postgresql import UUID
from src.core.pgdb import Base


class Incidencia(Base):
    __tablename__ = "incidencias"
    id_incidencia   = Column(UUID(as_uuid=True), primary_key=True)
    id_trabajador   = Column(Integer)
    id_empresa      = Column(Integer)
    tipo_incidencia = Column(String(30))
    fecha           = Column(Date)
    estado          = Column(String(15))
    descripcion     = Column(Text)
