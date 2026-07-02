# reports/models/empresa.py — modelo de SOLO LECTURA (sin relaciones).
from sqlalchemy import Column, Integer, String
from src.core.pgdb import Base


class Empresa(Base):
    __tablename__ = "empresas"
    id_empresa     = Column(Integer, primary_key=True)
    nombre_empresa = Column(String(100))
    zona_horaria   = Column(String)   # p.ej. 'America/Mazatlan' (para pasar UTC→local)
