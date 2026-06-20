# app/schemas/embedding.py
from pydantic import BaseModel, field_validator
from datetime import datetime
from typing import Annotated
from decimal import Decimal


class EmbeddingBase(BaseModel):
    id_trabajador:     int
    tipo_embedding:    str = "facial"
    calidad_embedding: Decimal | None = None
    modelo_ia:         str | None = None
    estado:            str = "activo"


class EmbeddingCreate(EmbeddingBase):
    vector_embedding: list[float]

    @field_validator("vector_embedding")
    @classmethod
    def validar_dimension(cls, v: list[float]) -> list[float]:
        if len(v) not in (128, 512, 1536):
            raise ValueError(f"Dimensión de vector inválida: {len(v)}. Usa 128, 512 o 1536.")
        return v


class EmbeddingResponse(EmbeddingBase):
    id_embedding:  int
    fecha_captura: datetime
    # El vector no se expone en la respuesta por tamaño

    model_config = {"from_attributes": True}


class EmbeddingUpdate(BaseModel):
    """Actualización parcial: solo se modifican los campos enviados."""
    tipo_embedding:    str | None = None
    calidad_embedding: Decimal | None = None
    modelo_ia:         str | None = None
    estado:            str | None = None   # 'activo' | 'inactivo'


class EmbeddingDeleteResponse(BaseModel):
    """Resultado de un borrado TOTAL (la fila ya no existe en la BD)."""
    eliminado:     bool
    id_embedding:  int
    id_trabajador: int
    mensaje:       str