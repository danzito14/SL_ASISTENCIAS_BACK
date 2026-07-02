# reports/models/area_trabajo.py — modelo de SOLO LECTURA (sin relaciones).
from sqlalchemy import Column, Integer, String, Time
from src.core.pgdb import Base


class AreaTrabajo(Base):
    __tablename__ = "area_trabajo"
    id_area      = Column(Integer, primary_key=True)
    nombre_area  = Column(String(100))
    id_empresa   = Column(Integer)
    hora_entrada = Column(Time)   # hora de entrada esperada (para calcular retardos)


class Trabajador(Base):
    __tablename__ = "trabajadores"
    id_trabajador = Column(Integer, primary_key=True)
    id_emp        = Column(String(50))   # número de empleado externo (SYS21), para mostrar
    nombre        = Column(String(100))
    apellido      = Column(String(100))
    id_area       = Column(Integer)
    id_empresa    = Column(Integer)
    estado        = Column(String(15))
