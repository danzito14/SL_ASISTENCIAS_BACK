# app/models/intento_acceso.py
from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography
from datetime import datetime, timezone
from src.core.pgdb import Base


class IntentoAcceso(Base):
    """
    Intentos de acceso RECHAZADOS en una puerta (spoofing, desconocido, otra
    empresa). A diferencia de las incidencias, NO requieren trabajador: son
    eventos de la PUERTA, scopeados por la empresa de la puerta (id_empresa).

    PK UUIDv7 + columnas de sincronización, por consistencia con el resto del
    modelo offline-first (los crea el scanner; ver scanner_service).
    """
    __tablename__ = "intentos_acceso"

    id_intento            = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_uuid_v7()"))
    id_puerta             = Column(Integer, ForeignKey("puertas_acceso.id_puerta"))
    id_empresa            = Column(Integer, ForeignKey("empresas.id_empresa"))
    tipo                  = Column(String(20), nullable=False)   # 'spoofing' | 'desconocido' | 'otra_empresa'
    id_trabajador         = Column(Integer, ForeignKey("trabajadores.id_trabajador"))  # solo en 'otra_empresa'
    similitud             = Column(Float)
    ruta_foto             = Column(Text)
    ubicacion             = Column(Geography(geometry_type="POINT", srid=4326))
    id_dispositivo        = Column(Integer, ForeignKey("dispositivos.id_dispositivo"))
    id_dispositivo_origen = Column(Integer)
    creado_en_cliente     = Column(DateTime(timezone=True))
    sincronizado_en       = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    fecha                 = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    trabajador = relationship("Trabajador")
    puerta     = relationship("PuertaAcceso")
