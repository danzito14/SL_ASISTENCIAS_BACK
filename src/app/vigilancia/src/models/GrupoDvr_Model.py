# vigilancia/models/GrupoDvr_Model.py
# Agrupa cámaras de SEGUIMIENTO (reid) por DVR/grabador: la contraseña del DVR vive
# UNA vez aquí (cifrada Fernet) y las cámaras del grupo la REUSAN (no repiten password).
# Espeja el patrón de Camara_Model: las columnas cruzadas (id_empresa) van como Integer
# plano; el FK a empresas lo enforcea la BD (migración 2026_07_reid_grupos.sql).
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, LargeBinary, String

from src.core.pgdb import Base


class GrupoDvr(Base):
    __tablename__ = "grupos_dvr"

    id_grupo_dvr       = Column(Integer, primary_key=True, autoincrement=True)
    nombre             = Column(String(100), nullable=False)
    id_empresa         = Column(Integer, nullable=True)
    host               = Column(String(45), nullable=True)   # IP del DVR (opcional)
    usuario            = Column(String(100), nullable=True)
    credencial_cifrada = Column(LargeBinary, nullable=True)   # password del DVR, Fernet; NUNCA texto plano
    # Opcional: password de las CÁMARAS del DVR para acceso por su IP DIRECTA (suele
    # diferir de la del DVR). Fallback del preview de canales IP. Cifrada Fernet.
    credencial_camaras_cifrada = Column(LargeBinary, nullable=True)
    estado             = Column(String(15), nullable=False, default="activo")  # estado_generico
    fecha_creacion     = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
