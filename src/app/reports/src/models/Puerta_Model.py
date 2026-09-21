# reports/models/puerta.py — modelo de SOLO LECTURA (sin relaciones).
from sqlalchemy import Column, Integer, String
from src.core.pgdb import Base


class PuertaAcceso(Base):
    __tablename__ = "puertas_acceso"
    id_puerta     = Column(Integer, primary_key=True)
    nombre_puerta = Column(String(100))
