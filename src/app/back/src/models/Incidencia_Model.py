# app/models/incidencia.py
from sqlalchemy import Column, Integer, String, Text, Date, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from src.core.pgdb import Base


class Incidencia(Base):
    """
    Incidencias de los trabajadores (faltas, retardos, salidas/entradas sin
    registro, escaneos fuera de área, área incorrecta, acceso a otra empresa).
    Algunas las generan las funciones de la BD (validar_escaneos_lote,
    procesar_salidas_dia); otras se registran manualmente desde el panel.

    PK UUIDv7; id_escaneo_ref apunta a escaneos.id_escaneo (también UUID).
    id_empresa denormalizado para el aislamiento multi-tenant.
    """
    __tablename__ = "incidencias"

    id_incidencia     = Column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_uuid_v7()"))
    id_trabajador     = Column(Integer, ForeignKey("trabajadores.id_trabajador"), nullable=False)
    id_empresa        = Column(Integer, ForeignKey("empresas.id_empresa", ondelete="CASCADE", onupdate="CASCADE"))
    tipo_incidencia   = Column(String(30), nullable=False)
    fecha             = Column(Date, nullable=False)
    descripcion       = Column(Text)
    ruta_foto         = Column(Text)
    id_escaneo_ref    = Column(UUID(as_uuid=True), ForeignKey("escaneos.id_escaneo"))
    estado            = Column(String(15), default="pendiente")
    creado_en_cliente = Column(DateTime(timezone=True))
    sincronizado_en   = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    fecha_creacion    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    trabajador = relationship("Trabajador")
    escaneo    = relationship("Escaneo")
