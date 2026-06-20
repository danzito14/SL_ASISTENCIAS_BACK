# app/models/parametro_sistema.py
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from datetime import datetime, timezone
from src.core.pgdb import Base


class ParametroSistema(Base):
    __tablename__ = "parametros_sistema"

    id_parametro        = Column(Integer, primary_key=True, autoincrement=True)
    clave               = Column(String(100), unique=True, nullable=False)
    valor               = Column(String(500), nullable=False)
    tipo                = Column(String(10), default="texto")
    descripcion         = Column(Text)
    editable            = Column(Boolean, default=True)
    fecha_actualizacion = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))