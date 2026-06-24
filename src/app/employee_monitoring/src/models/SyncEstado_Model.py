# employee_monitoring/models/sync_estado.py
# Estado OPERATIVO de la sincronización con la nómina SYS21. Una fila por
# (id_emp, origen_nomina): guarda los hashes para detectar cambios de datos y de
# foto (full-scan idempotente) y banderas de control de corrida. El vínculo con el
# trabajador local vive en trabajadores.id_emp, no aquí.
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Integer, String, UniqueConstraint,
)

from src.core.pgdb import Base


class SyncEstado(Base):
    __tablename__ = "sync_estado"
    __table_args__ = (UniqueConstraint("id_emp", "origen_nomina", name="sync_estado_id_emp_origen_nomina_key"),)

    id_sync                 = Column(Integer, primary_key=True, autoincrement=True)
    id_emp                  = Column(String(50), nullable=False)
    origen_nomina           = Column(String(30), nullable=False)
    id_empresa              = Column(Integer)
    hash_datos              = Column(String(64))
    hash_foto               = Column(String(64))
    foto_mtime              = Column(BigInteger)   # mtime remoto (SFTP): foto nueva sin descargar
    foto_size               = Column(BigInteger)   # tamaño remoto (SFTP), idem
    estado_foto             = Column(String(20))   # 'ok' | 'pendiente' | 'sin_foto'
    visto_en_ultima_corrida = Column(Boolean, nullable=False, default=False)
    ultima_sync             = Column(DateTime(timezone=True))
    ultima_sync_ok          = Column(DateTime(timezone=True))
