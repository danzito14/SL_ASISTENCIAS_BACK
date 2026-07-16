# vigilancia/models/EventoCamara_Model.py
# Bitácora/evidencia de lo que vio cada cámara. UUIDv7 (lo genera la BD por DEFAULT).
# id_escaneo/id_trabajador son enlaces SUAVES (sin FK): el escaneo lo crea el
# pipeline y puede vivir en otra BD a futuro.
from sqlalchemy import Column, DateTime, Float, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID

from src.core.pgdb import Base


class EventoCamara(Base):
    __tablename__ = "eventos_camara"

    id_evento         = Column(UUID(as_uuid=True), primary_key=True,
                               server_default=text("gen_uuid_v7()"))
    id_camara         = Column(Integer, nullable=False)
    id_empresa        = Column(Integer, nullable=True)
    id_puerta         = Column(Integer, nullable=True)
    tipo_evento       = Column(String(20), nullable=False)
    id_escaneo        = Column(UUID(as_uuid=True), nullable=True)   # enlace SUAVE (sin FK)
    id_trabajador     = Column(Integer, nullable=True)             # enlace SUAVE (sin FK)
    confianza         = Column(Float, nullable=True)
    face_px           = Column(Integer, nullable=True)
    mensaje           = Column(Text, nullable=True)
    ruta_frame        = Column(Text, nullable=True)
    fecha_hora        = Column(DateTime(timezone=True), server_default=text("NOW()"))
    creado_en_cliente = Column(DateTime(timezone=True), nullable=True)
    sincronizado_en   = Column(DateTime(timezone=True), server_default=text("NOW()"))
