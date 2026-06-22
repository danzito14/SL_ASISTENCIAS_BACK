# app/schemas/empresa.py
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Literal

from src.schemas._geo import GeografiaWKT

EstadoGenerico = Literal["activo", "inactivo"]


class EmpresaBase(BaseModel):
    nombre_empresa: str
    zona_horaria:   str
    estado:         EstadoGenerico = "activo"


class EmpresaCreate(EmpresaBase):
    # Ubicación como zona (geography POLYGON,4326): lista de [longitud, latitud].
    # El anillo se cierra solo; mínimo 3 puntos. Opcional (la columna admite NULL):
    # una empresa puede crearse sin geocerca y definirla después.
    coordenadas: list[tuple[float, float]] | None = Field(
        default=None,
        min_length=3,
        description="Vértices del polígono como [longitud, latitud]; mínimo 3.",
    )


class EmpresaUpdate(BaseModel):
    # Actualización parcial: solo se modifican los campos enviados.
    nombre_empresa: str | None = None
    zona_horaria:   str | None = None
    estado:         EstadoGenerico | None = None
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
