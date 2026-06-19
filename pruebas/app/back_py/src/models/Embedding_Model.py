# app/models/embedding.py
from sqlalchemy import Column, Integer, String, Numeric, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from pgvector.sqlalchemy import Vector
from src.core.pgdb import Base

VECTOR_DIM = 512  # Ajusta según tu modelo: FaceNet=128, VGGFace2=512, OpenAI=1536


class Embedding(Base):
    __tablename__ = "embeddings"

    id_embedding      = Column(Integer, primary_key=True, autoincrement=True)
    id_trabajador     = Column(Integer, ForeignKey("trabajadores.id_trabajador", ondelete="CASCADE"), nullable=False, unique=True)
    vector_embedding  = Column(Vector(VECTOR_DIM), nullable=False)
    tipo_embedding    = Column(String(10), default="facial")
    fecha_captura     = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    calidad_embedding = Column(Numeric(3, 2))
    modelo_ia         = Column(String(100))
    estado            = Column(String(10), default="activo")

    trabajador = relationship("Trabajador", back_populates="embedding")