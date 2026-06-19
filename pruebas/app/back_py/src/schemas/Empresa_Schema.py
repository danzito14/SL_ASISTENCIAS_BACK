# app/schemas/empresa.py
from pydantic import BaseModel, Field
from datetime import datetime

from src.schemas._geo import GeografiaWKT


class EmpresaBase(BaseModel):
    nombre_empresa: str
    zona_horaria:   str
    estado:         str = "activo"


class EmpresaCreate(EmpresaBase):
    # Ubicación como zona (geography POLYGON,4326): lista de [longitud, latitud].
    # El anillo se cierra solo; mínimo 3 puntos. Obligatoria (la columna es NOT NULL).
    coordenadas: list[tuple[float, float]] = Field(
        min_length=3,
        description="Vértices del polígono como [longitud, latitud]; mínimo 3.",
    )


class EmpresaUpdate(BaseModel):
    # Actualización parcial: solo se modifican los campos enviados.
    nombre_empresa: str | None = None
    zona_horaria:   str | None = None
    estado:         str | None = None
    coordenadas: list[tuple[float, float]] | None = Field(
        default=None,
        min_length=3,
        description="Nueva zona como [longitud, latitud]; mínimo 3 puntos.",
    )


class EmpresaResponse(EmpresaBase):
    id_empresa:     int
    ubicacion:      GeografiaWKT = None   # sale como WKT, ej: 'POLYGON ((...))'
    fecha_creacion: datetime

    model_config = {"from_attributes": True}
