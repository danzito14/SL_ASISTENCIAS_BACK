# reports/models/embedding.py — modelo de SOLO LECTURA (sin relaciones).
# Solo metadatos: el vector (512-D) no se mapea; los reportes nunca lo exportan.
from sqlalchemy import Column, DateTime, Integer, String
from src.core.pgdb import Base


class Embedding(Base):
    __tablename__ = "embeddings"
    id_embedding  = Column(Integer, primary_key=True)
    id_trabajador = Column(Integer)
    modelo_ia     = Column(String(100))
    estado        = Column(String(15))
    fecha_captura = Column(DateTime(timezone=True))
