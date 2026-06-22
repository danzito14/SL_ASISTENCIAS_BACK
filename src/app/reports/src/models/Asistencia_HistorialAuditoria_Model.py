# reports/models/asistencia.py — modelo de SOLO LECTURA (sin relaciones).
from sqlalchemy import Column, Integer, String, Numeric, Text, DateTime
from sqlalchemy.dialects.postgresql import UUID
from src.core.pgdb import Base


class Asistencia(Base):
    __tablename__ = "asistencia"
    id_asistencia        = Column(UUID(as_uuid=True), primary_key=True)
    id_trabajador        = Column(Integer)
    id_empresa           = Column(Integer)
    tipo_registro        = Column(String(10))
    fecha_hora           = Column(DateTime(timezone=True))
    confianza_biometrica = Column(Numeric(3, 2))
    estado_registro      = Column(String(15))
    observaciones        = Column(Text)
