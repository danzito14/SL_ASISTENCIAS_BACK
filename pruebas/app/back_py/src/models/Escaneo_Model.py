# app/models/escaneo.py
from sqlalchemy import Column, Integer, String, Numeric, Text, DateTime, ForeignKey
from geoalchemy2 import Geography
from datetime import datetime, timezone
from src.core.pgdb import Base


class Escaneo(Base):
    """
    Registro de cada escaneo del lector facial (entrada/salida). Sustituye a
    'asistencia' como bitácora cruda del scanner; conserva la misma estructura.
    """
    __tablename__ = "escaneos"

    id_escaneo           = Column(Integer, primary_key=True, autoincrement=True)
    id_trabajador        = Column(Integer, ForeignKey("trabajadores.id_trabajador"), nullable=False)
    id_puerta            = Column(Integer, ForeignKey("puertas_acceso.id_puerta"), nullable=False)
    tipo_registro        = Column(String(10), nullable=False)
    fecha_hora           = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    confianza_biometrica = Column(Numeric(3, 2))
    estado_registro      = Column(String(10), default="exitoso")
    observaciones        = Column(Text)
    id_dispositivo       = Column(Integer, ForeignKey("dispositivos.id_dispositivo"))
    fecha_creacion       = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    ubicacion            = Column(Geography(geometry_type="POINT", srid=4326))
