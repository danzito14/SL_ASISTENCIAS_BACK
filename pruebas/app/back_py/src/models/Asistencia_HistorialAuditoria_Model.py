# app/models/asistencia.py
from sqlalchemy import Column, Integer, String, Numeric, Text, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from geoalchemy2 import Geography
from datetime import datetime, timezone
from src.core.pgdb import Base


class Asistencia(Base):
    __tablename__ = "asistencia"

    id_asistencia        = Column(Integer, primary_key=True, autoincrement=True)
    id_trabajador        = Column(Integer, ForeignKey("trabajadores.id_trabajador"), nullable=False)
    id_puerta            = Column(Integer, ForeignKey("puertas_acceso.id_puerta"), nullable=False)
    tipo_registro        = Column(String(10), nullable=False)
    fecha_hora           = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    confianza_biometrica = Column(Numeric(3, 2))
    estado_registro      = Column(String(10), default="exitoso")
    observaciones        = Column(Text)
    id_dispositivo       = Column(Integer, ForeignKey("dispositivos.id_dispositivo"))
    ubicacion            = Column(Geography(geometry_type="POINT", srid=4326))
    fecha_creacion       = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    trabajador  = relationship("Trabajador", back_populates="asistencias")
    puerta      = relationship("PuertaAcceso", back_populates="asistencias")
    dispositivo = relationship("Dispositivo", back_populates="asistencias")


class HistorialAuditoria(Base):
    __tablename__ = "historial_auditoria"

    id_auditoria = Column(Integer, primary_key=True, autoincrement=True)
    id_usuario = Column(Integer, ForeignKey("usuarios.id_usuario"))
    tabla_modificada = Column(String(100), nullable=False)
    tipo_operacion = Column(String(10), nullable=False)
    id_registro_afectado = Column(Integer)
    valores_anteriores = Column(JSONB)
    valores_nuevos = Column(JSONB)
    ip_origen = Column(String(45))
    user_agent = Column(String(255))
    fecha_hora = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    usuario = relationship("Usuario", back_populates="historial")