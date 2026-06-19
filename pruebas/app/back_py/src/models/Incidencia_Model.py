# app/models/incidencia.py
from sqlalchemy import Column, Integer, String, Text, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from src.core.pgdb import Base


class Incidencia(Base):
    """
    Incidencias de los trabajadores (faltas, retardos, salidas/entradas sin
    registro, escaneos fuera de área). Algunas las generan los triggers/funciones
    de la BD; otras se registran manualmente desde el panel.
    """
    __tablename__ = "incidencias"

    id_incidencia   = Column(Integer, primary_key=True, autoincrement=True)
    id_trabajador   = Column(Integer, ForeignKey("trabajadores.id_trabajador"), nullable=False)
    tipo_incidencia = Column(String(30), nullable=False)
    fecha           = Column(Date, nullable=False)
    descripcion     = Column(Text)
    ruta_foto       = Column(Text)
    id_escaneo_ref  = Column(Integer, ForeignKey("escaneos.id_escaneo"))
    estado          = Column(String(15), default="pendiente")
    fecha_creacion  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    trabajador = relationship("Trabajador")
    escaneo    = relationship("Escaneo")
