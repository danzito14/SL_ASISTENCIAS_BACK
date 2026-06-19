"""
insertar_embedding.py
─────────────────────
Inserta datos de prueba en FP_PRUEBAS:
  - 1 área de trabajo
  - 1 trabajador
  - 1 embedding con vector aleatorio de 512 dimensiones

Requiere:
    pip install sqlalchemy psycopg2-binary pgvector numpy
"""

import numpy as np
from sqlalchemy import (
    create_engine, Column, Integer, String, Text,
    Boolean, Numeric, Date, DateTime, ForeignKey
)
from sqlalchemy.orm import DeclarativeBase, relationship, Session
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector
from datetime import datetime, timezone

# ─── Configuración de conexión ────────────────────────────────────────────────
DB_CONFIG = {
    "host":     "localhost",
    "port":     5432,
    "user":     "root",
    "password": "root",
    "dbname":   "FP_PRUEBAS",
}

DATABASE_URL = (
    "postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}"
    .format(**DB_CONFIG)
)

VECTOR_DIM = 512  # Ajusta según tu modelo (FaceNet=128, VGGFace2=512, OpenAI=1536)

# ─── Modelos ORM ──────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    pass


class AreaTrabajo(Base):
    __tablename__ = "area_trabajo"

    id_area        = Column(Integer, primary_key=True)
    nombre_area    = Column(String(100), nullable=False, unique=True)
    descripcion    = Column(Text)
    ubicacion      = Column(String(255))
    estado         = Column(String(10), default="activo")
    fecha_creacion = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    trabajadores = relationship("Trabajador", back_populates="area")


class Trabajador(Base):
    __tablename__ = "trabajadores"

    id_trabajador       = Column(Integer, primary_key=True)
    nombre              = Column(String(100), nullable=False)
    apellido            = Column(String(100), nullable=False)
    id_area             = Column(Integer, ForeignKey("area_trabajo.id_area"), nullable=False)
    foto_perfil         = Column(Text)
    estado              = Column(String(15), default="activo")
    fecha_creacion      = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    fecha_actualizacion = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    area      = relationship("AreaTrabajo", back_populates="trabajadores")
    embedding = relationship("Embedding", back_populates="trabajador", uselist=False)


class Embedding(Base):
    __tablename__ = "embeddings"

    id_embedding      = Column(Integer, primary_key=True)
    id_trabajador     = Column(Integer, ForeignKey("trabajadores.id_trabajador", ondelete="CASCADE"), nullable=False, unique=True)
    vector_embedding  = Column(Vector(VECTOR_DIM), nullable=False)
    tipo_embedding    = Column(String(10), default="facial")
    fecha_captura     = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    calidad_embedding = Column(Numeric(3, 2))
    modelo_ia         = Column(String(100))
    estado            = Column(String(10), default="activo")

    trabajador = relationship("Trabajador", back_populates="embedding")


# ─── Helpers ──────────────────────────────────────────────────────────────────
def generar_vector_aleatorio(dim: int = VECTOR_DIM) -> list[float]:
    """Genera un vector unitario aleatorio (normalizado L2)."""
    v = np.random.rand(dim).astype(np.float32)
    v /= np.linalg.norm(v)
    return v.tolist()


def insertar_datos_prueba(session: Session) -> None:
    # 1. Área de trabajo
    area = AreaTrabajo(
        nombre_area = "Desarrollo de Software",
        descripcion = "Área de ingeniería y desarrollo",
        ubicacion   = "Piso 2, Edificio A",
    )
    session.add(area)
    session.flush()  # Obtiene id_area sin hacer commit
    print(f"✔ Área creada  → id_area: {area.id_area}")

    # 2. Trabajador
    trabajador = Trabajador(
        nombre   = "Juan",
        apellido = "Pérez",
        id_area  = area.id_area,
    )
    session.add(trabajador)
    session.flush()
    print(f"✔ Trabajador   → id_trabajador: {trabajador.id_trabajador}")

    # 3. Embedding con vector aleatorio
    vector = generar_vector_aleatorio()
    embedding = Embedding(
        id_trabajador     = trabajador.id_trabajador,
        vector_embedding  = vector,
        tipo_embedding    = "facial",
        calidad_embedding = round(float(np.random.uniform(0.85, 0.99)), 2),
        modelo_ia         = "VGGFace2",
    )
    session.add(embedding)
    session.flush()
    print(f"✔ Embedding    → id_embedding: {embedding.id_embedding}")
    print(f"  Dimensiones  : {len(vector)}")
    print(f"  Primeros 5   : {[round(x, 6) for x in vector[:5]]}")
    print(f"  Calidad      : {embedding.calidad_embedding}")

    session.commit()
    print("\n✅ Todo insertado correctamente.")


# ─── Búsqueda de ejemplo por similitud coseno ─────────────────────────────────
def buscar_similares(session: Session, vector_consulta: list[float], top_k: int = 3) -> None:
    print(f"\n🔍 Top {top_k} embeddings más similares (similitud coseno):")
    resultados = (
        session.query(
            Embedding,
            Embedding.vector_embedding.cosine_distance(vector_consulta).label("distancia"),
        )
        .order_by("distancia")
        .limit(top_k)
        .all()
    )
    for emb, dist in resultados:
        similitud = 1 - dist
        print(f"  id_embedding: {emb.id_embedding} | "
              f"trabajador: {emb.id_trabajador} | "
              f"similitud: {similitud:.4f}")


# ─── Main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    engine = create_engine(DATABASE_URL, echo=False)

    with Session(engine) as session:
        insertar_datos_prueba(session)

        # Búsqueda de prueba con un vector aleatorio
        vector_consulta = generar_vector_aleatorio()
        buscar_similares(session, vector_consulta)