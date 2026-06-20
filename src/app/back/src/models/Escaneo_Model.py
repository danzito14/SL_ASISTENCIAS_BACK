# app/models/escaneo.py
from sqlalchemy import Column, Integer, String, Numeric, Boolean, Text, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from geoalchemy2 import Geography
from datetime import datetime, timezone
from src.core.pgdb import Base


class Escaneo(Base):
    """
    Registro de cada escaneo del lector facial (entrada/salida). Sustituye a
    'asistencia' como bitácora cruda del scanner; conserva la misma estructura.

    OFFLINE-FIRST: la PK es UUIDv7 (la genera el cliente offline o el servidor con
    DEFAULT gen_uuid_v7()). id_empresa va denormalizado (aislamiento multi-tenant
    sin joins). Las columnas creado_en_cliente/sincronizado_en/id_dispositivo_origen
    son la metadata de sincronización (opcionales: un escaneo online llena menos).
    """
    __tablename__ = "escaneos"

    id_escaneo            = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_uuid_v7()"))
    id_trabajador         = Column(Integer, ForeignKey("trabajadores.id_trabajador"), nullable=False)
    id_puerta             = Column(Integer, ForeignKey("puertas_acceso.id_puerta"), nullable=False)
    id_empresa            = Column(Integer, ForeignKey("empresas.id_empresa", ondelete="CASCADE", onupdate="CASCADE"))
    tipo_registro         = Column(String(10), nullable=False)
    fecha_hora            = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    confianza_biometrica  = Column(Numeric(3, 2))
    estado_registro       = Column(String(15), default="exitoso")
    dentro_de_area        = Column(Boolean)
    observaciones         = Column(Text)
    id_dispositivo        = Column(Integer, ForeignKey("dispositivos.id_dispositivo"))
    id_dispositivo_origen = Column(Integer)
    ubicacion             = Column(Geography(geometry_type="POINT", srid=4326))
    creado_en_cliente     = Column(DateTime(timezone=True))
    sincronizado_en       = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    fecha_creacion        = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
